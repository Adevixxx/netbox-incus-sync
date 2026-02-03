from netbox.plugins import PluginConfig


class IncusSyncConfig(PluginConfig):
    name = 'netbox_incus_sync'
    verbose_name = 'Incus Sync'
    description = 'Incus instance synchronization to NetBox'
    version = '0.3'
    base_url = 'incus-sync'
    min_version = '4.2.0'
    
    default_settings = {
        'socket_path': 'http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
        'sync_interval': 60,  # Minutes between each full sync
        'events_sync_interval': 15,  # Minutes between each event sync
        'events_lookback_minutes': 60,  # Time window for retrieving events
    }
    
    def ready(self):
        super().ready()
        # Import jobs to register them
        from .jobs import SyncIncusJob, SyncEventsJob


config = IncusSyncConfig