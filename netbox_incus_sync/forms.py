from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField
from virtualization.models import Cluster
from .models import IncusHost


class IncusHostForm(NetBoxModelForm):
    """Formulaire pour la création et l'édition d'un hôte Incus."""
    
    default_cluster = DynamicModelChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        label='Cluster par défaut',
        help_text="Cluster NetBox où seront créées les VMs synchronisées"
    )

    class Meta:
        model = IncusHost
        fields = ('name', 'socket_path', 'enabled', 'default_cluster', 'tags')