"""
Utility functions for Incus synchronization.
"""

from extras.models import Tag

TAG_COLORS = {
    "container": "blue",
    "virtual-machine": "purple",
    "incus-managed": "green",
}

TAGS_DEFINITION = [
    ("incus-container", "Incus Container", TAG_COLORS["container"]),
    ("incus-vm", "Incus Virtual Machine", TAG_COLORS["virtual-machine"]),
    ("incus-managed", "Managed by Incus Sync", TAG_COLORS["incus-managed"]),
]

# Config keys to exclude from sanitized output
EXCLUDE_CONFIG_PREFIXES = [
    "volatile.",
    "image.",
]

EXCLUDE_CONFIG_EXACT = [
    "user.password",
    "user.access_key",
    "user.secret_key",
]


def ensure_tags_exist(logger=None):
    """Creates necessary tags if they don't exist."""
    tags = {}
    for slug, name, color in TAGS_DEFINITION:
        tag, created = Tag.objects.get_or_create(
            slug=slug, defaults={"name": name, "color": color}
        )
        tags[slug] = tag
        if created and logger:
            logger.info(f"  Tag created: {name}")
    return tags


def parse_memory(value):
    """Converts an Incus memory value to MB."""
    if not value:
        return None
    try:
        value = str(value).upper().strip()

        if value.endswith("GIB"):
            return int(float(value[:-3]) * 1024)
        elif value.endswith("GB"):
            return int(float(value[:-2]) * 1024)
        elif value.endswith("MIB"):
            return int(float(value[:-3]))
        elif value.endswith("MB"):
            return int(float(value[:-2]))
        elif value.endswith("KIB"):
            return int(float(value[:-3]) / 1024)
        elif value.endswith("KB"):
            return int(float(value[:-2]) / 1024)
        else:
            return int(int(value) / (1024 * 1024))
    except (ValueError, TypeError):
        return None


def parse_size(value):
    """Converts an Incus disk size to MB (alias for parse_memory)."""
    return parse_memory(value)


def get_instance_type_tag(instance_type):
    """Returns the tag slug corresponding to the instance type."""
    if instance_type == "container":
        return "incus-container"
    return "incus-vm"


# ========== Shared sanitization/extraction helpers ==========


def sanitize_config(config):
    """
    Sanitizes Incus configuration by removing sensitive or volatile data.

    Args:
        config: Raw Incus config dict

    Returns:
        dict: Sanitized config
    """
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


def sanitize_devices(devices):
    """
    Sanitizes Incus devices configuration by removing user.* keys.

    Args:
        devices: Raw Incus devices dict

    Returns:
        dict: Sanitized devices
    """
    if not devices:
        return {}

    sanitized = {}
    for name, device in devices.items():
        sanitized_device = {
            key: value for key, value in device.items() if not key.startswith("user.")
        }
        sanitized[name] = sanitized_device

    return sanitized


def extract_limits(config):
    """Extracts resource limits from an Incus config dict."""
    limits = {}

    if config.get("limits.cpu"):
        limits["cpu"] = config["limits.cpu"]
    if config.get("limits.memory"):
        limits["memory"] = config["limits.memory"]

    for key in [
        "limits.disk.priority",
        "limits.disk.read",
        "limits.disk.write",
        "limits.network.priority",
        "limits.network.egress",
        "limits.network.ingress",
        "limits.processes",
    ]:
        if key in config:
            limits[key.replace("limits.", "")] = config[key]

    return limits if limits else None


def extract_security(config):
    """Extracts security-related settings from an Incus config dict."""
    security = {}
    security_keys = [
        "security.nesting",
        "security.privileged",
        "security.protection.delete",
        "security.protection.shift",
        "security.idmap.isolated",
        "security.secureboot",
        "security.devlxd",
        "security.devlxd.images",
    ]

    for key in security_keys:
        if key in config:
            short_key = key.replace("security.", "")
            value = config[key]
            if value in ("true", "false"):
                value = value == "true"
            security[short_key] = value

    return security if security else None
