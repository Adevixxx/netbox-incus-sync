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