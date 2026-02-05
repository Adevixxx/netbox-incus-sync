"""
Incus configuration synchronization service to NetBox local_context_data.

This service synchronizes Incus instance configurations (expanded_config, 
expanded_devices, profiles) directly to the VM's local_context_data field,
enabling:
- Infrastructure-as-Code workflows (Ansible, Terraform)
- Configuration auditing and tracking
- Data export for external tools
- Proper per-VM rendered context in NetBox UI
"""


class ConfigContextSyncService:
    """Service to synchronize Incus configurations to VM local_context_data."""
    
    def __init__(self, logger=None):
        self.logger = logger
    
    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)
    
    def sync_instance_config_context(self, vm, instance_data, host):
        """
        Synchronizes an Incus instance configuration to the VM's local_context_data.
        
        Stores:
        - expanded_config: All configuration including profile inheritance
        - expanded_devices: All devices including profile inheritance
        - profiles: List of applied profiles
        - instance metadata (type, status, location, etc.)
        
        Args:
            vm: VirtualMachine instance
            instance_data: Raw Incus instance data
            host: IncusHost instance
            
        Returns:
            tuple: (updated: bool, created: bool)
        """
        # Build the context data structure
        context_data = self._build_context_data(instance_data, host)
        
        # Check if data changed
        old_data = vm.local_context_data or {}
        old_incus = old_data.get('incus', {})
        new_incus = context_data.get('incus', {})
        
        # Determine if this is a create or update
        created = 'incus' not in old_data
        
        # Compare relevant fields (skip last_used_at as it changes frequently)
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
        # Extract configurations
        expanded_config = instance_data.get('expanded_config', {})
        expanded_devices = instance_data.get('expanded_devices', {})
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
                
                # Applied profiles (order matters!)
                'profiles': profiles,
                
                # Resource limits (extracted for easy access)
                'limits': self._extract_limits(expanded_config),
                
                # Full expanded configuration (includes profile inheritance)
                'expanded_config': self._sanitize_config(expanded_config),
                
                # Full expanded devices (includes profile inheritance)
                'expanded_devices': self._sanitize_devices(expanded_devices),
                
                # Instance-specific overrides only (not from profiles)
                'instance_config': self._sanitize_config(config),
                'instance_devices': self._sanitize_devices(devices),
                
                # Security settings (extracted for easy access)
                'security': self._extract_security(expanded_config),
                
                # Network configuration summary
                'network': self._extract_network_summary(expanded_devices),
                
                # Storage configuration summary  
                'storage': self._extract_storage_summary(expanded_devices),
            }
        }
        
        # Remove None values for cleaner output
        context_data['incus'] = {k: v for k, v in context_data['incus'].items() if v is not None}
        
        return context_data
    
    def _extract_limits(self, config):
        """Extracts resource limits from config."""
        limits = {}
        
        # CPU
        cpu = config.get('limits.cpu')
        if cpu:
            limits['cpu'] = cpu
        
        # Memory
        memory = config.get('limits.memory')
        if memory:
            limits['memory'] = memory
        
        # Disk I/O
        for key in ['limits.disk.priority', 'limits.disk.read', 'limits.disk.write']:
            if key in config:
                limits[key.replace('limits.', '')] = config[key]
        
        # Network I/O
        for key in ['limits.network.priority', 'limits.network.egress', 'limits.network.ingress']:
            if key in config:
                limits[key.replace('limits.', '')] = config[key]
        
        # Process limits
        if 'limits.processes' in config:
            limits['processes'] = config['limits.processes']
        
        return limits if limits else None
    
    def _extract_security(self, config):
        """Extracts security-related settings from config."""
        security = {}
        
        security_keys = [
            'security.nesting',
            'security.privileged', 
            'security.protection.delete',
            'security.protection.shift',
            'security.idmap.isolated',
            'security.secureboot',
            'security.devlxd',
            'security.devlxd.images',
        ]
        
        for key in security_keys:
            if key in config:
                # Convert to proper key name and boolean if applicable
                short_key = key.replace('security.', '')
                value = config[key]
                
                # Convert string booleans
                if value in ('true', 'false'):
                    value = value == 'true'
                
                security[short_key] = value
        
        return security if security else None
    
    def _extract_network_summary(self, devices):
        """Extracts network device summary."""
        networks = []
        
        for name, device in devices.items():
            if device.get('type') != 'nic':
                continue
            
            net_info = {
                'name': name,
                'type': device.get('nictype', device.get('type', '')),
            }
            
            # Add relevant network properties
            for key in ['network', 'parent', 'hwaddr', 'host_name', 'mtu', 'vlan']:
                if key in device:
                    net_info[key] = device[key]
            
            networks.append(net_info)
        
        return networks if networks else None
    
    def _extract_storage_summary(self, devices):
        """Extracts storage device summary."""
        storage = []
        
        for name, device in devices.items():
            if device.get('type') != 'disk':
                continue
            
            disk_info = {
                'name': name,
                'path': device.get('path', ''),
            }
            
            # Add relevant disk properties
            for key in ['pool', 'source', 'size', 'readonly', 'shift']:
                if key in device:
                    disk_info[key] = device[key]
            
            storage.append(disk_info)
        
        return storage if storage else None
    
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
        
        # Keys to exclude (sensitive or too volatile)
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
            # Skip excluded prefixes
            if any(key.startswith(prefix) for prefix in exclude_prefixes):
                continue
            
            # Skip exact matches
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
            # Copy device config, excluding sensitive fields
            sanitized_device = {}
            
            for key, value in device.items():
                # Skip sensitive fields
                if key in ['source'] and device.get('type') == 'disk':
                    # Keep source for disks as it's useful info
                    sanitized_device[key] = value
                elif key.startswith('user.'):
                    # Skip user-defined sensitive data
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