from netbox.plugins import PluginConfig


class IncusSyncConfig(PluginConfig):
    name = "netbox_incus_sync"
    verbose_name = "Incus Sync"
    description = "Incus instance synchronization to NetBox"
    version = "1.0"
    base_url = "incus-sync"
    min_version = "4.2.0"

    def ready(self):
        super().ready()
        from .jobs import SyncIncusJob, SyncEventsJob


config = IncusSyncConfig
