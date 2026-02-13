"""
Incus configuration synchronization service to NetBox local_context_data.

UPDATED: Now works in tandem with ProfileSyncService.

- ProfileSyncService handles profile data → NetBox ConfigContext objects (tag-based)
- ConfigContextSyncService handles instance-specific data → VM local_context_data

This means local_context_data now only contains:
- Instance metadata (name, type, status, location, etc.)
- Source host information
- Instance-specific config overrides (NOT from profiles)
- Instance-specific device overrides (NOT from profiles)
- The list of applied profiles (for reference)

The expanded_config/expanded_devices are NO LONGER stored here,
as they are reconstructed by NetBox's Config Context merging system.
"""


class ConfigContextSyncService:
    """Service to synchronize Incus instance-specific config to VM local_context_data."""
    
    def __init__(self, logger=None):
        self.logger = logger
    
    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)
    
    def sync_instance_config_context(self, vm, instance_data, host):
        """
        Synchronizes an Incus instance's LOCAL configuration to the VM's local_context_data.
        
        Only stores instance-specific overrides and metadata.
        Profile-inherited data is handled by ProfileSyncService via ConfigContext objects.
        
        Args:
            vm: VirtualMachine instance
            instance_data: Raw Incus instance data
            host: IncusHost instance
            
        Returns:
            tuple: (updated: bool, created: bool)
        """
        # Build the context data structure (instance-specific only)
        context_data = self._build_context_data(instance_data, host)
        
        # Check if data changed
        old_data = vm.local_context_data or {}
        old_incus = old_data.get('incus', {})
        new_incus = context_data.get('incus', {})
        
        # Determine if this is a create or update
        created = 'incus' not in old_data
        
        # Compare relevant fields (skip volatile ones)
        def normalize_for_compare(data):
            """Remove volatile fields for comparison."""
            if not data:
                return {}
            copy = dict(data)
            instance = copy.get('instance', {})
            if isinstance(instance, dict):
                instance.pop('last_used_at', None)
                instance.pop('status', None)
                instance.pop('status_code', None)
            return copy
        
        old_normalized = normalize_for_compare(old_incus)
        new_normalized = normalize_for_compare(new_incus)
        
        # Update if different or new
        if created or old_normalized != new_normalized:
            # Merge with existing local_context_data (preserve other keys)
            new_local_context = dict(old_data)
            new_local_context['incus'] = context_data['incus']
            
            vm.local_context_data = new_local_context
            vm.save(update_fields=['local_context_data'])
            
            if created:
                self.log('info', f"    Local context created for {vm.name}")
            else:
                self.log('debug', f"    Local context updated for {vm.name}")
            
            return True, created
        
        return False, False
    
    def _build_context_data(self, instance_data, host):
        """
        Builds the context data structure from Incus instance data.
        
        Args:
            instance_data: Raw Incus instance data
            host: IncusHost instance
            
        Returns:
            dict: Structured configuration data
        """
        # Instance-specific config and devices (NOT expanded)
        config = instance_data.get('config', {})
        devices = instance_data.get('devices', {})
        profiles = instance_data.get('profiles', [])
        
        # Build structured data
        context_data = {
            'incus': {
                # Instance metadata
                'instance': {
                    'name': instance_data.get('name', ''),
                    'type': instance_data.get('type', 'container'),
                    'status': instance_data.get('status', ''),
                    'status_code': instance_data.get('status_code', 0),
                    'location': instance_data.get('location', ''),
                    'architecture': instance_data.get('architecture', ''),
                    'created_at': instance_data.get('created_at', ''),
                    'last_used_at': instance_data.get('last_used_at', ''),
                    'stateful': instance_data.get('stateful', False),
                },
                
                # Source host information
                'source': {
                    'host': host.name,
                    'connection_type': host.connection_type,
                },
                
                # Applied profiles (order matters! — for reference)
                'profiles': profiles,
                
                # Instance-specific overrides only (NOT from profiles)
                'instance_config': self._sanitize_config(config),
                'instance_devices': self._sanitize_devices(devices),
                
                # Extracted summaries from instance-specific overrides
                'instance_limits': self._extract_limits(config),
                'instance_security': self._extract_security(config),
            }
        }
        
        # Remove None values for cleaner output
        context_data['incus'] = {k: v for k, v in context_data['incus'].items() if v is not None}
        
        return context_data
    
    def _extract_limits(self, config):
        """Extracts resource limits from config."""
        limits = {}
        
        if config.get('limits.cpu'):
            limits['cpu'] = config['limits.cpu']
        if config.get('limits.memory'):
            limits['memory'] = config['limits.memory']
        
        for key in ['limits.disk.priority', 'limits.disk.read', 'limits.disk.write',
                     'limits.network.priority', 'limits.network.egress', 'limits.network.ingress',
                     'limits.processes']:
            if key in config:
                limits[key.replace('limits.', '')] = config[key]
        
        return limits if limits else None
    
    def _extract_security(self, config):
        """Extracts security-related settings from config."""
        security = {}
        security_keys = [
            'security.nesting', 'security.privileged',
            'security.protection.delete', 'security.protection.shift',
            'security.idmap.isolated', 'security.secureboot',
            'security.devlxd', 'security.devlxd.images',
        ]
        
        for key in security_keys:
            if key in config:
                short_key = key.replace('security.', '')
                value = config[key]
                if value in ('true', 'false'):
                    value = value == 'true'
                security[short_key] = value
        
        return security if security else None
    
    def _sanitize_config(self, config):
        """
        Sanitizes configuration by removing sensitive or volatile data.
        
        Args:
            config: Raw Incus config dict
            
        Returns:
            dict: Sanitized config
        """
        if not config:
            return {}
        
        sanitized = {}
        
        exclude_prefixes = [
            'volatile.',      # Volatile runtime data (UUIDs, IPs, etc.)
            'image.',         # Already captured elsewhere
        ]
        
        exclude_exact = [
            'user.password',
            'user.access_key',
            'user.secret_key',
        ]
        
        for key, value in config.items():
            if any(key.startswith(prefix) for prefix in exclude_prefixes):
                continue
            if key in exclude_exact:
                continue
            sanitized[key] = value
        
        return sanitized
    
    def _sanitize_devices(self, devices):
        """
        Sanitizes devices configuration.
        
        Args:
            devices: Raw Incus devices dict
            
        Returns:
            dict: Sanitized devices
        """
        if not devices:
            return {}
        
        sanitized = {}
        
        for name, device in devices.items():
            sanitized_device = {}
            
            for key, value in device.items():
                if key in ['source'] and device.get('type') == 'disk':
                    sanitized_device[key] = value
                elif key.startswith('user.'):
                    continue
                else:
                    sanitized_device[key] = value
            
            sanitized[name] = sanitized_device
        
        return sanitized
    
    def clear_local_context(self, vm):
        """
        Removes Incus data from a VM's local_context_data.
        
        Args:
            vm: VirtualMachine instance
            
        Returns:
            bool: True if data was removed
        """
        if not vm.local_context_data or 'incus' not in vm.local_context_data:
            return False
        
        new_context = dict(vm.local_context_data)
        del new_context['incus']
        
        vm.local_context_data = new_context if new_context else None
        vm.save(update_fields=['local_context_data'])
        
        self.log('info', f"    Local context cleared for {vm.name}")
        return True