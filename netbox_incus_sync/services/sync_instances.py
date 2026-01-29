"""
Service de synchronisation des instances Incus vers NetBox.
"""

from datetime import datetime
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
        Retourne le cluster associé à l'hôte, ou None si non défini.
        
        Args:
            host: Instance IncusHost
        
        Returns:
            Cluster ou None: Le cluster à utiliser (peut être None)
        """
        return host.default_cluster
    
    def sync_instance(self, data, cluster, host):
        """
        Synchronise une instance Incus vers NetBox.
        
        Args:
            data: Données de l'instance Incus
            cluster: Cluster NetBox cible (peut être None)
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
        
        # Defaults pour update_or_create
        defaults = {
            'status': nb_status,
            'vcpus': vcpus,
            'cluster': cluster,  # Peut être None
        }
        
        if memory_mb:
            defaults['memory'] = memory_mb
        if disk_mb:
            defaults['disk'] = disk_mb
        
        # Rechercher la VM existante
        # On cherche par nom + soit même cluster, soit même hôte Incus (via custom field)
        existing_vm = self._find_existing_vm(vm_name, cluster, host)
        created = existing_vm is None
        
        if existing_vm:
            # Mettre à jour la VM existante
            for key, value in defaults.items():
                setattr(existing_vm, key, value)
            existing_vm.save()
            vm = existing_vm
        else:
            # Créer une nouvelle VM
            vm = VirtualMachine.objects.create(
                name=vm_name,
                **defaults
            )
        
        # Mettre à jour les Custom Fields
        self._update_vm_custom_fields(vm, data, host)
        
        # Appliquer les tags
        self._apply_tags(vm, instance_type)
        
        # Log
        action = "Créé" if created else "Mis à jour"
        type_label = "container" if instance_type == 'container' else "VM"
        cluster_info = f" dans {cluster.name}" if cluster else " (sans cluster)"
        self.log('info', f"  {action}: {vm_name} ({type_label}){cluster_info}")
        
        return vm, created, not created
    
    def _find_existing_vm(self, vm_name, cluster, host):
        """
        Recherche une VM existante par son nom.
        
        Stratégie de recherche :
        1. Si cluster défini : chercher par nom + cluster
        2. Sinon : chercher par nom + custom field incus_host
        3. Fallback : chercher par nom seul si une seule VM existe avec ce nom
        
        Args:
            vm_name: Nom de la VM
            cluster: Cluster cible (peut être None)
            host: IncusHost source
        
        Returns:
            VirtualMachine ou None
        """
        # 1. Recherche par nom + cluster (si cluster défini)
        if cluster:
            vm = VirtualMachine.objects.filter(name=vm_name, cluster=cluster).first()
            if vm:
                return vm
        
        # 2. Recherche par nom + incus_host custom field
        vms_by_host = VirtualMachine.objects.filter(
            name=vm_name,
            custom_field_data__incus_host=host.name
        )
        if vms_by_host.count() == 1:
            return vms_by_host.first()
        
        # 3. Recherche par nom seul (sans cluster) - seulement si pas de cluster défini
        if not cluster:
            vms_no_cluster = VirtualMachine.objects.filter(name=vm_name, cluster__isnull=True)
            if vms_no_cluster.count() == 1:
                return vms_no_cluster.first()
        
        return None
    
    def _update_vm_custom_fields(self, vm, data, host):
        """
        Met à jour les Custom Fields de la VM.
        
        Args:
            vm: Instance VirtualMachine NetBox
            data: Données de l'instance Incus
            host: Instance IncusHost source
        """
        config = data.get('config', {})
        instance_type = data.get('type', 'container')
        architecture = data.get('architecture', '')
        created_at = data.get('created_at', '')
        profiles = data.get('profiles', [])
        
        # Image: essayer plusieurs clés possibles
        image_info = (
            config.get('image.description') or 
            config.get('image.os', '') + ' ' + config.get('image.release', '') or
            config.get('volatile.base_image', '') or
            'Unknown'
        ).strip()
        
        updated = False
        
        # Incus Host
        if vm.custom_field_data.get('incus_host') != host.name:
            vm.custom_field_data['incus_host'] = host.name
            updated = True
        
        # Instance Type
        if vm.custom_field_data.get('incus_type') != instance_type:
            vm.custom_field_data['incus_type'] = instance_type
            updated = True
        
        # Architecture
        if architecture and vm.custom_field_data.get('incus_architecture') != architecture:
            vm.custom_field_data['incus_architecture'] = architecture
            updated = True
        
        # Image
        if image_info and image_info != 'Unknown':
            if vm.custom_field_data.get('incus_image') != image_info:
                vm.custom_field_data['incus_image'] = image_info
                updated = True
        
        # Created in Incus (convertir ISO en datetime)
        if created_at:
            created_datetime = self._parse_incus_datetime(created_at)
            if created_datetime:
                # Stocker en format ISO pour les custom fields datetime
                created_iso = created_datetime.isoformat()
                if vm.custom_field_data.get('incus_created') != created_iso:
                    vm.custom_field_data['incus_created'] = created_iso
                    updated = True
        
        # Last Sync (toujours mettre à jour)
        now_iso = timezone.now().isoformat()
        vm.custom_field_data['incus_last_sync'] = now_iso
        updated = True
        
        # Profiles (liste -> string séparé par virgules)
        if profiles:
            profiles_str = ', '.join(profiles)
            if vm.custom_field_data.get('incus_profiles') != profiles_str:
                vm.custom_field_data['incus_profiles'] = profiles_str
                updated = True
        
        if updated:
            vm.save()
    
    def _parse_incus_datetime(self, dt_string):
        """
        Parse une date/heure Incus (format ISO avec nanosecondes).
        
        Args:
            dt_string: String datetime au format Incus
        
        Returns:
            datetime ou None
        """
        if not dt_string:
            return None
        
        try:
            # Format Incus: 2026-01-27T13:58:42.690298037Z
            # Python ne gère pas les nanosecondes, on tronque aux microsecondes
            if '.' in dt_string:
                # Séparer la partie date et la partie fractionnaire
                base, frac = dt_string.split('.')
                # Garder seulement 6 chiffres pour les microsecondes
                frac_clean = frac.rstrip('Z')[:6]
                dt_string = f"{base}.{frac_clean}Z"
            
            # Parser avec le format ISO
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            self.log('debug', f"    Impossible de parser la date: {dt_string} - {e}")
            return None
    
    def handle_deletions(self, cluster, host, incus_instance_names):
        """
        Gère les VMs qui n'existent plus dans Incus.
        
        Args:
            cluster: Cluster NetBox (peut être None)
            host: IncusHost source
            incus_instance_names: Set des noms d'instances actuelles dans Incus
        
        Returns:
            int: Nombre de VMs marquées comme supprimées
        """
        deleted_count = 0
        
        try:
            managed_tag = Tag.objects.get(slug='incus-managed')
        except Tag.DoesNotExist:
            return 0
        
        # Filtrer les VMs gérées par cet hôte Incus
        managed_vms = VirtualMachine.objects.filter(
            tags=managed_tag,
            custom_field_data__incus_host=host.name
        )
        
        # Si un cluster est défini, filtrer aussi par cluster
        if cluster:
            managed_vms = managed_vms.filter(cluster=cluster)
        
        for vm in managed_vms:
            if vm.name not in incus_instance_names:
                self.log('warning', f"  Instance disparue d'Incus: {vm.name}")
                
                # Marquer comme offline et retirer le tag managed
                vm.status = 'offline'
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