"""
Incus virtual disk synchronization service to NetBox.

Enhanced version with disk usage statistics.
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
    
    def sync_instance_disks(self, vm, instance_data, client, instance_type=None):
        """
        Synchronizes Incus instance disks to NetBox.
        
        Args:
            vm: NetBox VirtualMachine instance
            instance_data: Incus instance data dict
            client: IncusClient instance
            instance_type: Optional instance type override ('container' or 'virtual-machine')
        
        Returns:
            int: Number of disks synchronized
        """
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
        
        # Use provided instance_type or get from instance_data
        if instance_type is None:
            instance_type = instance_data.get('type', 'container')
        
        for disk_name, disk_config in disk_devices.items():
            current_disk_names.add(disk_name)
            
            disk, created = self._sync_disk(
                vm, disk_name, disk_config, client, instance_type
            )
            
            if disk:
                disks_synced += 1
                if created:
                    usage_info = ""
                    if disk.custom_field_data.get('incus_disk_used'):
                        used = disk.custom_field_data.get('incus_disk_used', 0)
                        usage_info = f", used: {used} MB"
                    self.log('debug', f"    Disk created: {disk_name} ({disk.size} MB{usage_info})")
        
        self._cleanup_old_disks(vm, current_disk_names)
        
        return disks_synced
    
    def _sync_disk(self, vm, disk_name, disk_config, client, instance_type='container'):
        """Synchronizes an individual disk."""
        path = disk_config.get('path', '')
        pool = disk_config.get('pool', '')
        source = disk_config.get('source', '')
        size_raw = disk_config.get('size', '')
        
        # Get disk size (allocated/configured size)
        size_mb = self._get_disk_size(
            size_raw=size_raw,
            pool=pool,
            source=source,
            disk_name=disk_name,
            vm_name=vm.name,
            client=client,
            instance_type=instance_type
        )
        
        # Get disk usage statistics (actual used space)
        usage_stats = self._get_disk_usage_stats(
            pool=pool,
            source=source,
            disk_name=disk_name,
            vm_name=vm.name,
            client=client,
            instance_type=instance_type
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
        
        self._update_disk_custom_fields(
            disk, path, pool, source, disk_type, usage_stats
        )
        
        return disk, created
    
    def _update_disk_custom_fields(self, disk, path, pool, source, disk_type, usage_stats=None):
        """Updates disk Custom Fields including usage statistics."""
        updated = False
        
        cf_updates = {
            'incus_disk_path': path,
            'incus_disk_pool': pool,
            'incus_disk_source': source,
            'incus_disk_type': disk_type,
        }
        
        # Add usage statistics if available
        if usage_stats:
            if 'used' in usage_stats:
                cf_updates['incus_disk_used'] = usage_stats['used']
            if 'total' in usage_stats:
                cf_updates['incus_disk_total'] = usage_stats['total']
            if 'percentage' in usage_stats and usage_stats['percentage'] is not None:
                cf_updates['incus_disk_percentage'] = usage_stats['percentage']
            if 'driver' in usage_stats:
                cf_updates['incus_disk_driver'] = usage_stats['driver']
            if 'content_type' in usage_stats:
                cf_updates['incus_disk_content_type'] = usage_stats['content_type']
        
        for key, value in cf_updates.items():
            if value and disk.custom_field_data.get(key) != value:
                disk.custom_field_data[key] = value
                updated = True
        
        if updated:
            disk.save()
    
    def _get_disk_size(self, size_raw, pool, source, disk_name, vm_name, client, instance_type):
        """Gets disk size from multiple sources."""
        if size_raw:
            size_mb = parse_size(size_raw)
            if size_mb:
                return size_mb
        
        if source and pool:
            size_mb = self._get_volume_size(client, pool, source)
            if size_mb:
                return size_mb
        
        if disk_name == 'root' and pool:
            size_mb = self._get_instance_disk_usage(client, pool, vm_name, instance_type)
            if size_mb:
                return size_mb
        
        return 0
    
    def _get_disk_usage_stats(self, pool, source, disk_name, vm_name, client, instance_type='container'):
        """
        Gets detailed disk usage statistics from Incus.
        
        Returns a dict with:
        - used: Used space in MB
        - total: Total space in MB
        - percentage: Usage percentage (0-100)
        - driver: Storage driver type
        - content_type: filesystem or block
        """
        stats = {}
        
        if not pool:
            return stats
        
        # Get pool info for driver type
        try:
            pool_info = client.get_storage_pool_info(pool)
            if pool_info:
                stats['driver'] = pool_info.get('driver', '')
        except Exception as e:
            self.log('debug', f"    Unable to get pool info for {pool}: {e}")
        
        # Determine volume type and name for the API call
        if source:
            # Custom volume
            volume_type = 'custom'
            volume_name = source
        elif disk_name == 'root':
            # Instance root volume
            volume_type = 'virtual-machine' if instance_type == 'virtual-machine' else 'container'
            volume_name = vm_name
        else:
            return stats
        
        # Get volume state (usage info)
        try:
            volume_state = client.get_storage_volume_state(pool, volume_type, volume_name)
            
            if volume_state:
                usage = volume_state.get('usage', {})
                
                # Used space (in bytes from API, convert to MB)
                used_bytes = usage.get('used', 0)
                if used_bytes:
                    stats['used'] = int(used_bytes / (1024 * 1024))
                
                # Total space (in bytes from API, convert to MB)
                total_bytes = usage.get('total', 0)
                if total_bytes:
                    stats['total'] = int(total_bytes / (1024 * 1024))
                
                # Calculate percentage
                if used_bytes and total_bytes and total_bytes > 0:
                    stats['percentage'] = round((used_bytes / total_bytes) * 100, 1)
                elif used_bytes and not total_bytes:
                    # Some drivers don't report total, only used
                    stats['percentage'] = None
                
                self.log('debug', f"    Volume {volume_name} usage: {stats.get('used', 0)} MB / {stats.get('total', 'N/A')} MB")
                
        except Exception as e:
            self.log('debug', f"    Unable to get volume state for {volume_type}/{volume_name}: {e}")
        
        # Get volume config for content_type
        try:
            volume_info = client.get_storage_volume(pool, volume_type, volume_name)
            if volume_info:
                stats['content_type'] = volume_info.get('content_type', 'filesystem')
        except Exception as e:
            self.log('debug', f"    Unable to get volume info for {volume_type}/{volume_name}: {e}")
        
        return stats
    
    def _get_volume_size(self, client, pool, volume_name):
        """Gets the configured size of a custom volume."""
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
    
    def _get_instance_disk_usage(self, client, pool, instance_name, instance_type='container'):
        """Gets the configured size of an instance's root volume."""
        try:
            volume_type = 'virtual-machine' if instance_type == 'virtual-machine' else 'container'
            volume_info = client.get_storage_volume(pool, volume_type, instance_name)
            
            if volume_info:
                config = volume_info.get('config', {})
                size_raw = config.get('size', '')
                if size_raw:
                    return parse_size(size_raw)
        except Exception as e:
            self.log('debug', f"    Disk usage not available for {instance_name}: {e}")
        
        return None
    
    def _cleanup_old_disks(self, vm, current_disk_names):
        """Removes disks that no longer exist in Incus."""
        old_disks = VirtualDisk.objects.filter(
            virtual_machine=vm
        ).exclude(name__in=current_disk_names)
        
        for old_disk in old_disks:
            self.log('info', f"    Disk deleted: {old_disk.name}")
            old_disk.delete()