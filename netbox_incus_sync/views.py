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
# Vues CRUD pour IncusHost
# ============================================

class IncusHostListView(generic.ObjectListView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable


@register_model_view(IncusHost)
class IncusHostView(generic.ObjectView):
    queryset = IncusHost.objects.all()
    
    def get_extra_context(self, request, instance):
        """Ajoute des informations supplémentaires au contexte."""
        context = {}
        
        # Essayer de récupérer les infos de connexion
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
# Vues de synchronisation
# ============================================

class IncusSyncView(View):
    """Lance la synchronisation complète Incus (instances, réseau, disques, événements, cluster)."""
    
    def get(self, request):
        job = SyncIncusJob.enqueue()
        messages.success(request, f"Synchronisation complète Incus lancée (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


class IncusSyncEventsView(View):
    """Lance la synchronisation des événements Incus uniquement."""
    
    def get(self, request):
        job = SyncEventsJob.enqueue()
        messages.success(request, f"Synchronisation des événements Incus lancée (Job #{job.pk})")
        return redirect('plugins:netbox_incus_sync:incushost_list')


# ============================================
# Vues utilitaires
# ============================================

class IncusHostTestConnectionView(View):
    """Teste la connexion à un hôte Incus et retourne le résultat en JSON."""
    
    def get(self, request, pk):
        host = get_object_or_404(IncusHost, pk=pk)
        
        try:
            client = IncusClient(host=host)
            success, message, extra_info = client.test_connection()
            
            # Récupérer des infos supplémentaires si connecté
            if success:
                # Nombre d'instances
                try:
                    instances = client.get_instances(recursion=0)
                    extra_info['instances_count'] = len(instances)
                except:
                    extra_info['instances_count'] = 0
                
                # Pools de stockage
                try:
                    pools = client.get_storage_pools()
                    extra_info['storage_pools'] = [p.get('name', '') for p in pools]
                except:
                    extra_info['storage_pools'] = []
                
                # Réseaux
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