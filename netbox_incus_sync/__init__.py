from netbox.plugins import PluginConfig


class IncusSyncConfig(PluginConfig):
    name = 'netbox_incus_sync'
    verbose_name = 'Incus Sync'
    description = 'Intégration et synchronisation Incus'
    version = '0.2'
    base_url = 'incus-sync'
    min_version = '4.2.0'
    
    default_settings = {
        'socket_path': 'http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket',
        'default_cluster_type_slug': 'incus',
        'sync_interval': 60,
        'events_sync_interval': 15,  # Minutes entre chaque sync d'événements
        'events_lookback_minutes': 60,  # Fenêtre de temps pour récupérer les événements
    }
    
    def ready(self):
        super().ready()
        # Importer les jobs pour les enregistrer
        from .jobs import SyncIncusJob, SyncEventsJob


config = IncusSyncConfig