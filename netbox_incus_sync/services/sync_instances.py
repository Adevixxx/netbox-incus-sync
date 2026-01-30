"""
Service de synchronisation des instances Incus vers NetBox.

Utilise les objets natifs NetBox :
- ClusterType : Type "Incus" créé automatiquement
- Cluster : Un cluster par hôte Incus (si clustering Incus activé)
- VirtualMachine : Les instances Incus

Identification des instances :
- Utilise l'UUID Incus (volatile.uuid) comme identifiant unique
- Permet de gérer correctement les renommages d'instances
"""

from datetime import datetime
from django.utils import timezone
from virtualization.models import VirtualMachine, Cluster, ClusterType
from extras.models import Tag

from .sync_utils import parse_memory, parse_size, ensure_tags_exist


# Slug du ClusterType Incus
INCUS_CLUSTER_TYPE_SLUG = 'incus'


class InstanceSyncService:
    """
    Service pour synchroniser les instances Incus vers NetBox VirtualMachine.
    
    Gestion des clusters :
    - Si Incus n'est PAS en mode cluster : les VMs sont créées sans cluster
      (sauf si default_cluster est défini manuellement sur l'IncusHost)
    - Si Incus EST en mode cluster : un Cluster NetBox est créé automatiquement
      et toutes les VMs y sont assignées
    
    Identification des instances :
    - Utilise l'UUID Incus (config['volatile.uuid']) comme identifiant unique
    - Permet de suivre les instances même après un renommage
    """
    
    def __init__(self, logger=None):
        """
        Initialise le service.
        
        Args:
            logger: Logger pour les messages (optionnel)
        """
        self.logger = logger
        self.tags = {}
        self._cluster_type = None
    
    def log(self, level, message):
        """Log un message si logger disponible."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    def setup(self):
        """Prépare le service (crée les tags, etc.)."""
        self.tags = ensure_tags_exist(self.logger)
    
    @property
    def incus_cluster_type(self):
        """
        Retourne le ClusterType "Incus", le crée si nécessaire.
        
        Returns:
            ClusterType: Le type de cluster Incus
        """
        if self._cluster_type is None:
            self._cluster_type, created = ClusterType.objects.get_or_create(
                slug=INCUS_CLUSTER_TYPE_SLUG,
                defaults={
                    'name': 'Incus',
                    'description': 'Cluster Incus (conteneurs et VMs)',
                }
            )
            if created:
                self.log('info', f"  ClusterType 'Incus' créé")
        return self._cluster_type
    
    def resolve_cluster(self, host, cluster_info=None):
        """
        Détermine le cluster à utiliser pour les VMs d'un hôte.
        
        Logique :
        1. Si cluster_info indique qu'Incus est en mode cluster → créer/utiliser un Cluster NetBox
        2. Sinon, si default_cluster est défini sur l'hôte → l'utiliser
        3. Sinon → pas de cluster (None)
        
        Args:
            host: Instance IncusHost
            cluster_info: Dict avec infos cluster depuis Incus API (optionnel)
                         {'enabled': bool, 'server_name': str, 'member_count': int}
        
        Returns:
            Cluster ou None: Le cluster à utiliser
        """
        # Cas 1 : Incus est en mode cluster
        if cluster_info and cluster_info.get('enabled'):
            cluster_name = cluster_info.get('server_name') or f"incus-{host.name}"
            return self._get_or_create_cluster(cluster_name, host)
        
        # Cas 2 : Utiliser le cluster par défaut si défini
        if host.default_cluster:
            return host.default_cluster
        
        # Cas 3 : Pas de cluster
        return None
    
    def _get_or_create_cluster(self, cluster_name, host):
        """
        Récupère ou crée un Cluster NetBox pour un cluster Incus.
        
        Args:
            cluster_name: Nom du cluster
            host: IncusHost source
        
        Returns:
            Cluster: Le cluster NetBox
        """
        cluster, created = Cluster.objects.get_or_create(
            name=cluster_name,
            type=self.incus_cluster_type,
            defaults={
                'description': f"Cluster Incus synchronisé depuis {host.name}",
            }
        )
        
        if created:
            self.log('info', f"  Cluster NetBox créé: {cluster_name}")
        
        return cluster
    
    def sync_instance(self, data, cluster, host):
        """
        Synchronise une instance Incus vers NetBox.
        
        Utilise l'UUID Incus (volatile.uuid) comme identifiant unique pour :
        - Retrouver une VM existante même si elle a été renommée
        - Éviter les doublons
        
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
        config = data.get('config', {})
        
        # UUID unique de l'instance Incus
        incus_uuid = config.get('volatile.uuid', '')
        
        # Champ location pour le clustering - indique sur quel nœud tourne l'instance
        location = data.get('location', '')
        
        # Mapping du statut
        nb_status = 'active' if status_raw == 'Running' else 'offline'
        
        # Extraction des ressources
        vcpus = self._extract_cpu(config)
        memory_mb = parse_memory(config.get('limits.memory', ''))
        disk_mb = self._extract_disk(data.get('devices', {}))
        
        # Defaults pour update_or_create
        defaults = {
            'status': nb_status,
            'vcpus': vcpus,
            'cluster': cluster,  # Peut être None - c'est voulu !
        }
        
        if memory_mb:
            defaults['memory'] = memory_mb
        if disk_mb:
            defaults['disk'] = disk_mb
        
        # Rechercher la VM existante par UUID d'abord, puis par nom
        existing_vm = self._find_existing_vm(vm_name, incus_uuid, host)
        created = existing_vm is None
        renamed = False
        old_name = None
        
        if existing_vm:
            # Vérifier si l'instance a été renommée
            if existing_vm.name != vm_name:
                old_name = existing_vm.name
                renamed = True
                self.log('info', f"  Renommage détecté: {old_name} -> {vm_name}")
            
            # Mettre à jour la VM existante
            existing_vm.name = vm_name  # Mettre à jour le nom si renommé
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
        
        # Mettre à jour les Custom Fields (incluant l'UUID)
        self._update_vm_custom_fields(vm, data, host, location, incus_uuid)
        
        # Appliquer les tags
        self._apply_tags(vm, instance_type)
        
        # Log
        if renamed:
            action = f"Renommé ({old_name} ->)"
        elif created:
            action = "Créé"
        else:
            action = "Mis à jour"
        
        type_label = "container" if instance_type == 'container' else "VM"
        cluster_info = f" dans {cluster.name}" if cluster else " (sans cluster)"
        location_info = f" sur {location}" if location else ""
        self.log('info', f"  {action}: {vm_name} ({type_label}){cluster_info}{location_info}")
        
        return vm, created, not created
    
    def _find_existing_vm(self, vm_name, incus_uuid, host):
        """
        Recherche une VM existante, d'abord par UUID puis par nom.
        
        Stratégie de recherche (dans l'ordre) :
        1. Par UUID Incus (le plus fiable, survit aux renommages)
        2. Par nom + hôte Incus (fallback pour les anciennes VMs sans UUID)
        
        Args:
            vm_name: Nom actuel de la VM dans Incus
            incus_uuid: UUID de l'instance Incus (volatile.uuid)
            host: IncusHost source
        
        Returns:
            VirtualMachine ou None
        """
        # 1. Recherche par UUID (méthode privilégiée)
        if incus_uuid:
            vm = VirtualMachine.objects.filter(
                custom_field_data__incus_uuid=incus_uuid
            ).first()
            if vm:
                return vm
        
        # 2. Fallback: recherche par nom + hôte Incus
        # (pour les VMs créées avant l'ajout du tracking par UUID)
        vm = VirtualMachine.objects.filter(
            name=vm_name,
            custom_field_data__incus_host=host.name
        ).first()
        
        return vm
    
    def _update_vm_custom_fields(self, vm, data, host, location='', incus_uuid=''):
        """
        Met à jour les Custom Fields de la VM.
        
        Args:
            vm: Instance VirtualMachine NetBox
            data: Données de l'instance Incus
            host: Instance IncusHost source
            location: Nom du nœud de cluster (optionnel)
            incus_uuid: UUID unique de l'instance Incus
        """
        config = data.get('config', {})
        instance_type = data.get('type', 'container')
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
        
        # UUID Incus (identifiant unique pour le tracking)
        if incus_uuid and vm.custom_field_data.get('incus_uuid') != incus_uuid:
            vm.custom_field_data['incus_uuid'] = incus_uuid
            updated = True
        
        # Hôte Incus source
        if vm.custom_field_data.get('incus_host') != host.name:
            vm.custom_field_data['incus_host'] = host.name
            updated = True
        
        # Instance Type
        if vm.custom_field_data.get('incus_type') != instance_type:
            vm.custom_field_data['incus_type'] = instance_type
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
        elif 'incus_profiles' in vm.custom_field_data:
            del vm.custom_field_data['incus_profiles']
            updated = True
        
        # Cluster Node Location (pour les instances en cluster Incus)
        if location:
            if vm.custom_field_data.get('incus_location') != location:
                vm.custom_field_data['incus_location'] = location
                updated = True
        elif 'incus_location' in vm.custom_field_data:
            # Retirer si plus de location (instance déplacée hors cluster)
            del vm.custom_field_data['incus_location']
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
                base, frac = dt_string.split('.')
                frac_clean = frac.rstrip('Z')[:6]
                dt_string = f"{base}.{frac_clean}Z"
            
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            self.log('debug', f"    Impossible de parser la date: {dt_string} - {e}")
            return None
    
    def handle_deletions(self, cluster, host, incus_instance_uuids):
        """
        Supprime les VMs qui n'existent plus dans Incus.
        
        Utilise les UUIDs pour identifier les VMs à supprimer.
        
        Args:
            cluster: Cluster NetBox (peut être None)
            host: IncusHost source
            incus_instance_uuids: Set des UUIDs d'instances actuelles dans Incus
        
        Returns:
            int: Nombre de VMs supprimées
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
        
        for vm in managed_vms:
            vm_uuid = vm.custom_field_data.get('incus_uuid', '')
            
            # Si la VM a un UUID et qu'il n'est plus dans Incus
            if vm_uuid and vm_uuid not in incus_instance_uuids:
                vm_name = vm.name
                self.log('warning', f"  Instance disparue d'Incus: {vm_name} (UUID: {vm_uuid[:8]}...)")
                
                # Supprimer la VM de NetBox
                vm.delete()
                deleted_count += 1
                self.log('info', f"  Supprimé de NetBox: {vm_name}")
            
            # Fallback pour les VMs sans UUID (anciennes)
            elif not vm_uuid:
                self.log('debug', f"  VM sans UUID ignorée pour la suppression: {vm.name}")
        
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