"""
Incus profile synchronization service to NetBox Config Contexts.

This service maps Incus profiles to NetBox's Config Context system:
- Each Incus profile becomes a NetBox ConfigContext object
- Tags (incus-profile:<n>) are used for automatic association
- Profile stacking order is translated to ConfigContext weights
- Instance-specific overrides remain in local_context_data
"""

import json
import re

from extras.models import ConfigContext, Tag
from django.contrib.contenttypes.models import ContentType
from virtualization.models import VirtualMachine

from .sync_utils import (
    sanitize_config, sanitize_devices,
    extract_limits, extract_security,
    EXCLUDE_CONFIG_PREFIXES, EXCLUDE_CONFIG_EXACT,
)


# Base weight for profile-based config contexts
PROFILE_BASE_WEIGHT = 1000
PROFILE_WEIGHT_STEP = 100

# Tag prefix for profile-based tags
PROFILE_TAG_PREFIX = 'incus-profile'

# ConfigContext name prefix
CONTEXT_NAME_PREFIX = 'incus'


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

        removed = self._cleanup_stale_contexts(host.name, synced_context_names)
        stats['profiles_removed'] = removed

        changed = stats['profiles_created'] + stats['profiles_updated'] + stats['profiles_removed']
        self.log('info', f"    Profiles: {stats['profiles_synced']} synced ({changed} changed)")

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
        desired_slugs = set()
        for name in profile_names:
            slug = self._make_tag_slug(name)
            desired_slugs.add(slug)
            self._get_or_create_profile_tag(name)

        current_profile_tags = set(
            vm.tags.filter(slug__startswith=f'{PROFILE_TAG_PREFIX}-')
            .values_list('slug', flat=True)
        )

        current_profile_tags_colon = set(
            vm.tags.filter(slug__startswith=f'{PROFILE_TAG_PREFIX}')
            .values_list('slug', flat=True)
        )
        current_profile_tags = current_profile_tags | current_profile_tags_colon

        current_managed = {s for s in current_profile_tags if self._is_profile_tag_slug(s)}

        tags_to_add = desired_slugs - current_managed
        tags_to_remove = current_managed - desired_slugs

        modified = False

        if tags_to_remove:
            stale_tags = Tag.objects.filter(slug__in=tags_to_remove)
            for tag in stale_tags:
                vm.tags.remove(tag)
                self.log('debug', f"    Removed tag '{tag.slug}' from {vm.name}")
            modified = True

        if tags_to_add:
            for slug in tags_to_add:
                tag = self._tag_cache.get(slug) or Tag.objects.filter(slug=slug).first()
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
            profile_data: Raw Incus profile dict
            host: IncusHost instance
            position: Profile position in the list (for weight calculation)

        Returns:
            tuple: (created: bool, updated: bool)
        """
        profile_name = profile_data.get('name', '')
        context_name = self._make_context_name(host.name, profile_name)

        tag = self._get_or_create_profile_tag(profile_name)

        context_data = self._build_profile_context_data(profile_data, host)

        weight = PROFILE_BASE_WEIGHT + (position * PROFILE_WEIGHT_STEP)
        description = self._make_description(profile_data, host)

        try:
            ctx = ConfigContext.objects.get(name=context_name)

            updated = False
            if ctx.data != context_data:
                ctx.data = context_data
                updated = True
            if ctx.weight != weight:
                ctx.weight = weight
                updated = True
            if ctx.description != description:
                ctx.description = description
                updated = True

            if updated:
                ctx.save()

            if tag not in ctx.tags.all():
                ctx.tags.add(tag)

            return False, updated

        except ConfigContext.DoesNotExist:
            ctx = ConfigContext.objects.create(
                name=context_name,
                weight=weight,
                description=description,
                data=context_data,
                is_active=True,
            )
            ctx.tags.add(tag)
            self.log('info', f"    Created ConfigContext: {context_name}")
            return True, False

    def _build_profile_context_data(self, profile_data, host):
        """
        Builds the ConfigContext data structure from an Incus profile.

        Args:
            profile_data: Raw Incus profile dict
            host: IncusHost instance

        Returns:
            dict: Structured context data
        """
        profile_name = profile_data.get('name', '')
        config = profile_data.get('config', {})
        devices = profile_data.get('devices', {})

        sanitized_config = sanitize_config(config)
        sanitized_devs = sanitize_devices(devices)

        limits = extract_limits(sanitized_config)
        security = extract_security(sanitized_config)
        network_summary = self._extract_network_summary(devices)
        storage_summary = self._extract_storage_summary(devices)

        data = {
            'incus': {
                'profiles': {
                    profile_name: {
                        'config': sanitized_config,
                        'devices': sanitized_devs,
                        'description': profile_data.get('description', ''),
                        'source_host': host.name,
                    }
                }
            }
        }

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
        """Removes Config Contexts for profiles that no longer exist on the host."""
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
        """Gets or creates a tag for an Incus profile."""
        slug = self._make_tag_slug(profile_name)

        if slug in self._tag_cache:
            return self._tag_cache[slug]

        tag, created = Tag.objects.get_or_create(
            slug=slug,
            defaults={
                'name': f'Incus Profile: {profile_name}',
                'description': f'Auto-managed tag for Incus profile "{profile_name}". '
                               f'Used for Config Context association.',
                'color': '3f51b5',
            }
        )

        self._tag_cache[slug] = tag

        if created:
            self.log('info', f"    Created tag: {tag.name} ({slug})")

        return tag

    def _make_tag_slug(self, profile_name):
        """Creates a valid NetBox tag slug from a profile name."""
        sanitized = re.sub(r'[^a-z0-9]+', '-', profile_name.lower()).strip('-')
        return f'{PROFILE_TAG_PREFIX}-{sanitized}'

    def _is_profile_tag_slug(self, slug):
        """Checks if a slug is one of our managed profile tags."""
        return slug.startswith(f'{PROFILE_TAG_PREFIX}-')

    # ========================================================================
    # Naming helpers
    # ========================================================================

    def _make_context_name(self, host_name, profile_name):
        """Creates a unique ConfigContext name for a host+profile combination."""
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
    # Summary extractors (profile-specific, not shared)
    # ========================================================================

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