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

from .sync_utils import sanitize_config, sanitize_devices, extract_limits, extract_security


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
        context_data = self._build_context_data(instance_data, host)

        old_data = vm.local_context_data or {}
        old_incus = old_data.get('incus', {})
        new_incus = context_data.get('incus', {})

        created = 'incus' not in old_data

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

        if created or old_normalized != new_normalized:
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
        config = instance_data.get('config', {})
        devices = instance_data.get('devices', {})
        profiles = instance_data.get('profiles', [])

        context_data = {
            'incus': {
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

                'source': {
                    'host': host.name,
                    'connection_type': host.connection_type,
                },

                'profiles': profiles,

                'instance_config': sanitize_config(config),
                'instance_devices': sanitize_devices(devices),

                'instance_limits': extract_limits(config),
                'instance_security': extract_security(config),
            }
        }

        # Remove None values for cleaner output
        context_data['incus'] = {k: v for k, v in context_data['incus'].items() if v is not None}

        return context_data