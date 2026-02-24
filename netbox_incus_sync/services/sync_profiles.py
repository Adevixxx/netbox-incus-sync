"""
Incus profile synchronization service to NetBox Config Contexts.

This service maps Incus profiles to NetBox's Config Context system:
- Each Incus profile becomes a NetBox ConfigContext object
- ConfigContexts are scoped by TenantGroup (per host) instead of name prefixes
- Tags (incus-profile-<name>) are used for automatic association
- Profile stacking order is translated to ConfigContext weights
- Instance-specific overrides remain in local_context_data

CHANGES vs previous version:
- ConfigContext names: "incus:host:profile" → "profile" (scoped by tenant_groups)
- Tags name: "Incus Profile: xyz" → "xyz" (just the profile name)
- Tags description: generic text → actual Incus profile description
- ConfigContext scoping: uses TenantGroup assignment instead of name prefix
- Migration: automatically cleans up old colon-separated ConfigContext names
"""

import json
import re

from extras.models import ConfigContext, Tag
from tenancy.models import TenantGroup
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

# Tag prefix for profile-based tags (slug only, for identification)
PROFILE_TAG_PREFIX = 'incus-profile'

# Old ConfigContext name prefix (for migration/cleanup)
OLD_CONTEXT_NAME_PREFIX = 'incus'

# TenantGroup slug prefix (reuse the same as TenantSyncService)
TENANT_GROUP_SLUG_PREFIX = 'incus-projects'


class ProfileSyncService:
    """
    Service to synchronize Incus profiles to NetBox Config Contexts.

    Creates one ConfigContext per profile per host, using tags for
    automatic association with VMs that use those profiles.

    ConfigContexts are scoped to the host's TenantGroup so that profiles
    from different hosts don't collide, without needing ugly name prefixes.
    """

    def __init__(self, logger=None):
        self.logger = logger
        self._tag_cache = {}  # slug → Tag
        self._vm_content_type = None
        self._tenant_group_cache = {}  # host_name → TenantGroup

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

        # Migrate old colon-separated ConfigContext names first
        self._migrate_old_context_names(host)

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

        Ensures the VM has exactly the right set of incus-profile-* tags.
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

        # Also catch any old colon-style tags that may still be assigned
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
        profile_description = profile_data.get('description', '')
        context_name = self._make_context_name(host.name, profile_name)

        tag = self._get_or_create_profile_tag(profile_name, profile_description)

        context_data = self._build_profile_context_data(profile_data, host)

        weight = PROFILE_BASE_WEIGHT + (position * PROFILE_WEIGHT_STEP)
        description = self._make_description(profile_data, host)

        # Get the TenantGroup for scoping
        tenant_group = self._get_tenant_group(host)

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

            # Ensure tag association
            if tag not in ctx.tags.all():
                ctx.tags.add(tag)

            # Ensure TenantGroup scoping
            if tenant_group and tenant_group not in ctx.tenant_groups.all():
                ctx.tenant_groups.add(tenant_group)

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
            if tenant_group:
                ctx.tenant_groups.add(tenant_group)
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
        """
        Removes Config Contexts for profiles that no longer exist on the host.

        Uses TenantGroup scoping to identify managed ConfigContexts for this host
        instead of relying on a name prefix.
        """
        tenant_group = self._get_tenant_group_for_host(host_name)
        if not tenant_group:
            return 0

        # Find all ConfigContexts scoped to this host's TenantGroup
        stale_contexts = ConfigContext.objects.filter(
            tenant_groups=tenant_group
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
    # Migration: old colon-separated names → new dash-separated names
    # ========================================================================

    def _migrate_old_context_names(self, host):
        """
        Migrates ConfigContexts from old naming schemes to just the profile name,
        and adds TenantGroup scoping.

        Old formats:
        - "incus:host:profile" (colon-separated)
        - "incus-host-profile" (dash-separated with prefix)

        New format:
        - "profile" (just the profile name, scoped by TenantGroup)

        This runs once per sync and is idempotent.
        """
        tenant_group = self._get_tenant_group(host)

        # Migrate colon-separated format: "incus:hostname:profilename"
        old_prefix_colon = f"{OLD_CONTEXT_NAME_PREFIX}:{host.name}:"
        old_contexts = ConfigContext.objects.filter(name__startswith=old_prefix_colon)

        migrated = 0
        for ctx in old_contexts:
            parts = ctx.name.split(':', 2)
            if len(parts) != 3:
                continue
            profile_name = parts[2]
            self._do_migrate_context(ctx, profile_name, tenant_group)
            migrated += 1

        # Migrate dash-separated format: "incus-hostname-profilename"
        old_prefix_dash = f"incus-{host.name}-"
        old_contexts_dash = ConfigContext.objects.filter(name__startswith=old_prefix_dash)

        for ctx in old_contexts_dash:
            profile_name = ctx.name[len(old_prefix_dash):]
            if not profile_name:
                continue
            self._do_migrate_context(ctx, profile_name, tenant_group)
            migrated += 1

        if migrated:
            self.log('info', f"    Migration: {migrated} ConfigContext(s) renamed")

    def _do_migrate_context(self, ctx, new_name, tenant_group):
        """Renames a ConfigContext and adds TenantGroup scoping."""
        old_name = ctx.name

        # Check if target name already exists (avoid collision)
        if ConfigContext.objects.filter(name=new_name).exclude(pk=ctx.pk).exists():
            self.log('warning',
                f"    Migration skip: '{old_name}' → '{new_name}' (target already exists)")
            ctx.delete()
            return

        ctx.name = new_name
        ctx.save()

        if tenant_group and tenant_group not in ctx.tenant_groups.all():
            ctx.tenant_groups.add(tenant_group)

        self.log('info', f"    Migrated ConfigContext: '{old_name}' → '{new_name}'")

    # ========================================================================
    # Tag management
    # ========================================================================

    def _get_or_create_profile_tag(self, profile_name, profile_description=''):
        """
        Gets or creates a tag for an Incus profile.

        Tag naming:
        - slug: incus-profile-<sanitized_name>  (for programmatic identification)
        - name: <profile_name>                   (clean display name, no prefix)
        - description: the Incus profile description (if available)

        If the tag already exists, its description is updated if the Incus
        profile description has changed.
        """
        slug = self._make_tag_slug(profile_name)

        if slug in self._tag_cache:
            tag = self._tag_cache[slug]
            # Update description if changed
            if profile_description and tag.description != profile_description:
                tag.description = profile_description
                tag.save(update_fields=['description'])
            return tag

        # Build the description: use Incus profile description if available
        description = profile_description or f'Incus profile: {profile_name}'

        tag, created = Tag.objects.get_or_create(
            slug=slug,
            defaults={
                'name': profile_name,
                'description': description,
                'color': '3f51b5',
            }
        )

        # If tag existed but has old-style name, update it
        updated = False
        if not created:
            if tag.name != profile_name and tag.name.startswith('Incus Profile:'):
                tag.name = profile_name
                updated = True
            if profile_description and tag.description != profile_description:
                tag.description = profile_description
                updated = True
            if updated:
                tag.save()
                self.log('info', f"    Updated tag: {tag.name} ({slug})")

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
    # TenantGroup helpers
    # ========================================================================

    def _get_tenant_group(self, host):
        """
        Gets the TenantGroup for a host (created by TenantSyncService).

        Returns None if the TenantGroup doesn't exist yet (e.g. first sync
        before projects are synced).
        """
        return self._get_tenant_group_for_host(host.name)

    def _get_tenant_group_for_host(self, host_name):
        """
        Gets the TenantGroup for a host by name.

        Returns None if the TenantGroup doesn't exist yet.
        """
        if host_name in self._tenant_group_cache:
            return self._tenant_group_cache[host_name]

        slug = f"{TENANT_GROUP_SLUG_PREFIX}-{host_name}"
        try:
            tg = TenantGroup.objects.get(slug=slug)
        except TenantGroup.DoesNotExist:
            tg = None

        self._tenant_group_cache[host_name] = tg
        return tg

    # ========================================================================
    # Naming helpers
    # ========================================================================

    def _make_context_name(self, host_name, profile_name):
        """
        Creates a unique ConfigContext name for a host+profile combination.

        The name is just the profile name — scoping is handled by TenantGroup
        assignment, so no host prefix is needed in the name.

        Old format was: "incus:<host_name>:<profile_name>" (colon-separated)
        """
        return profile_name

    def _make_description(self, profile_data, host):
        """Creates a description for the ConfigContext from the Incus profile description."""
        profile_desc = profile_data.get('description', '')
        return profile_desc if profile_desc else ''

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
            disk_info = {'name': name}
            for key in ['path', 'pool', 'source', 'size']:
                if key in device:
                    disk_info[key] = device[key]
            storage.append(disk_info)
        return storage if storage else None