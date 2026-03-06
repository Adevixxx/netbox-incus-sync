"""
Incus UI URL builder.

Generates links to the Incus web UI for various object types.
URL patterns are configurable per-host via individual CharField fields.
Falls back to default Incus UI paths when no custom template is set.
"""

DEFAULT_PATTERNS = {
    "instance": "{host}/ui/project/{project}/instance/{name}",
    "profile": "{host}/ui/project/{project}/profile/{name}",
    "network": "{host}/ui/project/{project}/network/{name}",
    "storage_pool": "{host}/ui/project/{project}/storage/pool/{name}",
    "storage_volume": "{host}/ui/project/{project}/storage/pool/{pool}/volumes/custom/{name}",
    "project": "{host}/ui/project/{name}",
}

FIELD_MAP = {
    "instance": "incus_ui_instance_url",
    "profile": "incus_ui_profile_url",
    "network": "incus_ui_network_url",
    "storage_pool": "incus_ui_storage_pool_url",
    "storage_volume": "incus_ui_storage_volume_url",
    "project": "incus_ui_project_url",
}


def build_incus_ui_url(host, object_type, name, project=None, pool=None):
    """
    Constructs the URL to the Incus UI for a given object.

    Args:
        host: IncusHost instance
        object_type: 'instance', 'profile', 'network', 'storage_pool', 'storage_volume', 'project'
        name: Object name in Incus
        project: Incus project name (default: 'default')
        pool: Storage pool name (required for 'storage_volume')

    Returns:
        str or None if {host} cannot be resolved
    """
    host_url = host.incus_ui_host_url
    if not host_url:
        return None

    field_name = FIELD_MAP.get(object_type)
    pattern = getattr(host, field_name, "") if field_name else ""
    if not pattern:
        pattern = DEFAULT_PATTERNS.get(object_type, "")
    if not pattern:
        return None

    if project is None:
        project = "default"

    try:
        url = pattern.format(
            host=host_url,
            name=name,
            project=project,
            pool=pool or "",
        )
    except (KeyError, IndexError, ValueError):
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
