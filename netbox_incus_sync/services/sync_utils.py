"""
Utility functions for Incus synchronization.
"""

from extras.models import Tag


# NetBox Tag colors
TAG_COLORS = {
    'container': 'blue',
    'virtual-machine': 'purple',
    'incus-managed': 'green',
}

# Tag Definitions
TAGS_DEFINITION = [
    ('incus-container', 'Incus Container', TAG_COLORS['container']),
    ('incus-vm', 'Incus Virtual Machine', TAG_COLORS['virtual-machine']),
    ('incus-managed', 'Managed by Incus Sync', TAG_COLORS['incus-managed']),
]


def ensure_tags_exist(logger=None):
    """
    Creates necessary tags if they don't exist.
    
    Args:
        logger: Optional logger for messages
    
    Returns:
        dict: Created/Retrieved tags by slug
    """
    tags = {}
    for slug, name, color in TAGS_DEFINITION:
        tag, created = Tag.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'color': color}
        )
        tags[slug] = tag
        if created and logger:
            logger.info(f"  Tag created: {name}")
    return tags


def parse_memory(value):
    """
    Converts an Incus memory value to MB.
    
    Supports: GiB, GB, MiB, MB, KiB, KB, bytes
    
    Args:
        value: Memory value (str or int)
    
    Returns:
        int: Value in MB or None
    """
    if not value:
        return None
    try:
        value = str(value).upper().strip()
        
        # Gibibytes
        if value.endswith('GIB'):
            return int(float(value[:-3]) * 1024)
        # Gigabytes
        elif value.endswith('GB'):
            return int(float(value[:-2]) * 1024)
        # Mebibytes
        elif value.endswith('MIB'):
            return int(float(value[:-3]))
        # Megabytes
        elif value.endswith('MB'):
            return int(float(value[:-2]))
        # Kibibytes
        elif value.endswith('KIB'):
            return int(float(value[:-3]) / 1024)
        # Kilobytes
        elif value.endswith('KB'):
            return int(float(value[:-2]) / 1024)
        # Bytes (number only)
        else:
            return int(int(value) / (1024 * 1024))
    except (ValueError, TypeError):
        return None


def parse_size(value):
    """
    Converts an Incus disk size to MB.
    Alias for parse_memory as logic is the same.
    """
    return parse_memory(value)


def get_instance_type_tag(instance_type):
    """
    Returns the tag slug corresponding to the instance type.
    
    Args:
        instance_type: 'container' or 'virtual-machine'
    
    Returns:
        str: Tag Slug
    """
    if instance_type == 'container':
        return 'incus-container'
    return 'incus-vm'