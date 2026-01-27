from netbox.plugins import PluginConfig


class IncusSyncConfig(PluginConfig):
    name = 'netbox_incus_sync'
    verbose_name = 'Incus Sync'
    description = 'Intégration et synchronisation Incus'
    version = '0.1'
    base_url = 'incus-sync'
    min_version = '4.2.0'
    
    default_settings = {
        'socket_path': 'http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
        'default_cluster_type_slug': 'incus',
        'sync_interval': 60,
    }
    
    def ready(self):
        super().ready()
        # Importer le job pour l'enregistrer
        from .jobs import SyncIncusJob


config = IncusSyncConfig