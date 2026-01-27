from rest_framework import serializers
from netbox.api.serializers import NetBoxModelSerializer
from ..models import IncusHost


class IncusHostSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name='plugins-api:netbox_incus_sync-api:incushost-detail'
    )

    class Meta:
        model = IncusHost
        fields = (
            'id',
            'url',
            'display',
            'name',
            'socket_path',
            'enabled',
            'default_cluster',
            'tags',
            'custom_fields',
            'created',
            'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name')