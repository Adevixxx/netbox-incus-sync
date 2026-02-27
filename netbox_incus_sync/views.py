from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import redirect, get_object_or_404
from django.views import View
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.utils import timezone
from netbox.views import generic
from utilities.views import register_model_view
from extras.models import ImageAttachment
from virtualization.models import VirtualMachine

from .models import IncusHost
from .forms import IncusHostForm
from .tables import IncusHostTable
from .jobs import SyncIncusJob, SyncEventsJob
from .incus_client import IncusClient
from .forms import IncusHostForm, IncusHostFilterForm, IncusHostBulkEditForm, IncusHostImportForm
from .filtersets import IncusHostFilterSet


# ============================================
# CRUD Views for IncusHost
# ============================================

class IncusHostListView(generic.ObjectListView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable
    filterset = IncusHostFilterSet
    filterset_form = IncusHostFilterForm        # ← sidebar filtres

class IncusHostBulkDeleteView(generic.BulkDeleteView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable

class IncusHostBulkEditView(generic.BulkEditView):
    queryset = IncusHost.objects.all()
    filterset = IncusHostFilterSet
    table = IncusHostTable
    form = IncusHostBulkEditForm

class IncusHostBulkImportView(generic.BulkImportView):
    queryset = IncusHost.objects.all()
    model_form = IncusHostImportForm


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
        
        # Retrieve VMs managed by this host
        managed_vms = VirtualMachine.objects.filter(
            custom_field_data__incus_host=instance.name
        ).order_by('name')
        
        # Get existing screenshots for these VMs
        vm_ct = ContentType.objects.get_for_model(VirtualMachine)
        screenshots = {}
        for attachment in ImageAttachment.objects.filter(
            object_type=vm_ct,
            object_id__in=managed_vms.values_list('pk', flat=True),
            name__startswith='incus-screenshot-'
        ).order_by('-created'):
            # Keep only the latest per VM
            if attachment.object_id not in screenshots:
                screenshots[attachment.object_id] = attachment
        
        # Build VM list with screenshot info
        vm_list = []
        for vm in managed_vms:
            vm_list.append({
                'vm': vm,
                'instance_type': vm.custom_field_data.get('incus_type', 'container'),
                'is_vm': vm.custom_field_data.get('incus_type', '') != 'container',
                'screenshot': screenshots.get(vm.pk),
            })
        
        context['managed_vms'] = vm_list
        context['managed_vms_count'] = managed_vms.count()
        
        return context


@register_model_view(IncusHost, 'edit')
class IncusHostEditView(generic.ObjectEditView):
    queryset = IncusHost.objects.all()
    form = IncusHostForm


@register_model_view(IncusHost, 'delete')
class IncusHostDeleteView(generic.ObjectDeleteView):
    queryset = IncusHost.objects.all()


# NOTE: ChangeLogView is NOT registered here explicitly.
# NetBoxModel + get_model_urls() already provides the changelog tab automatically.
# Registering it again with @register_model_view causes a duplicate "Changelog" tab.


class IncusHostBulkDeleteView(generic.BulkDeleteView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable


# ============================================
# Synchronization Views
# ============================================

class IncusSyncView(View):
    """Starts full Incus synchronization (all enabled hosts)."""
    
    def get(self, request):
        job = SyncIncusJob.enqueue()
        messages.success(request, f"Full Incus synchronization started (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


class IncusSyncHostView(View):
    """Starts synchronization for a single Incus host (or multiple via query params)."""
    
    def get(self, request, pk):
        """Sync a single host by PK."""
        host = get_object_or_404(IncusHost, pk=pk)
        if not host.enabled:
            messages.warning(request, f"Host '{host.name}' is disabled. Enable it first.")
            return redirect('plugins:netbox_incus_sync:incushost', pk=pk)
        
        job = SyncIncusJob.enqueue(host_ids=[host.pk])
        messages.success(request, f"Synchronization started for '{host.name}' (Job #{job.pk})")
        
        # Redirect back to where we came from
        next_url = request.GET.get('next')
        if next_url:
            return redirect(next_url)
        return redirect('plugins:netbox_incus_sync:incushost', pk=pk)
    
    def post(self, request):
        """Sync multiple hosts by PK (from list view bulk action)."""
        host_ids = request.POST.getlist('pk')
        if not host_ids:
            messages.warning(request, "No hosts selected.")
            return redirect('plugins:netbox_incus_sync:incushost_list')
        
        host_ids = [int(pk) for pk in host_ids]
        hosts = IncusHost.objects.filter(pk__in=host_ids, enabled=True)
        
        if not hosts.exists():
            messages.warning(request, "No enabled hosts found in selection.")
            return redirect('plugins:netbox_incus_sync:incushost_list')
        
        job = SyncIncusJob.enqueue(host_ids=list(hosts.values_list('pk', flat=True)))
        host_names = ', '.join(hosts.values_list('name', flat=True))
        messages.success(request, f"Synchronization started for {hosts.count()} host(s): {host_names} (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


class IncusSyncLogsView(View):
    """Starts Incus instance logs synchronization only."""
    
    def get(self, request):
        job = SyncEventsJob.enqueue()
        messages.success(request, f"Incus logs synchronization started (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


# ============================================
# Screenshot View
# ============================================

class IncusVMScreenshotView(View):
    """
    Captures a VGA console screenshot from Incus and attaches it to the VM
    as a NetBox ImageAttachment.
    
    Only works for virtual machines (not containers) that are running.
    Keeps only one screenshot per VM (deletes previous ones before creating new).
    
    Requires Incus >= 6.7 with instance_console_screenshot API extension.
    """
    
    def post(self, request, pk):
        vm = get_object_or_404(VirtualMachine, pk=pk)
        
        # Find the Incus host for this VM
        host_name = vm.custom_field_data.get('incus_host')
        if not host_name:
            return self._respond(
                request, vm, False,
                "This VM is not managed by Incus Sync (no incus_host field)."
            )
        
        try:
            host = IncusHost.objects.get(name=host_name, enabled=True)
        except IncusHost.DoesNotExist:
            return self._respond(
                request, vm, False,
                f"Incus host '{host_name}' not found or disabled."
            )
        
        # Check instance type - screenshots only work for VMs
        instance_type = vm.custom_field_data.get('incus_type', '')
        if instance_type == 'container':
            return self._respond(
                request, vm, False,
                "VGA screenshots are only available for virtual machines, not containers."
            )
        
        try:
            client = IncusClient(host=host)
            
            # Capture screenshot
            screenshot_data = client.get_instance_screenshot(vm.name)
            
            if not screenshot_data:
                return self._respond(
                    request, vm, False,
                    "Unable to capture screenshot. The VM may be stopped or the VGA console unavailable."
                )
            
            # Delete previous screenshots
            vm_ct = ContentType.objects.get_for_model(VirtualMachine)
            ImageAttachment.objects.filter(
                object_type=vm_ct,
                object_id=vm.pk,
                name__startswith='incus-screenshot-'
            ).delete()
            
            # Create new ImageAttachment
            timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
            filename = f"incus-screenshot-{vm.name}-{timestamp}.png"
            
            attachment = ImageAttachment(
                object_type=vm_ct,
                object_id=vm.pk,
                name=f"incus-screenshot-{vm.name}",
                image=ContentFile(screenshot_data, name=filename),
            )
            attachment.save()
            
            return self._respond(
                request, vm, True,
                f"Screenshot captured for {vm.name}",
                screenshot_url=attachment.image.url
            )
            
        except Exception as e:
            return self._respond(
                request, vm, False,
                f"Error capturing screenshot: {str(e)}"
            )
    
    def _respond(self, request, vm, success, message, screenshot_url=None):
        """Returns JSON or redirect response."""
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            data = {'success': success, 'message': message}
            if screenshot_url:
                data['screenshot_url'] = screenshot_url
            return JsonResponse(data)
        
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)
        return redirect(vm.get_absolute_url())


# ============================================
# Connection Test Views
# ============================================

class IncusHostTestConnectionView(View):
    """Tests connection to an Incus host and returns JSON results."""
    
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
        
        try:
            import requests as req_lib
            
            urls = host.get_https_urls()
            if not urls:
                return JsonResponse({
                    'success': False,
                    'message': 'No HTTPS URLs configured',
                    'data': {},
                })
            
            results = []
            for url in urls:
                result = {
                    'url': url,
                    'success': False,
                    'message': '',
                }
                
                try:
                    test_session = req_lib.Session()
                    
                    # Configure TLS
                    if host.client_cert_path and host.client_key_path:
                        test_session.cert = (host.client_cert_path, host.client_key_path)
                    
                    if host.ca_cert_path:
                        test_session.verify = host.ca_cert_path
                    elif not host.verify_ssl:
                        test_session.verify = False
                    
                    response = test_session.get(f"{url}/1.0", timeout=5)
                    
                    if response.status_code == 200:
                        result['success'] = True
                        data = response.json()
                        meta = data.get('metadata', {})
                        env = meta.get('environment', {})
                        result['message'] = (
                            f"OK - {env.get('server_name', '?')} "
                            f"v{env.get('server_version', '?')}"
                        )
                    else:
                        result['message'] = f"HTTP {response.status_code}: {response.text[:100]}"
                except req_lib.exceptions.ConnectionError as e:
                    result['message'] = f"Connection error: {str(e)[:100]}"
                except req_lib.exceptions.Timeout:
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
        return self.post(request, pk)