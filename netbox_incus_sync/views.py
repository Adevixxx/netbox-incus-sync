from django.contrib import messages
from django.shortcuts import redirect
from django.views import View
from netbox.views import generic
from utilities.views import register_model_view

from .models import IncusHost
from .forms import IncusHostForm
from .tables import IncusHostTable
from .jobs import SyncIncusJob, SyncEventsJob


# ============================================
# Vues CRUD pour IncusHost
# ============================================

class IncusHostListView(generic.ObjectListView):
    queryset = IncusHost.objects.all()
    table = IncusHostTable


@register_model_view(IncusHost)
class IncusHostView(generic.ObjectView):
    queryset = IncusHost.objects.all()


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
    """Lance la synchronisation complète Incus (instances, réseau, disques, événements)."""
    
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