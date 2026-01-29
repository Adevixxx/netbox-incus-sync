"""
Jobs de synchronisation Incus pour NetBox.

Ce fichier contient uniquement l'orchestration.
La logique métier est dans le dossier services/.
"""

from netbox.jobs import JobRunner

from .incus_client import IncusClient
from .models import IncusHost
from .services import InstanceSyncService, NetworkSyncService, DiskSyncService
from .custom_fields import ensure_custom_fields_exist


class SyncIncusJob(JobRunner):
    """
    Job de synchronisation des instances Incus vers NetBox.
    
    Synchronise :
    - Instances (VMs/conteneurs)
    - Interfaces réseau
    - Adresses IP
    - Disques virtuels
    """
    
    class Meta:
        name = "Synchronisation Incus"

    def run(self, *args, **kwargs):
        self.logger.info("Initialisation de la synchronisation Incus...")
        
        # Créer les Custom Fields si nécessaire
        ensure_custom_fields_exist(logger=self.logger)
        
        # Récupération des hôtes configurés
        hosts = IncusHost.objects.filter(enabled=True)
        
        if not hosts.exists():
            self.logger.warning("Aucun hôte Incus configuré ou activé.")
            return

        # Initialiser les services
        instance_service = InstanceSyncService(logger=self.logger)
        network_service = NetworkSyncService(logger=self.logger)
        disk_service = DiskSyncService(logger=self.logger)
        
        # Préparer les tags
        instance_service.setup()
        
        # Statistiques
        stats = {
            'instances_created': 0,
            'instances_updated': 0,
            'instances_removed': 0,
            'interfaces_synced': 0,
            'ips_synced': 0,
            'disks_synced': 0,
        }
        
        # Traiter chaque hôte
        for host in hosts:
            self._process_host(host, instance_service, network_service, disk_service, stats)

        # Résumé
        self.logger.info(
            f"Synchronisation terminée. "
            f"Instances: +{stats['instances_created']} ~{stats['instances_updated']} -{stats['instances_removed']} | "
            f"Interfaces: {stats['interfaces_synced']} | IPs: {stats['ips_synced']} | "
            f"Disques: {stats['disks_synced']}"
        )

    def _process_host(self, host, instance_service, network_service, disk_service, stats):
        """
        Traite un hôte Incus.
        
        Args:
            host: Instance IncusHost
            instance_service: Service de sync des instances
            network_service: Service de sync réseau
            disk_service: Service de sync des disques
            stats: Dict des statistiques à mettre à jour
        """
        self.logger.info(f"Traitement de l'hôte : {host.name} ({host.get_connection_type_display()})")
        
        try:
            # Connexion au client
            client = IncusClient(host=host)
            
            # Test de connexion
            success, message = client.test_connection()
            if not success:
                self.logger.error(f"  Échec de connexion: {message}")
                return
                
            self.logger.info(f"  {message}")
            
            # Log des infos serveur
            self._log_server_info(client)
            
            # Récupérer les instances (recursion=2 pour avoir l'état)
            instances = client.get_instances(recursion=2)
            self.logger.info(f"  > {len(instances)} instances trouvées.")
            
            # Résoudre le cluster
            cluster = instance_service.resolve_cluster(host)
            
            # Collecter les noms pour la gestion des suppressions
            incus_instance_names = set()
            
            # Synchroniser chaque instance
            for instance_data in instances:
                instance_name = instance_data.get('name')
                incus_instance_names.add(instance_name)
                
                # Sync de l'instance
                vm, created, updated = instance_service.sync_instance(
                    instance_data, cluster, host
                )
                
                if created:
                    stats['instances_created'] += 1
                elif updated:
                    stats['instances_updated'] += 1
                
                # Sync du réseau
                if vm:
                    iface_count, ip_count = network_service.sync_instance_network(
                        vm, instance_data, client
                    )
                    stats['interfaces_synced'] += iface_count
                    stats['ips_synced'] += ip_count
                    
                    # Sync des disques
                    disk_count = disk_service.sync_instance_disks(
                        vm, instance_data, client
                    )
                    stats['disks_synced'] += disk_count
            
            # Gérer les suppressions
            deleted = instance_service.handle_deletions(cluster, incus_instance_names)
            stats['instances_removed'] += deleted
            
            # Log des réseaux Incus (informatif)
            networks = client.get_networks()
            network_service.log_networks_info(networks)
                
        except Exception as e:
            self.logger.error(f"Erreur lors du traitement de {host.name}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _log_server_info(self, client):
        """Log les informations du serveur Incus."""
        try:
            server_info = client.get_server_info()
            if server_info:
                env = server_info.get('environment', {})
                self.logger.info(f"  Serveur: {env.get('server_name', 'N/A')}")
                self.logger.info(f"  Version: {env.get('server_version', 'N/A')}")
        except Exception as e:
            self.logger.warning(f"  Impossible de récupérer les infos serveur: {e}")