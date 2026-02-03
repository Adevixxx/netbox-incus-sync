"""
Incus virtual disk synchronization service to NetBox.
"""

from virtualization.models import VirtualDisk

from .sync_utils import parse_size


class DiskSyncService:
    """
    Service to synchronize Incus instance disks to NetBox VirtualDisks.
    """
    
    def __init__(self, logger=None):
        """
        Initializes the service.
        
        Args:
            logger: Logger for messages (optional)
        """
        self.logger = logger
    
    def log(self, level, message):
        """Log a message if logger is available."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    def sync_instance_disks(self, vm, instance_data, client):
        """
        Synchronizes Incus instance disks to NetBox.
        
        Args:
            vm: NetBox VirtualMachine instance
            instance_data: Incus instance data
            client: Incus Client for additional requests
        
        Returns:
            int: Number of synchronized disks
        """
        disks_synced = 0
        
        # Get devices (expanded to include those inherited from profile)
        devices = instance_data.get('expanded_devices', {})
        
        if not devices:
            # Fallback to direct devices
            devices = instance_data.get('devices', {})
        
        # Filter to keep only disks
        disk_devices = {
            name: config 
            for name, config in devices.items() 
            if config.get('type') == 'disk'
        }
        
        if not disk_devices:
            self.log('info', f"    No disk found for {vm.name}")
            return 0
        
        # Track current disk names for cleanup
        current_disk_names = set()
        
        for disk_name, disk_config in disk_devices.items():
            current_disk_names.add(disk_name)
            
            # Sync disk
            disk, created = self._sync_disk(vm, disk_name, disk_config, client)
            
            if disk:
                disks_synced += 1
                if created:
                    self.log('info', f"    Disk created: {disk_name} ({disk.size} MB)")
                else:
                    self.log('info', f"    Disk updated: {disk_name} ({disk.size} MB)")
        
        # Cleanup obsolete disks
        self._cleanup_old_disks(vm, current_disk_names)
        
        return disks_synced
    
    def _sync_disk(self, vm, disk_name, disk_config, client):
        """
        Synchronizes an individual disk.
        
        Args:
            vm: NetBox VirtualMachine instance
            disk_name: Disk name (e.g., 'root', 'data')
            disk_config: Disk configuration from Incus
            client: Incus Client
        
        Returns:
            tuple: (VirtualDisk, created)
        """
        path = disk_config.get('path', '')
        pool = disk_config.get('pool', '')
        source = disk_config.get('source', '')  # For additional volumes
        size_raw = disk_config.get('size', '')
        
        # Calculate size
        size_mb = self._get_disk_size(
            size_raw=size_raw,
            pool=pool,
            source=source,
            disk_name=disk_name,
            vm_name=vm.name,
            client=client
        )
        
        # Determine disk type
        disk_type = 'root' if disk_name == 'root' or path == '/' else 'data'
        
        # Simplified description (details are in custom fields)
        description = f"Synced from Incus"
        
        # Create or update disk
        defaults = {
            'size': size_mb or 0,
            'description': description,
        }
        
        disk, created = VirtualDisk.objects.update_or_create(
            virtual_machine=vm,
            name=disk_name,
            defaults=defaults
        )
        
        # Update Custom Fields
        self._update_disk_custom_fields(disk, path, pool, source, disk_type)
        
        return disk, created
    
    def _update_disk_custom_fields(self, disk, path, pool, source, disk_type):
        """
        Updates Disk Custom Fields.
        
        Args:
            disk: NetBox VirtualDisk
            path: Mount point
            pool: Storage pool name
            source: Source volume name (for additional volumes)
            disk_type: Disk type (root, data)
        """
        updated = False
        
        # Mount Path
        if path and disk.custom_field_data.get('incus_mount_path') != path:
            disk.custom_field_data['incus_mount_path'] = path
            updated = True
        
        # Storage Pool
        if pool and disk.custom_field_data.get('incus_storage_pool') != pool:
            disk.custom_field_data['incus_storage_pool'] = pool
            updated = True
        
        # Volume Source (only if defined)
        if source and disk.custom_field_data.get('incus_volume_source') != source:
            disk.custom_field_data['incus_volume_source'] = source
            updated = True
        elif not source and 'incus_volume_source' in disk.custom_field_data:
            # Remove field if no source
            del disk.custom_field_data['incus_volume_source']
            updated = True
        
        # Disk Type
        if disk_type and disk.custom_field_data.get('incus_disk_type') != disk_type:
            disk.custom_field_data['incus_disk_type'] = disk_type
            updated = True
        
        if updated:
            disk.save()
    
    def _get_disk_size(self, size_raw, pool, source, disk_name, vm_name, client):
        """
        Determines disk size.
        
        Priority order:
        1. Size defined directly on device (size_raw)
        2. For volumes: volume size in pool
        3. For root without size: size used by instance
        
        Returns:
            int: Size in MB or 0 if unknown
        """
        # 1. Size defined directly
        if size_raw:
            size_mb = parse_size(size_raw)
            if size_mb:
                return size_mb
        
        # 2. For additional volumes, check in pool
        if source and pool:
            size_mb = self._get_volume_size(client, pool, source)
            if size_mb:
                return size_mb
        
        # 3. For root disk, try to get usage
        if disk_name == 'root' and pool:
            size_mb = self._get_instance_disk_usage(client, pool, vm_name)
            if size_mb:
                return size_mb
        
        return 0
    
    def _get_volume_size(self, client, pool, volume_name):
        """
        Retrieves storage volume size.
        
        Args:
            client: Incus Client
            pool: Storage pool name
            volume_name: Volume name
        
        Returns:
            int: Size in MB or None
        """
        try:
            # First try as custom volume
            volume_info = client.get_storage_volume(pool, 'custom', volume_name)
            if volume_info:
                config = volume_info.get('config', {})
                size_raw = config.get('size', '')
                if size_raw:
                    return parse_size(size_raw)
        except Exception as e:
            self.log('debug', f"    Volume {volume_name} not found in {pool}: {e}")
        
        return None
    
    def _get_instance_disk_usage(self, client, pool, instance_name):
        """
        Retrieves instance disk usage.
        
        Args:
            client: Incus Client
            pool: Storage pool name
            instance_name: Instance name
        
        Returns:
            int: Size in MB or None
        """
        try:
            # Get instance volume info
            volume_info = client.get_storage_volume(pool, 'container', instance_name)
            if not volume_info:
                # Try with 'virtual-machine' for VMs
                volume_info = client.get_storage_volume(pool, 'virtual-machine', instance_name)
            
            if volume_info:
                config = volume_info.get('config', {})
                size_raw = config.get('size', '')
                if size_raw:
                    return parse_size(size_raw)
        except Exception as e:
            self.log('debug', f"    Disk usage not available for {instance_name}: {e}")
        
        return None
    
    def _cleanup_old_disks(self, vm, current_disk_names):
        """
        Deletes disks that no longer exist in Incus.
        
        Args:
            vm: VirtualMachine instance
            current_disk_names: Set of current disk names
        """
        old_disks = VirtualDisk.objects.filter(
            virtual_machine=vm
        ).exclude(name__in=current_disk_names)
        
        for old_disk in old_disks:
            self.log('info', f"    Disk deleted: {old_disk.name}")
            old_disk.delete()