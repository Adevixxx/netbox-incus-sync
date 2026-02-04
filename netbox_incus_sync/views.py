from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.views import View
from django.http import JsonResponse
from netbox.views import generic
from utilities.views import register_model_view

from .models import IncusHost
from .forms import IncusHostForm
from .tables import IncusHostTable
from .jobs import SyncIncusJob, SyncEventsJob
from .incus_client import IncusClient


# ============================================
# CRUD Views for IncusHost
# ============================================

class IncusHostListView(generic.ObjectListView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable


@register_model_view(IncusHost)
class IncusHostView(generic.ObjectView):
    queryset = IncusHost.objects.all()
    
    def get_extra_context(self, request, instance):
        """Adds additional information to the context."""
        context = {}
        
        # URL information for multi-URL hosts
        if instance.connection_type == 'https':
            context['configured_urls'] = instance.get_https_urls()
            context['url_cache_valid'] = instance.is_url_cache_valid()
        
        # Try to retrieve connection info
        try:
            client = IncusClient(host=instance)
            success, message, extra_info = client.test_connection()
            
            context['connection_status'] = {
                'success': success,
                'message': message,
                'cluster_enabled': extra_info.get('cluster_enabled', False),
                'cluster_members': extra_info.get('cluster_members', 0),
                'server_name': extra_info.get('server_name', ''),
                'version': extra_info.get('version', ''),
                'connected_url': extra_info.get('connected_url', ''),
            }
        except Exception as e:
            context['connection_status'] = {
                'success': False,
                'message': str(e),
            }
        
        return context


@register_model_view(IncusHost, 'edit')
class IncusHostEditView(generic.ObjectEditView):
    queryset = IncusHost.objects.all()
    form = IncusHostForm


@register_model_view(IncusHost, 'delete')
class IncusHostDeleteView(generic.ObjectDeleteView):
    queryset = IncusHost.objects.all()


@register_model_view(IncusHost, 'changelog')
class IncusHostChangeLogView(generic.ObjectChangeLogView):
    queryset = IncusHost.objects.all()


class IncusHostBulkDeleteView(generic.BulkDeleteView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable


# ============================================
# Synchronization Views
# ============================================

class IncusSyncView(View):
    """Starts full Incus synchronization (instances, network, disks, events, cluster)."""
    
    def get(self, request):
        job = SyncIncusJob.enqueue()
        messages.success(request, f"Full Incus synchronization started (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


class IncusSyncEventsView(View):
    """Starts Incus events synchronization only."""
    
    def get(self, request):
        job = SyncEventsJob.enqueue()
        messages.success(request, f"Incus events synchronization started (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


# ============================================
# Utility Views
# ============================================

class IncusHostTestConnectionView(View):
    """Tests connection to an Incus host and returns the result in JSON."""
    
    def get(self, request, pk):
        host = get_object_or_404(IncusHost, pk=pk)
        
        try:
            client = IncusClient(host=host)
            success, message, extra_info = client.test_connection()
            
            # Retrieve additional info if connected
            if success:
                # Instance count
                try:
                    instances = client.get_instances(recursion=0)
                    extra_info['instances_count'] = len(instances)
                except:
                    extra_info['instances_count'] = 0
                
                # Storage pools
                try:
                    pools = client.get_storage_pools()
                    extra_info['storage_pools'] = [p.get('name', '') for p in pools]
                except:
                    extra_info['storage_pools'] = []
                
                # Networks
                try:
                    networks = client.get_networks()
                    extra_info['networks'] = [n.get('name', '') for n in networks if n.get('managed', False)]
                except:
                    extra_info['networks'] = []
                
                # Add URL cache info
                extra_info['cached_url'] = host.last_working_url
                extra_info['cache_valid'] = host.is_url_cache_valid()
            
            return JsonResponse({
                'success': success,
                'message': message,
                'data': extra_info,
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e),
                'data': {},
            }, status=500)


class IncusHostTestAllUrlsView(View):
    """Tests all configured URLs for an Incus host and returns the results."""
    
    def get(self, request, pk):
        host = get_object_or_404(IncusHost, pk=pk)
        
        if host.connection_type != 'https':
            return JsonResponse({
                'success': False,
                'message': 'This feature is only for HTTPS connections',
                'data': {},
            })
        
        try:
            # Create a client just to use the test method
            # We need to bypass the normal initialization to test all URLs
            urls = host.get_https_urls()
            
            if not urls:
                return JsonResponse({
                    'success': False,
                    'message': 'No URLs configured',
                    'data': {'urls': []},
                })
            
            # Test each URL individually
            results = []
            import requests
            import os
            
            for url in urls:
                result = {'url': url, 'success': False, 'message': ''}
                
                try:
                    test_session = requests.Session()
                    
                    # Configure certificates
                    if host.client_cert_path and host.client_key_path:
                        test_session.cert = (host.client_cert_path, host.client_key_path)
                    
                    # Configure SSL verification
                    if host.ca_cert_path and os.path.isfile(host.ca_cert_path):
                        test_session.verify = host.ca_cert_path
                    else:
                        test_session.verify = host.verify_ssl
                    
                    # Quick connection test
                    test_url = f"{url.rstrip('/')}/1.0"
                    response = test_session.get(test_url, timeout=5)
                    response.raise_for_status()
                    
                    data = response.json()
                    if data.get('type') == 'sync':
                        env = data.get('metadata', {}).get('environment', {})
                        server_name = env.get('server_name', 'Unknown')
                        version = env.get('server_version', 'Unknown')
                        result['success'] = True
                        result['message'] = f"Connected: {server_name} v{version}"
                    else:
                        result['message'] = 'Invalid response'
                        
                except requests.exceptions.SSLError as e:
                    result['message'] = f"SSL Error: {str(e)[:100]}"
                except requests.exceptions.ConnectionError as e:
                    result['message'] = f"Connection Error: {str(e)[:100]}"
                except requests.exceptions.Timeout:
                    result['message'] = "Timeout (5s)"
                except Exception as e:
                    result['message'] = f"Error: {str(e)[:100]}"
                finally:
                    try:
                        test_session.close()
                    except:
                        pass
                
                results.append(result)
            
            working_count = sum(1 for r in results if r['success'])
            
            return JsonResponse({
                'success': working_count > 0,
                'message': f"{working_count}/{len(results)} URLs working",
                'data': {
                    'urls': results,
                    'cached_url': host.last_working_url,
                    'cache_valid': host.is_url_cache_valid(),
                },
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e),
                'data': {},
            }, status=500)


class IncusHostClearCacheView(View):
    """Clears the URL cache for an Incus host."""
    
    def post(self, request, pk):
        host = get_object_or_404(IncusHost, pk=pk)
        
        old_url = host.last_working_url
        host.clear_url_cache()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f"Cache cleared (was: {old_url or 'empty'})",
            })
        
        messages.success(request, f"URL cache cleared for {host.name}")
        return redirect('plugins:netbox_incus_sync:incushost', pk=pk)
    
    def get(self, request, pk):
        # Allow GET for simple link-based clearing
        return self.post(request, pk)