"""
Service de synchronisation des disques virtuels Incus vers NetBox.
"""

from virtualization.models import VirtualDisk

from .sync_utils import parse_size


class DiskSyncService:
    """
    Service pour synchroniser les disques des instances Incus vers NetBox VirtualDisk.
    """
    
    def __init__(self, logger=None):
        """
        Initialise le service.
        
        Args:
            logger: Logger pour les messages (optionnel)
        """
        self.logger = logger
    
    def log(self, level, message):
        """Log un message si logger disponible."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    def sync_instance_disks(self, vm, instance_data, client):
        """
        Synchronise les disques d'une instance Incus vers NetBox.
        
        Args:
            vm: Instance VirtualMachine NetBox
            instance_data: Données de l'instance Incus
            client: Client Incus pour requêtes supplémentaires
        
        Returns:
            int: Nombre de disques synchronisés
        """
        disks_synced = 0
        
        # Récupérer les devices (expanded pour avoir ceux hérités du profil)
        devices = instance_data.get('expanded_devices', {})
        
        if not devices:
            # Fallback sur devices directs
            devices = instance_data.get('devices', {})
        
        # Filtrer pour ne garder que les disques
        disk_devices = {
            name: config 
            for name, config in devices.items() 
            if config.get('type') == 'disk'
        }
        
        if not disk_devices:
            self.log('info', f"    Aucun disque trouvé pour {vm.name}")
            return 0
        
        # Tracker les noms de disques actuels pour le nettoyage
        current_disk_names = set()
        
        for disk_name, disk_config in disk_devices.items():
            current_disk_names.add(disk_name)
            
            # Synchroniser le disque
            disk, created = self._sync_disk(vm, disk_name, disk_config, client)
            
            if disk:
                disks_synced += 1
                if created:
                    self.log('info', f"    Disque créé: {disk_name} ({disk.size} MB)")
                else:
                    self.log('info', f"    Disque mis à jour: {disk_name} ({disk.size} MB)")
        
        # Nettoyer les disques obsolètes
        self._cleanup_old_disks(vm, current_disk_names)
        
        return disks_synced
    
    def _sync_disk(self, vm, disk_name, disk_config, client):
        """
        Synchronise un disque individuel.
        
        Args:
            vm: Instance VirtualMachine NetBox
            disk_name: Nom du disque (ex: 'root', 'data')
            disk_config: Configuration du disque depuis Incus
            client: Client Incus
        
        Returns:
            tuple: (VirtualDisk, created)
        """
        path = disk_config.get('path', '')
        pool = disk_config.get('pool', '')
        source = disk_config.get('source', '')  # Pour les volumes additionnels
        size_raw = disk_config.get('size', '')
        
        # Calculer la taille
        size_mb = self._get_disk_size(
            size_raw=size_raw,
            pool=pool,
            source=source,
            disk_name=disk_name,
            vm_name=vm.name,
            client=client
        )
        
        # Construire la description
        description = self._build_description(disk_name, path, pool, source)
        
        # Créer ou mettre à jour le disque
        defaults = {
            'size': size_mb or 0,
            'description': description,
        }
        
        disk, created = VirtualDisk.objects.update_or_create(
            virtual_machine=vm,
            name=disk_name,
            defaults=defaults
        )
        
        return disk, created
    
    def _get_disk_size(self, size_raw, pool, source, disk_name, vm_name, client):
        """
        Détermine la taille d'un disque.
        
        Ordre de priorité :
        1. Taille définie directement sur le device (size_raw)
        2. Pour les volumes : taille du volume dans le pool
        3. Pour root sans taille : taille utilisée par l'instance
        
        Returns:
            int: Taille en MB ou 0 si inconnue
        """
        # 1. Taille définie directement
        if size_raw:
            size_mb = parse_size(size_raw)
            if size_mb:
                return size_mb
        
        # 2. Pour les volumes additionnels, chercher dans le pool
        if source and pool:
            size_mb = self._get_volume_size(client, pool, source)
            if size_mb:
                return size_mb
        
        # 3. Pour le disque root, essayer de récupérer l'usage
        if disk_name == 'root' and pool:
            size_mb = self._get_instance_disk_usage(client, pool, vm_name)
            if size_mb:
                return size_mb
        
        return 0
    
    def _get_volume_size(self, client, pool, volume_name):
        """
        Récupère la taille d'un volume de stockage.
        
        Args:
            client: Client Incus
            pool: Nom du pool de stockage
            volume_name: Nom du volume
        
        Returns:
            int: Taille en MB ou None
        """
        try:
            # Essayer d'abord comme volume custom
            volume_info = client.get_storage_volume(pool, 'custom', volume_name)
            if volume_info:
                config = volume_info.get('config', {})
                size_raw = config.get('size', '')
                if size_raw:
                    return parse_size(size_raw)
        except Exception as e:
            self.log('debug', f"    Volume {volume_name} non trouvé dans {pool}: {e}")
        
        return None
    
    def _get_instance_disk_usage(self, client, pool, instance_name):
        """
        Récupère l'utilisation disque d'une instance.
        
        Args:
            client: Client Incus
            pool: Nom du pool de stockage
            instance_name: Nom de l'instance
        
        Returns:
            int: Taille en MB ou None
        """
        try:
            # Récupérer les infos du volume de l'instance
            volume_info = client.get_storage_volume(pool, 'container', instance_name)
            if not volume_info:
                # Essayer avec 'virtual-machine' pour les VMs
                volume_info = client.get_storage_volume(pool, 'virtual-machine', instance_name)
            
            if volume_info:
                config = volume_info.get('config', {})
                size_raw = config.get('size', '')
                if size_raw:
                    return parse_size(size_raw)
        except Exception as e:
            self.log('debug', f"    Usage disque non disponible pour {instance_name}: {e}")
        
        return None
    
    def _build_description(self, disk_name, path, pool, source):
        """
        Construit la description du disque.
        
        Returns:
            str: Description formatée
        """
        parts = [f"Synced from Incus"]
        
        if path:
            parts.append(f"Mount: {path}")
        
        if pool:
            parts.append(f"Pool: {pool}")
        
        if source:
            parts.append(f"Source: {source}")
        
        if disk_name == 'root':
            parts.append("(System disk)")
        
        return " | ".join(parts)
    
    def _cleanup_old_disks(self, vm, current_disk_names):
        """
        Supprime les disques qui n'existent plus dans Incus.
        
        Args:
            vm: Instance VirtualMachine
            current_disk_names: Set des noms de disques actuels
        """
        old_disks = VirtualDisk.objects.filter(
            virtual_machine=vm
        ).exclude(name__in=current_disk_names)
        
        for old_disk in old_disks:
            self.log('info', f"    Disque supprimé: {old_disk.name}")
            old_disk.delete()