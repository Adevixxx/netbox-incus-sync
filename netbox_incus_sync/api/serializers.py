from rest_framework import serializers
from netbox.api.serializers import NetBoxModelSerializer
from ..models import IncusHost


class IncusHostSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_incus_sync-api:incushost-detail"
    )
    connection_url = serializers.ReadOnlyField()
    configured_urls = serializers.SerializerMethodField()
    url_cache_valid = serializers.SerializerMethodField()
    sync_interval_display = serializers.ReadOnlyField()

    class Meta:
        model = IncusHost
        fields = (
            "id",
            "url",
            "display",
            "name",
            "connection_type",
            "socket_path",
            "https_urls",
            "last_working_url",
            "last_working_url_checked",
            "url_cache_ttl",
            "url_cache_valid",
            "configured_urls",
            "client_cert_path",
            "client_key_path",
            "ca_cert_path",
            "verify_ssl",
            "enabled",
            "sync_interval_value",
            "sync_interval_unit",
            "sync_interval_display",
            "default_cluster",
            "incus_ui_instance_url",
            "incus_ui_profile_url",
            "incus_ui_network_url",
            "incus_ui_storage_pool_url",
            "incus_ui_storage_volume_url",
            "incus_ui_project_url",
            "connection_url",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "connection_type")

        # Do not expose key paths in brief responses
        # to avoid disclosing sensitive information

        # Make cache fields read-only
        read_only_fields = ("last_working_url", "last_working_url_checked")

    def get_configured_urls(self, obj):
        """Returns the list of all configured HTTPS URLs."""
        if obj.connection_type == "https":
            return obj.get_https_urls()
        return []

    def get_url_cache_valid(self, obj):
        """Returns whether the URL cache is currently valid."""
        return obj.is_url_cache_valid()


class IncusHostBriefSerializer(NetBoxModelSerializer):
    """Brief serializer for nested representations."""

    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_incus_sync-api:incushost-detail"
    )

    class Meta:
        model = IncusHost
        fields = ("id", "url", "display", "name", "connection_type", "enabled")
