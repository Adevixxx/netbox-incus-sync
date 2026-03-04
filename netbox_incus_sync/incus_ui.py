"""
Incus UI URL builder.

Generates links to the Incus web UI for various object types.
URL patterns are defined in default_settings and overridable via PLUGINS_CONFIG.

Default Incus UI paths:
    - Instance:     /ui/project/{project}/instance/{name}
    - Profile:      /ui/project/{project}/profile/{name}
    - Network:      /ui/project/{project}/network/{name}
    - Storage Pool: /ui/project/{project}/storage/pool/{name}
    - Storage Vol:  /ui/project/{project}/storage/pool/{pool}/volumes/custom/{name}
    - Project:      /ui/project/{name}
"""

from django.conf import settings

DEFAULT_URL_PATTERNS = {
    "instance": "{base_url}/ui/project/{project}/instance/{name}",
    "profile": "{base_url}/ui/project/{project}/profile/{name}",
    "network": "{base_url}/ui/project/{project}/network/{name}",
    "storage_pool": "{base_url}/ui/project/{project}/storage/pool/{name}",
    "storage_volume": "{base_url}/ui/project/{project}/storage/pool/{pool}/volumes/custom/{name}",
    "project": "{base_url}/ui/project/{name}",
}


def get_url_patterns():
    """Retourne les patterns en mergeant defaults + overrides de PLUGINS_CONFIG."""
    plugin_config = getattr(settings, "PLUGINS_CONFIG", {}).get("netbox_incus_sync", {})
    overrides = plugin_config.get("incus_ui_url_patterns", {})
    patterns = DEFAULT_URL_PATTERNS.copy()
    patterns.update(overrides)
    return patterns


def build_incus_ui_url(host, object_type, name, project=None, pool=None):
    """
    Construit l'URL complète vers l'UI Incus pour un objet donné.

    Args:
        host: IncusHost instance (doit avoir incus_ui_base_url)
        object_type: 'instance', 'profile', 'network', 'storage_pool', 'storage_volume', 'project'
        name: Nom de l'objet dans Incus
        project: Nom du projet Incus (défaut: 'default')
        pool: Nom du storage pool (requis pour 'storage_volume')

    Returns:
        str ou None si base_url pas configuré
    """
    base_url = getattr(host, "incus_ui_base_url", "") or ""
    base_url = base_url.rstrip("/")
    if not base_url:
        return None

    patterns = get_url_patterns()
    pattern = patterns.get(object_type)
    if not pattern:
        return None

    if project is None:
        project = "default"

    try:
        url = pattern.format(
            base_url=base_url, name=name, project=project, pool=pool or ""
        )
    except (KeyError, IndexError):
        return None

    return url


def get_instance_ui_url(host, instance_name, project=None):
    return build_incus_ui_url(host, "instance", instance_name, project=project)


def get_profile_ui_url(host, profile_name, project=None):
    return build_incus_ui_url(host, "profile", profile_name, project=project)


def get_network_ui_url(host, network_name, project=None):
    return build_incus_ui_url(host, "network", network_name, project=project)


def get_storage_pool_ui_url(host, pool_name, project=None):
    return build_incus_ui_url(host, "storage_pool", pool_name, project=project)


def get_storage_volume_ui_url(host, volume_name, pool_name, project=None):
    return build_incus_ui_url(
        host, "storage_volume", volume_name, project=project, pool=pool_name
    )


def get_project_ui_url(host, project_name):
    return build_incus_ui_url(host, "project", project_name)
