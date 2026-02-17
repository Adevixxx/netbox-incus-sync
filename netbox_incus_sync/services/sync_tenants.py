"""
Incus project → NetBox Tenant synchronization service.

Maps Incus projects to NetBox Tenants so that instances from different
projects can share the same name within a cluster (NetBox uniqueness
constraint is on the triplet: name + cluster + tenant).

Project features (features.images, features.profiles, features.networks,
features.storage.volumes, features.storage.buckets) are stored as custom
fields on the Tenant so the sync engine knows which resources are isolated
per-project vs shared from the ``default`` project.
"""

import logging

from tenancy.models import Tenant, TenantGroup
from extras.models import Tag

logger = logging.getLogger(__name__)

# Slug for the auto-created TenantGroup that holds all Incus project tenants
INCUS_TENANT_GROUP_SLUG = 'incus-projects'

# Tag applied to tenants managed by this service
INCUS_TENANT_TAG_SLUG = 'incus-managed'

# Project features we track — these become custom field keys on the Tenant
PROJECT_FEATURES = [
    'features.images',
    'features.profiles',
    'features.networks',
    'features.networks.zones',
    'features.storage.volumes',
    'features.storage.buckets',
]


class TenantSyncService:
    """
    Service to synchronize Incus projects to NetBox Tenants.
    
    Creates one Tenant per project and groups them under a single
    TenantGroup "Incus Projects". The ``default`` project also gets
    a Tenant so that VMs in it are explicitly scoped.
    """

    def __init__(self, logger=None):
        self.logger = logger
        self._tenant_group = None
        self._managed_tag = None

    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)

    # ========== Lazy properties ==========

    @property
    def tenant_group(self):
        """Gets or creates the 'Incus Projects' TenantGroup."""
        if self._tenant_group is None:
            self._tenant_group, created = TenantGroup.objects.get_or_create(
                slug=INCUS_TENANT_GROUP_SLUG,
                defaults={
                    'name': 'Incus Projects',
                    'description': 'Auto-created group for Incus project tenants',
                }
            )
            if created:
                self.log('info', '  TenantGroup "Incus Projects" created')
        return self._tenant_group

    @property
    def managed_tag(self):
        """Gets or creates the 'incus-managed' tag."""
        if self._managed_tag is None:
            self._managed_tag, _ = Tag.objects.get_or_create(
                slug=INCUS_TENANT_TAG_SLUG,
                defaults={'name': 'Incus Managed'}
            )
        return self._managed_tag

    # ========== Public API ==========

    def sync_project_as_tenant(self, project_data):
        """
        Synchronizes a single Incus project to a NetBox Tenant.

        Args:
            project_data: dict from Incus API (GET /1.0/projects/<n>)
                          Must contain 'name', 'description', 'config'.

        Returns:
            tuple: (Tenant, created: bool)
        """
        project_name = project_data.get('name', '')
        description = project_data.get('description', '')
        config = project_data.get('config', {})

        if not project_name:
            self.log('warning', '  Skipping project with empty name')
            return None, False

        # Build the tenant slug: "incus-<project_name>"
        tenant_slug = f'incus-{project_name}'

        # Extract feature flags
        features = {}
        for feature_key in PROJECT_FEATURES:
            raw = config.get(feature_key, 'false')
            features[feature_key] = raw.lower() == 'true'

        # Build description
        tenant_description = f'Incus project: {project_name}'
        if description:
            tenant_description += f' — {description}'

        # Feature summary for description
        isolated = [k.replace('features.', '') for k, v in features.items() if v]
        if isolated:
            tenant_description += f' [isolated: {", ".join(isolated)}]'

        # Create or update Tenant
        tenant, created = Tenant.objects.get_or_create(
            slug=tenant_slug,
            defaults={
                'name': f'Incus: {project_name}',
                'group': self.tenant_group,
                'description': tenant_description,
            }
        )

        updated = False
        if not created:
            if tenant.description != tenant_description:
                tenant.description = tenant_description
                updated = True
            if tenant.group != self.tenant_group:
                tenant.group = self.tenant_group
                updated = True

        # Store features in custom_field_data
        if tenant.custom_field_data.get('incus_project_features') != features:
            tenant.custom_field_data['incus_project_features'] = features
            updated = True

        # Store raw project config for reference
        if tenant.custom_field_data.get('incus_project_name') != project_name:
            tenant.custom_field_data['incus_project_name'] = project_name
            updated = True

        if created or updated:
            tenant.save()

        # Ensure managed tag
        if self.managed_tag not in tenant.tags.all():
            tenant.tags.add(self.managed_tag)

        if created:
            self.log('info', f'  Tenant created: {tenant.name} (features: {features})')
        elif updated:
            self.log('info', f'  Tenant updated: {tenant.name}')
        else:
            self.log('debug', f'  Tenant unchanged: {tenant.name}')

        return tenant, created

    def sync_all_projects(self, projects_data):
        """
        Synchronizes all Incus projects to NetBox Tenants.

        Args:
            projects_data: list of project dicts from Incus API

        Returns:
            dict: {
                'tenants_created': int,
                'tenants_updated': int,
                'tenants_removed': int,
                'tenant_map': dict  # project_name → Tenant
            }
        """
        stats = {
            'tenants_created': 0,
            'tenants_updated': 0,
            'tenants_removed': 0,
            'tenant_map': {},
        }

        project_names = set()

        for project_data in projects_data:
            project_name = project_data.get('name', '')
            if not project_name:
                continue

            project_names.add(project_name)
            tenant, created = self.sync_project_as_tenant(project_data)

            if tenant:
                stats['tenant_map'][project_name] = tenant
                if created:
                    stats['tenants_created'] += 1

        # Clean up tenants for deleted projects
        removed = self._cleanup_stale_tenants(project_names)
        stats['tenants_removed'] = removed

        self.log('info',
            f"  Projects sync: {stats['tenants_created']} created, "
            f"{stats['tenants_removed']} removed, "
            f"{len(stats['tenant_map'])} total"
        )

        return stats

    def get_project_features(self, tenant):
        """
        Returns the feature flags for a project tenant.

        Args:
            tenant: NetBox Tenant instance

        Returns:
            dict: Feature flags, e.g. {'features.profiles': True, ...}
                  Returns all-False if no features stored.
        """
        return tenant.custom_field_data.get('incus_project_features', {
            feature: False for feature in PROJECT_FEATURES
        })

    # ========== Internal ==========

    def _cleanup_stale_tenants(self, active_project_names):
        """
        Removes tenants for projects that no longer exist in Incus.

        Args:
            active_project_names: set of current project names

        Returns:
            int: Number of tenants removed
        """
        removed = 0

        # Find all tenants in our group that are tagged as managed
        managed_tenants = Tenant.objects.filter(
            group=self.tenant_group,
            tags=self.managed_tag,
        )

        for tenant in managed_tenants:
            project_name = tenant.custom_field_data.get('incus_project_name', '')
            if project_name and project_name not in active_project_names:
                self.log('warning', f'  Removing stale tenant: {tenant.name} (project {project_name} no longer exists)')
                tenant.delete()
                removed += 1

        return removed