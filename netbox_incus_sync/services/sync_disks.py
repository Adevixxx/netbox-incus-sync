"""
Incus virtual disk synchronization service to NetBox.
"""

from virtualization.models import VirtualDisk

from .sync_utils import parse_size


class DiskSyncService:
    """Service to synchronize Incus instance disks to NetBox VirtualDisks."""
    
    def __init__(self, logger=None):
        self.logger = logger
    
    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)
    
    def sync_instance_disks(self, vm, instance_data, client):
        """Synchronizes Incus instance disks to NetBox."""
        disks_synced = 0
        
        # Prefer expanded_devices (includes profile-inherited devices)
        devices = instance_data.get('expanded_devices') or instance_data.get('devices', {})
        
        disk_devices = {
            name: config 
            for name, config in devices.items() 
            if config.get('type') == 'disk'
        }
        
        if not disk_devices:
            self.log('debug', f"    No disk found for {vm.name}")
            return 0
        
        current_disk_names = set()
        
        for disk_name, disk_config in disk_devices.items():
            current_disk_names.add(disk_name)
            
            disk, created = self._sync_disk(vm, disk_name, disk_config, client)
            
            if disk:
                disks_synced += 1
                if created:
                    self.log('info', f"    Disk created: {disk_name} ({disk.size} MB)")
        
        self._cleanup_old_disks(vm, current_disk_names)
        
        return disks_synced
    
    def _sync_disk(self, vm, disk_name, disk_config, client):
        """Synchronizes an individual disk."""
        path = disk_config.get('path', '')
        pool = disk_config.get('pool', '')
        source = disk_config.get('source', '')
        size_raw = disk_config.get('size', '')
        
        size_mb = self._get_disk_size(
            size_raw=size_raw,
            pool=pool,
            source=source,
            disk_name=disk_name,
            vm_name=vm.name,
            client=client
        )
        
        disk_type = 'root' if disk_name == 'root' or path == '/' else 'data'
        description = f"Synced from Incus"
        
        defaults = {
            'size': size_mb or 0,
            'description': description,
        }
        
        disk, created = VirtualDisk.objects.update_or_create(
            virtual_machine=vm,
            name=disk_name,
            defaults=defaults
        )
        
        self._update_disk_custom_fields(disk, path, pool, source, disk_type)
        
        return disk, created
    
    def _update_disk_custom_fields(self, disk, path, pool, source, disk_type):
        updated = False
        
        if path and disk.custom_field_data.get('incus_mount_path') != path:
            disk.custom_field_data['incus_mount_path'] = path
            updated = True
        
        if pool and disk.custom_field_data.get('incus_storage_pool') != pool:
            disk.custom_field_data['incus_storage_pool'] = pool
            updated = True
        
        if source and disk.custom_field_data.get('incus_volume_source') != source:
            disk.custom_field_data['incus_volume_source'] = source
            updated = True
        elif not source and 'incus_volume_source' in disk.custom_field_data:
            del disk.custom_field_data['incus_volume_source']
            updated = True
        
        if disk_type and disk.custom_field_data.get('incus_disk_type') != disk_type:
            disk.custom_field_data['incus_disk_type'] = disk_type
            updated = True
        
        if updated:
            disk.save()
    
    def _get_disk_size(self, size_raw, pool, source, disk_name, vm_name, client):
        if size_raw:
            size_mb = parse_size(size_raw)
            if size_mb:
                return size_mb
        
        if source and pool:
            size_mb = self._get_volume_size(client, pool, source)
            if size_mb:
                return size_mb
        
        if disk_name == 'root' and pool:
            size_mb = self._get_instance_disk_usage(client, pool, vm_name)
            if size_mb:
                return size_mb
        
        return 0
    
    def _get_volume_size(self, client, pool, volume_name):
        try:
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
        try:
            volume_info = client.get_storage_volume(pool, 'container', instance_name)
            if not volume_info:
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
        old_disks = VirtualDisk.objects.filter(
            virtual_machine=vm
        ).exclude(name__in=current_disk_names)
        
        for old_disk in old_disks:
            self.log('info', f"    Disk deleted: {old_disk.name}")
            old_disk.delete()