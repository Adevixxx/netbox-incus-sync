"""
Service de synchronisation des instances Incus vers NetBox.
"""

from django.utils import timezone
from virtualization.models import VirtualMachine, Cluster, ClusterType
from extras.models import Tag

from .sync_utils import parse_memory, parse_size, ensure_tags_exist


class InstanceSyncService:
    """
    Service pour synchroniser les instances Incus vers NetBox VirtualMachine.
    """
    
    def __init__(self, logger=None):
        """
        Initialise le service.
        
        Args:
            logger: Logger pour les messages (optionnel)
        """
        self.logger = logger
        self.tags = {}
    
    def log(self, level, message):
        """Log un message si logger disponible."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    def setup(self):
        """Prépare le service (crée les tags, etc.)."""
        self.tags = ensure_tags_exist(self.logger)
    
    def resolve_cluster(self, host):
        """
        Assure qu'un Cluster existe pour accueillir les VMs.
        
        Args:
            host: Instance IncusHost
        
        Returns:
            Cluster: Le cluster à utiliser
        """
        if host.default_cluster:
            return host.default_cluster
        
        ctype, _ = ClusterType.objects.get_or_create(
            name='Incus', 
            defaults={'slug': 'incus'}
        )
        
        cluster, _ = Cluster.objects.get_or_create(
            name=f"Cluster {host.name}",
            defaults={'type': ctype}
        )
        return cluster
    
    def sync_instance(self, data, cluster, host):
        """
        Synchronise une instance Incus vers NetBox.
        
        Args:
            data: Données de l'instance Incus
            cluster: Cluster NetBox cible
            host: Instance IncusHost source
        
        Returns:
            tuple: (vm, created: bool, updated: bool)
        """
        vm_name = data.get('name')
        status_raw = data.get('status')
        instance_type = data.get('type', 'container')
        
        # Mapping du statut
        nb_status = 'active' if status_raw == 'Running' else 'offline'
        
        config = data.get('config', {})
        
        # Extraction des ressources
        vcpus = self._extract_cpu(config)
        memory_mb = parse_memory(config.get('limits.memory', ''))
        disk_mb = self._extract_disk(data.get('devices', {}))
        
        # Métadonnées
        architecture = data.get('architecture', 'unknown')
        created_at = data.get('created_at', '')
        image_info = config.get('image.description', config.get('image.os', 'Unknown'))
        
        # Construire le commentaire
        comments = self._build_comments(host, instance_type, architecture, image_info, created_at)
        
        # Defaults pour update_or_create
        defaults = {
            'status': nb_status,
            'vcpus': vcpus,
            'comments': comments,
        }
        
        if memory_mb:
            defaults['memory'] = memory_mb
        if disk_mb:
            defaults['disk'] = disk_mb
        
        # Vérifier si la VM existe déjà
        existing_vm = VirtualMachine.objects.filter(name=vm_name, cluster=cluster).first()
        created = existing_vm is None
        
        # Créer ou mettre à jour
        vm, _ = VirtualMachine.objects.update_or_create(
            name=vm_name,
            cluster=cluster,
            defaults=defaults
        )
        
        # Appliquer les tags
        self._apply_tags(vm, instance_type)
        
        # Log
        action = "Créé" if created else "Mis à jour"
        type_label = "container" if instance_type == 'container' else "VM"
        self.log('info', f"  {action}: {vm_name} ({type_label})")
        
        return vm, created, not created
    
    def handle_deletions(self, cluster, incus_instance_names):
        """
        Gère les VMs qui n'existent plus dans Incus.
        
        Args:
            cluster: Cluster NetBox
            incus_instance_names: Set des noms d'instances actuelles dans Incus
        
        Returns:
            int: Nombre de VMs marquées comme supprimées
        """
        deleted_count = 0
        
        try:
            managed_tag = Tag.objects.get(slug='incus-managed')
        except Tag.DoesNotExist:
            return 0
        
        managed_vms = VirtualMachine.objects.filter(
            cluster=cluster,
            tags=managed_tag
        )
        
        for vm in managed_vms:
            if vm.name not in incus_instance_names:
                self.log('warning', f"  Instance disparue d'Incus: {vm.name}")
                
                # Marquer comme offline et retirer le tag managed
                vm.status = 'offline'
                vm.comments = f"{vm.comments}\n\n⚠️ Removed from Incus on {timezone.now().isoformat()}"
                vm.tags.remove(managed_tag)
                vm.save()
                deleted_count += 1
                self.log('info', f"  Marqué comme supprimé: {vm.name}")
        
        return deleted_count
    
    def _extract_cpu(self, config):
        """Extrait le nombre de vCPUs depuis la config."""
        try:
            return float(config.get('limits.cpu', 1))
        except (ValueError, TypeError):
            return 1
    
    def _extract_disk(self, devices):
        """Extrait la taille du disque root depuis les devices."""
        for dev_name, dev_conf in devices.items():
            if dev_conf.get('type') == 'disk' and dev_conf.get('path') == '/':
                raw_disk = dev_conf.get('size', '0')
                return parse_size(raw_disk)
        return 0
    
    def _build_comments(self, host, instance_type, architecture, image_info, created_at):
        """Construit le champ comments de la VM."""
        return (
            f"Synchronized from Incus host: {host.name}\n"
            f"Type: {instance_type}\n"
            f"Architecture: {architecture}\n"
            f"Image: {image_info}\n"
            f"Created: {created_at}\n"
            f"Last sync: {timezone.now().isoformat()}"
        )
    
    def _apply_tags(self, vm, instance_type):
        """Applique les tags appropriés à la VM."""
        managed_tag = self.tags.get('incus-managed') or Tag.objects.get(slug='incus-managed')
        
        if instance_type == 'container':
            type_tag = self.tags.get('incus-container') or Tag.objects.get(slug='incus-container')
            other_tag_slug = 'incus-vm'
        else:
            type_tag = self.tags.get('incus-vm') or Tag.objects.get(slug='incus-vm')
            other_tag_slug = 'incus-container'
        
        vm.tags.add(managed_tag)
        vm.tags.add(type_tag)
        
        # Retirer l'autre tag de type si présent
        try:
            other_tag = Tag.objects.get(slug=other_tag_slug)
            vm.tags.remove(other_tag)
        except Tag.DoesNotExist:
            pass
        
        vm.save()