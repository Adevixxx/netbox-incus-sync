from django import forms
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField
from utilities.forms.rendering import FieldSet
from virtualization.models import Cluster
from .models import IncusHost, ConnectionTypeChoices


class IncusHostForm(NetBoxModelForm):
    """
    Form for creating and editing an Incus host.
    
    Certificates are referenced by their filesystem paths,
    not stored in the database for security reasons.
    """

    default_cluster = DynamicModelChoiceField(
        queryset=Cluster.objects.all(),
        required=False,
        label='Default Cluster',
        help_text="NetBox Cluster where synchronized VMs will be created"
    )

    fieldsets = (
        FieldSet('name', 'connection_type', 'enabled', name='General'),
        FieldSet('socket_path', name='Unix Socket Connection'),
        FieldSet(
            'https_url', 
            'client_cert_path', 
            'client_key_path', 
            'ca_cert_path',
            'verify_ssl', 
            name='HTTPS Connection'
        ),
        FieldSet('default_cluster', 'tags', name='NetBox Association'),
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
                'placeholder': '/etc/netbox/incus/server.crt (optional)'
            }),
        }
        help_texts = {
            'client_cert_path': (
                "Absolute path to client certificate. "
                "File must be readable by NetBox user."
            ),
            'client_key_path': (
                "Absolute path to private key. "
                "Recommended permissions: chmod 600"
            ),
        }