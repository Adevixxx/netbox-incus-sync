"""
Fonctions utilitaires pour la synchronisation Incus.
"""

from extras.models import Tag


# Couleurs des tags NetBox
TAG_COLORS = {
    'container': 'blue',
    'virtual-machine': 'purple',
    'incus-managed': 'green',
}

# Définition des tags
TAGS_DEFINITION = [
    ('incus-container', 'Incus Container', TAG_COLORS['container']),
    ('incus-vm', 'Incus Virtual Machine', TAG_COLORS['virtual-machine']),
    ('incus-managed', 'Managed by Incus Sync', TAG_COLORS['incus-managed']),
]


def ensure_tags_exist(logger=None):
    """
    Crée les tags nécessaires s'ils n'existent pas.
    
    Args:
        logger: Logger optionnel pour les messages
    
    Returns:
        dict: Les tags créés/récupérés par slug
    """
    tags = {}
    for slug, name, color in TAGS_DEFINITION:
        tag, created = Tag.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'color': color}
        )
        tags[slug] = tag
        if created and logger:
            logger.info(f"  Tag créé: {name}")
    return tags


def parse_memory(value):
    """
    Convertit une valeur mémoire Incus en MB.
    
    Supporte: GiB, GB, MiB, MB, KiB, KB, bytes
    
    Args:
        value: Valeur mémoire (str ou int)
    
    Returns:
        int: Valeur en MB ou None
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
        # Bytes (nombre seul)
        else:
            return int(int(value) / (1024 * 1024))
    except (ValueError, TypeError):
        return None


def parse_size(value):
    """
    Convertit une taille de disque Incus en MB.
    Alias pour parse_memory car même logique.
    """
    return parse_memory(value)


def get_instance_type_tag(instance_type):
    """
    Retourne le slug du tag correspondant au type d'instance.
    
    Args:
        instance_type: 'container' ou 'virtual-machine'
    
    Returns:
        str: Slug du tag
    """
    if instance_type == 'container':
        return 'incus-container'
    return 'incus-vm'