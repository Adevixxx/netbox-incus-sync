from django import forms
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField
from utilities.forms.rendering import FieldSet
from virtualization.models import Cluster
from dcim.models import Site
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

    default_site = DynamicModelChoiceField(
        queryset=Site.objects.all(),
        required=False,
        label='Default Site',
        help_text="Site assigned to auto-created Devices for cluster nodes"
    )

    fieldsets = (
        FieldSet('name', 'connection_type', 'enabled', name='General'),
        FieldSet('socket_path', name='Unix Socket Connection'),
        FieldSet(
            'https_url',
            'https_urls',
            'url_cache_ttl',
            name='HTTPS Connection - URLs'
        ),
        FieldSet(
            'client_cert_path', 
            'client_key_path', 
            'ca_cert_path',
            'verify_ssl', 
            name='HTTPS Connection - Certificates'
        ),
        FieldSet('default_cluster', 'default_site', 'tags', name='NetBox Association'),
    )

    class Meta:
        model = IncusHost
        fields = (
            'name',
            'connection_type',
            'socket_path',
            'https_url',
            'https_urls',
            'url_cache_ttl',
            'client_cert_path',
            'client_key_path',
            'ca_cert_path',
            'verify_ssl',
            'enabled',
            'default_cluster',
            'default_site',
            'tags',
        )
        widgets = {
            'https_url': forms.TextInput(attrs={
                'placeholder': 'https://incus.example.com:8443'
            }),
            'https_urls': forms.Textarea(attrs={
                'placeholder': (
                    '# One URL per line, lines starting with # are ignored\n'
                    'https://incus1.example.com:8443\n'
                    'https://incus2.example.com:8443\n'
                ),
                'rows': 6,
            }),
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
            'https_url': (
                "Single server URL. For multiple servers, use the field below."
            ),
            'https_urls': (
                "Multiple server URLs for failover. One per line.\n"
                "The system tests each URL until one works and caches the result."
            ),
            'url_cache_ttl': (
                "How long (in seconds) to use a working URL before re-testing. "
                "Set to 0 to always test. Default: 300 (5 minutes)."
            ),
            'client_cert_path': (
                "Absolute path to client certificate. "
                "File must be readable by NetBox user."
            ),
            'client_key_path': (
                "Absolute path to private key. "
                "Recommended permissions: chmod 600"
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        
        # S'assurer que cleaned_data existe
        if cleaned_data is None:
            return cleaned_data
        
        connection_type = cleaned_data.get('connection_type')
        
        if connection_type == ConnectionTypeChoices.HTTPS:
            https_url = cleaned_data.get('https_url') or ''
            https_urls = cleaned_data.get('https_urls') or ''
            
            https_url = https_url.strip()
            https_urls = https_urls.strip()
            
            # Need at least one URL
            if not https_url and not https_urls:
                raise forms.ValidationError({
                    'https_url': "At least one HTTPS URL is required."
                })
            
            # Validate URL format in https_urls
            if https_urls:
                for i, line in enumerate(https_urls.split('\n'), 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # Basic URL validation
                    if not line.startswith(('http://', 'https://')):
                        raise forms.ValidationError({
                            'https_urls': f"Line {i}: URL must start with http:// or https://"
                        })
        
        return cleaned_data


class IncusHostClearCacheForm(forms.Form):
    """Simple form to confirm cache clearing."""
    confirm = forms.BooleanField(
        required=True,
        label="Confirm cache clear",
        help_text="This will force a re-test of all URLs on next connection."
    )