from netbox.plugins import PluginConfig


class IncusSyncConfig(PluginConfig):
    name = "netbox_incus_sync"
    verbose_name = "Incus Sync"
    description = "Incus instance synchronization to NetBox"
    version = "1.0"
    base_url = "incus-sync"
    min_version = "4.2.0"

    default_settings = {
        "incus_ui_url_patterns": {
            "instance": "{base_url}/ui/project/{project}/instance/{name}",
            "profile": "{base_url}/ui/project/{project}/profile/{name}",
            "network": "{base_url}/ui/project/{project}/network/{name}",
            "storage_pool": "{base_url}/ui/project/{project}/storage/pool/{name}",
            "storage_volume": "{base_url}/ui/project/{project}/storage/pool/{pool}/volumes/custom/{name}",
            "project": "{base_url}/ui/project/{name}",
        },
    }

    def ready(self):
        super().ready()
        from .jobs import SyncIncusJob, SyncEventsJob


config = IncusSyncConfig
