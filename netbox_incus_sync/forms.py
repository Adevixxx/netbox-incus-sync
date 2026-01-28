from django import forms
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField
from utilities.forms.rendering import FieldSet
from virtualization.models import Cluster
from .models import IncusHost, ConnectionTypeChoices


class IncusHostForm(NetBoxModelForm):
    """
    Formulaire pour la création et l'édition d'un hôte Incus.
    
    Les certificats sont référencés par leurs chemins sur le système de fichiers,
    pas stockés dans la base de données pour des raisons de sécurité.
    """

    default_cluster = DynamicModelChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        label='Cluster par défaut',
        help_text="Cluster NetBox où seront créées les VMs synchronisées"
    )

    fieldsets = (
        FieldSet('name', 'connection_type', 'enabled', name='Général'),
        FieldSet('socket_path', name='Connexion Socket Unix'),
        FieldSet(
            'https_url', 
            'client_cert_path', 
            'client_key_path', 
            'ca_cert_path',
            'verify_ssl', 
            name='Connexion HTTPS'
        ),
        FieldSet('default_cluster', 'tags', name='Association NetBox'),
    )

    class Meta:
        model = IncusHost
        fields = (
            'name',
            'connection_type',
            'socket_path',
            'https_url',
            'client_cert_path',
            'client_key_path',
            'ca_cert_path',
            'verify_ssl',
            'enabled',
            'default_cluster',
            'tags',
        )
        widgets = {
            'client_cert_path': forms.TextInput(attrs={
                'placeholder': '/etc/netbox/incus/client.crt'
            }),
            'client_key_path': forms.TextInput(attrs={
                'placeholder': '/etc/netbox/incus/client.key'
            }),
            'ca_cert_path': forms.TextInput(attrs={
                'placeholder': '/etc/netbox/incus/server.crt (optionnel)'
            }),
        }
        help_texts = {
            'client_cert_path': (
                "Chemin absolu vers le certificat client. "
                "Le fichier doit être lisible par l'utilisateur NetBox."
            ),
            'client_key_path': (
                "Chemin absolu vers la clé privée. "
                "Permissions recommandées : chmod 600"
            ),
        }