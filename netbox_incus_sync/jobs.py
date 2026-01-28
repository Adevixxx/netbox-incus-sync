from netbox.jobs import JobRunner
from virtualization.models import VirtualMachine, Cluster, ClusterType
from .incus_client import IncusClient
from .models import IncusHost


class SyncIncusJob(JobRunner):
    """
    Tâche de fond pour synchroniser les instances Incus vers NetBox.
    """
    
    class Meta:
        name = "Synchronisation Incus"

    def run(self, *args, **kwargs):
        self.logger.info("Initialisation de la synchronisation Incus...")
        
        # Récupération des hôtes configurés
        hosts = IncusHost.objects.filter(enabled=True)
        
        if not hosts.exists():
            self.logger.warning("Aucun hôte Incus configuré ou activé.")
            return

        total_synced = 0
        
        for host in hosts:
            self.logger.info(f"Traitement de l'hôte : {host.name} ({host.get_connection_type_display()})")
            
            try:
                # Instanciation du client avec l'objet host complet
                client = IncusClient(host=host)
                
                # Test de connexion
                success, message = client.test_connection()
                if not success:
                    self.logger.error(f"  Échec de connexion: {message}")
                    continue
                    
                self.logger.info(f"  {message}")
                
                instances = client.get_instances()
                self.logger.info(f"  > {len(instances)} instances trouvées.")
                
                # Résoudre le cluster
                cluster = self.resolve_cluster(host)
                
                # Synchroniser les instances
                for instance_data in instances:
                    self.sync_instance(instance_data, cluster)
                    total_synced += 1
                    
            except Exception as e:
                self.logger.error(f"Erreur lors du traitement de {host.name}: {e}")
                continue

        self.logger.info(f"Synchronisation terminée. {total_synced} instances traitées.")

    def resolve_cluster(self, host_obj):
        """Assure qu'un Cluster existe pour accueillir les VMs."""
        if host_obj.default_cluster:
            return host_obj.default_cluster
        
        # Fallback : Création d'un cluster par défaut
        ctype, _ = ClusterType.objects.get_or_create(
            name='Incus', 
            defaults={'slug': 'incus'}
        )
        
        cluster, _ = Cluster.objects.get_or_create(
            name=f"Cluster {host_obj.name}",
            defaults={'type': ctype}
        )
        return cluster

    def sync_instance(self, data, cluster):
        """Synchronise une instance Incus vers NetBox."""
        vm_name = data.get('name')
        status_raw = data.get('status')
        
        # Mapping du statut Incus vers NetBox
        nb_status = 'active' if status_raw == 'Running' else 'offline'
        
        config = data.get('config', {})
        
        # Extraction CPU
        try:
            vcpus = float(config.get('limits.cpu', 1))
        except (ValueError, TypeError):
            vcpus = 1
            
        # Extraction Mémoire (en MB)
        raw_mem = config.get('limits.memory', '')
        memory_mb = self.parse_memory(raw_mem)
        
        # Extraction Disque
        disk_mb = 0
        devices = data.get('devices', {})
        for dev_name, dev_conf in devices.items():
            if dev_conf.get('type') == 'disk' and dev_conf.get('path') == '/':
                raw_disk = dev_conf.get('size', '0')
                disk_mb = self.parse_size(raw_disk)
                break
        
        # Mise à jour dans NetBox
        defaults = {
            'status': nb_status,
            'vcpus': vcpus,
        }
        
        if memory_mb:
            defaults['memory'] = memory_mb
        if disk_mb:
            defaults['disk'] = disk_mb
            
        vm, created = VirtualMachine.objects.update_or_create(
            name=vm_name,
            cluster=cluster,
            defaults=defaults
        )
        
        action = "Créé" if created else "Mis à jour"
        self.logger.info(f"  {action}: {vm_name}")

    def parse_memory(self, value):
        """Convertit une valeur mémoire Incus en MB."""
        if not value:
            return None
        try:
            value = str(value).upper()
            if value.endswith('GB'):
                return int(float(value[:-2]) * 1024)
            elif value.endswith('MB'):
                return int(float(value[:-2]))
            elif value.endswith('KB'):
                return int(float(value[:-2]) / 1024)
            else:
                return int(value)
        except (ValueError, TypeError):
            return None

    def parse_size(self, value):
        """Convertit une taille Incus en MB."""
        return self.parse_memory(value)