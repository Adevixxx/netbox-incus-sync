"""
Incus profile synchronization service to NetBox Config Contexts.

This service maps Incus profiles to NetBox's Config Context system:
- Each Incus profile becomes a NetBox ConfigContext object
- Tags (incus-profile:<name>) are used for automatic association
- Profile stacking order is translated to ConfigContext weights
- Instance-specific overrides remain in local_context_data
"""

import json
import re

from extras.models import ConfigContext, Tag
from django.contrib.contenttypes.models import ContentType
from virtualization.models import VirtualMachine


# Base weight for profile-based config contexts
# Profiles are ordered: position 0 → 1000, position 1 → 1100, etc.
PROFILE_BASE_WEIGHT = 1000
PROFILE_WEIGHT_STEP = 100

# Tag prefix for profile-based tags
PROFILE_TAG_PREFIX = 'incus-profile'

# ConfigContext name prefix
CONTEXT_NAME_PREFIX = 'incus'

# Keys to exclude from profile config (sensitive or volatile)
EXCLUDE_CONFIG_PREFIXES = [
    'volatile.',
    'image.',
]

EXCLUDE_CONFIG_EXACT = [
    'user.password',
    'user.access_key',
    'user.secret_key',
]


class ProfileSyncService:
    """
    Service to synchronize Incus profiles to NetBox Config Contexts.
    
    Creates one ConfigContext per profile per host, using tags for
    automatic association with VMs that use those profiles.
    """
    
    def __init__(self, logger=None):
        self.logger = logger
        self._tag_cache = {}  # slug → Tag
        self._vm_content_type = None
    
    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)
    
    @property
    def vm_content_type(self):
        if self._vm_content_type is None:
            self._vm_content_type = ContentType.objects.get_for_model(VirtualMachine)
        return self._vm_content_type
    
    # ========================================================================
    # Public API
    # ========================================================================
    
    def sync_profiles(self, profiles_data, host):
        """
        Synchronizes all Incus profiles for a host to NetBox Config Contexts.
        
        Args:
            profiles_data: List of profile dicts from Incus API (recursion=1)
            host: IncusHost instance
            
        Returns:
            dict: Statistics {profiles_synced, profiles_created, profiles_updated, profiles_removed}
        """
        stats = {
            'profiles_synced': 0,
            'profiles_created': 0,
            'profiles_updated': 0,
            'profiles_removed': 0,
        }
        
        if not profiles_data:
            self.log('info', '  No profiles to sync')
            return stats
        
        self.log('info', f'  > {len(profiles_data)} profiles found')
        
        # Track which context names we've seen for cleanup
        synced_context_names = set()
        
        for idx, profile_data in enumerate(profiles_data):
            profile_name = profile_data.get('name', '')
            if not profile_name:
                continue
            
            context_name = self._make_context_name(host.name, profile_name)
            synced_context_names.add(context_name)
            
            created, updated = self._sync_single_profile(
                profile_data=profile_data,
                host=host,
                position=idx,
            )
            
            stats['profiles_synced'] += 1
            if created:
                stats['profiles_created'] += 1
            elif updated:
                stats['profiles_updated'] += 1
        
        # Cleanup: remove Config Contexts for profiles that no longer exist
        removed = self._cleanup_stale_contexts(host.name, synced_context_names)
        stats['profiles_removed'] = removed
        
        return stats
    
    def assign_profile_tags_to_vm(self, vm, profile_names):
        """
        Assigns profile tags to a VM based on its Incus profile list.
        
        Ensures the VM has exactly the right set of incus-profile:* tags.
        Removes stale profile tags and adds missing ones.
        
        Args:
            vm: VirtualMachine instance
            profile_names: List of profile names from Incus instance data
            
        Returns:
            bool: True if tags were modified
        """
        # Desired profile tags
        desired_slugs = set()
        for name in profile_names:
            slug = self._make_tag_slug(name)
            desired_slugs.add(slug)
            # Ensure the tag exists
            self._get_or_create_profile_tag(name)
        
        # Current profile tags on the VM
        current_profile_tags = set(
            vm.tags.filter(slug__startswith=f'{PROFILE_TAG_PREFIX}-')
            .values_list('slug', flat=True)
        )
        
        # Also include tags with the colon format  
        current_profile_tags_colon = set(
            vm.tags.filter(slug__startswith=f'{PROFILE_TAG_PREFIX}')
            .values_list('slug', flat=True)
        )
        current_profile_tags = current_profile_tags | current_profile_tags_colon
        
        # Filter to only our managed profile tags
        current_managed = {s for s in current_profile_tags if self._is_profile_tag_slug(s)}
        
        tags_to_add = desired_slugs - current_managed
        tags_to_remove = current_managed - desired_slugs
        
        modified = False
        
        # Remove stale tags
        if tags_to_remove:
            stale_tags = Tag.objects.filter(slug__in=tags_to_remove)
            for tag in stale_tags:
                vm.tags.remove(tag)
                self.log('debug', f"    Removed tag '{tag.slug}' from {vm.name}")
            modified = True
        
        # Add missing tags
        if tags_to_add:
            for slug in tags_to_add:
                tag = self._tag_cache.get(slug)
                if not tag:
                    tag = Tag.objects.filter(slug=slug).first()
                if tag:
                    vm.tags.add(tag)
                    self.log('debug', f"    Added tag '{tag.slug}' to {vm.name}")
            modified = True
        
        return modified
    
    # ========================================================================
    # Internal methods
    # ========================================================================
    
    def _sync_single_profile(self, profile_data, host, position):
        """
        Syncs a single Incus profile to a NetBox ConfigContext.
        
        Args:
            profile_data: Raw profile dict from Incus API
            host: IncusHost instance  
            position: Index in the profiles list (for weight calculation)
            
        Returns:
            tuple: (created: bool, updated: bool)
        """
        profile_name = profile_data.get('name', '')
        context_name = self._make_context_name(host.name, profile_name)
        weight = PROFILE_BASE_WEIGHT + (position * PROFILE_WEIGHT_STEP)
        
        # Build the context data from the profile
        context_data = self._build_profile_context_data(profile_data, host)
        
        # Ensure the profile tag exists
        profile_tag = self._get_or_create_profile_tag(profile_name)
        
        # Try to find existing ConfigContext
        try:
            config_context = ConfigContext.objects.get(name=context_name)
            
            # Check if update needed
            data_changed = config_context.data != context_data
            weight_changed = config_context.weight != weight
            is_active_changed = not config_context.is_active
            
            if data_changed or weight_changed or is_active_changed:
                config_context.data = context_data
                config_context.weight = weight
                config_context.is_active = True
                config_context.description = self._make_description(profile_data, host)
                config_context.save()
                
                # Ensure tag assignment
                if not config_context.tags.filter(pk=profile_tag.pk).exists():
                    config_context.tags.add(profile_tag)
                
                self.log('debug', f"    Profile '{profile_name}' updated (weight: {weight})")
                return False, True
            
            return False, False
            
        except ConfigContext.DoesNotExist:
            # Create new ConfigContext
            config_context = ConfigContext.objects.create(
                name=context_name,
                weight=weight,
                data=context_data,
                description=self._make_description(profile_data, host),
                is_active=True,
            )
            
            # Assign the profile tag for auto-association
            config_context.tags.add(profile_tag)
            
            self.log('info', f"    Profile '{profile_name}' → ConfigContext created (weight: {weight})")
            return True, False
    
    def _build_profile_context_data(self, profile_data, host):
        """
        Builds structured JSON data from an Incus profile.
        
        The data is namespaced under 'incus.profiles.<name>' to avoid
        collisions when multiple profiles are merged by NetBox.
        
        Args:
            profile_data: Raw Incus profile dict
            host: IncusHost instance
            
        Returns:
            dict: Structured context data
        """
        profile_name = profile_data.get('name', '')
        config = profile_data.get('config', {})
        devices = profile_data.get('devices', {})
        
        # Sanitize config (remove volatile/sensitive keys)
        sanitized_config = self._sanitize_config(config)
        
        # Sanitize devices
        sanitized_devices = self._sanitize_devices(devices)
        
        # Extract useful summaries
        limits = self._extract_limits(sanitized_config)
        security = self._extract_security(sanitized_config)
        network_summary = self._extract_network_summary(devices)
        storage_summary = self._extract_storage_summary(devices)
        
        # Build the data structure
        # Namespace under incus.profiles.<name> so multiple profiles merge cleanly
        data = {
            'incus': {
                'profiles': {
                    profile_name: {
                        'config': sanitized_config,
                        'devices': sanitized_devices,
                        'description': profile_data.get('description', ''),
                        'source_host': host.name,
                    }
                }
            }
        }
        
        # Add extracted summaries at profile level
        profile_section = data['incus']['profiles'][profile_name]
        if limits:
            profile_section['limits'] = limits
        if security:
            profile_section['security'] = security
        if network_summary:
            profile_section['network'] = network_summary
        if storage_summary:
            profile_section['storage'] = storage_summary
        
        return data
    
    def _cleanup_stale_contexts(self, host_name, active_context_names):
        """
        Removes Config Contexts for profiles that no longer exist on the host.
        
        Args:
            host_name: Incus host name
            active_context_names: Set of context names that should exist
            
        Returns:
            int: Number of contexts removed
        """
        prefix = f"{CONTEXT_NAME_PREFIX}:{host_name}:"
        
        stale_contexts = ConfigContext.objects.filter(
            name__startswith=prefix
        ).exclude(
            name__in=active_context_names
        )
        
        count = stale_contexts.count()
        if count > 0:
            for ctx in stale_contexts:
                self.log('info', f"    Removed stale ConfigContext: {ctx.name}")
            stale_contexts.delete()
        
        return count
    
    # ========================================================================
    # Tag management
    # ========================================================================
    
    def _get_or_create_profile_tag(self, profile_name):
        """
        Gets or creates a tag for an Incus profile.
        
        Tag format: incus-profile-<sanitized_name>
        
        Args:
            profile_name: Incus profile name
            
        Returns:
            Tag: The NetBox Tag object
        """
        slug = self._make_tag_slug(profile_name)
        
        if slug in self._tag_cache:
            return self._tag_cache[slug]
        
        tag, created = Tag.objects.get_or_create(
            slug=slug,
            defaults={
                'name': f'Incus Profile: {profile_name}',
                'description': f'Auto-managed tag for Incus profile "{profile_name}". '
                               f'Used for Config Context association.',
                'color': '3f51b5',  # Indigo - visually distinct for Incus tags
            }
        )
        
        self._tag_cache[slug] = tag
        
        if created:
            self.log('info', f"    Created tag: {tag.name} ({slug})")
        
        return tag
    
    def _make_tag_slug(self, profile_name):
        """
        Creates a valid NetBox tag slug from a profile name.
        
        Handles special characters and ensures uniqueness.
        
        Args:
            profile_name: Incus profile name (e.g., "web-server", "default")
            
        Returns:
            str: Valid slug (e.g., "incus-profile-web-server")
        """
        # Sanitize: lowercase, replace non-alphanumeric with hyphens
        sanitized = re.sub(r'[^a-z0-9]+', '-', profile_name.lower()).strip('-')
        return f'{PROFILE_TAG_PREFIX}-{sanitized}'
    
    def _is_profile_tag_slug(self, slug):
        """Checks if a slug is one of our managed profile tags."""
        return slug.startswith(f'{PROFILE_TAG_PREFIX}-')
    
    # ========================================================================
    # Naming helpers
    # ========================================================================
    
    def _make_context_name(self, host_name, profile_name):
        """
        Creates a unique ConfigContext name for a host+profile combination.
        
        Format: incus:<host_name>:<profile_name>
        """
        return f"{CONTEXT_NAME_PREFIX}:{host_name}:{profile_name}"
    
    def _make_description(self, profile_data, host):
        """Creates a human-readable description for the ConfigContext."""
        profile_name = profile_data.get('name', '')
        profile_desc = profile_data.get('description', '')
        
        parts = [f"Auto-synced from Incus profile '{profile_name}' on host '{host.name}'."]
        if profile_desc:
            parts.append(f"Profile description: {profile_desc}")
        
        return ' '.join(parts)
    
    # ========================================================================
    # Config/device sanitization (reused from ConfigContextSyncService)
    # ========================================================================
    
    def _sanitize_config(self, config):
        """Sanitizes configuration by removing sensitive or volatile data."""
        if not config:
            return {}
        
        sanitized = {}
        for key, value in config.items():
            if any(key.startswith(prefix) for prefix in EXCLUDE_CONFIG_PREFIXES):
                continue
            if key in EXCLUDE_CONFIG_EXACT:
                continue
            sanitized[key] = value
        
        return sanitized
    
    def _sanitize_devices(self, devices):
        """Sanitizes devices configuration."""
        if not devices:
            return {}
        
        sanitized = {}
        for name, device in devices.items():
            sanitized_device = {}
            for key, value in device.items():
                if key.startswith('user.'):
                    continue
                sanitized_device[key] = value
            sanitized[name] = sanitized_device
        
        return sanitized
    
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
    
    def _extract_network_summary(self, devices):
        """Extracts network device summary."""
        networks = []
        for name, device in devices.items():
            if device.get('type') != 'nic':
                continue
            net_info = {'name': name, 'type': device.get('nictype', device.get('type', ''))}
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
            disk_info = {'name': name, 'path': device.get('path', '')}
            for key in ['pool', 'source', 'size', 'readonly', 'shift']:
                if key in device:
                    disk_info[key] = device[key]
            storage.append(disk_info)
        return storage if storage else None