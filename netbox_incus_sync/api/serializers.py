from rest_framework import serializers
from netbox.api.serializers import NetBoxModelSerializer
from ..models import IncusHost


class IncusHostSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name='plugins-api:netbox_incus_sync-api:incushost-detail'
    )
    connection_url = serializers.ReadOnlyField()

    class Meta:
        model = IncusHost
        fields = (
            'id',
            'url',
            'display',
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
            'connection_url',
            'tags',
            'custom_fields',
            'created',
            'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'connection_type')
        
        # Ne pas exposer les chemins des clés dans les réponses brief
        # pour éviter de divulguer des informations sensibles