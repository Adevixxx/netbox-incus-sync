"""
Gestion des Custom Fields pour le plugin Incus Sync.

Ce module crée et gère les Custom Fields nécessaires au plugin.
"""

from django.contrib.contenttypes.models import ContentType
from extras.models import CustomField
from extras.choices import CustomFieldTypeChoices, CustomFieldUIVisibleChoices, CustomFieldUIEditableChoices


# Définition des Custom Fields du plugin
CUSTOM_FIELDS = [
    {
        'name': 'incus_bridge',
        'label': 'Incus Bridge',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Bridge ou réseau Incus auquel cette interface est connectée',
        'object_types': ['virtualization.vminterface'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.YES,
        'is_cloneable': True,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_host_interface',
        'label': 'Host Interface',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Interface veth côté hôte Incus',
        'object_types': ['virtualization.vminterface'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_nic_type',
        'label': 'NIC Type',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Type de NIC Incus (bridged, macvlan, etc.)',
        'object_types': ['virtualization.vminterface'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': True,
        'group_name': 'Incus',
    },
]


def ensure_custom_fields_exist(logger=None):
    """
    Crée les Custom Fields nécessaires s'ils n'existent pas.
    
    Args:
        logger: Logger optionnel pour les messages
    
    Returns:
        dict: Les Custom Fields créés/récupérés par nom
    """
    custom_fields = {}
    
    for cf_def in CUSTOM_FIELDS:
        cf_name = cf_def['name']
        
        # Vérifier si le Custom Field existe déjà
        try:
            cf = CustomField.objects.get(name=cf_name)
            custom_fields[cf_name] = cf
            continue
        except CustomField.DoesNotExist:
            pass
        
        # Récupérer les ContentTypes pour object_types
        object_types = []
        for ct_string in cf_def['object_types']:
            app_label, model = ct_string.split('.')
            try:
                ct = ContentType.objects.get(app_label=app_label, model=model)
                object_types.append(ct)
            except ContentType.DoesNotExist:
                if logger:
                    logger.warning(f"ContentType {ct_string} non trouvé")
                continue
        
        if not object_types:
            continue
        
        # Créer le Custom Field
        cf = CustomField.objects.create(
            name=cf_name,
            label=cf_def.get('label', cf_name),
            type=cf_def['type'],
            description=cf_def.get('description', ''),
            ui_visible=cf_def.get('ui_visible', CustomFieldUIVisibleChoices.ALWAYS),
            ui_editable=cf_def.get('ui_editable', CustomFieldUIEditableChoices.YES),
            is_cloneable=cf_def.get('is_cloneable', True),
            group_name=cf_def.get('group_name', ''),
        )
        
        # Associer les object_types (ManyToMany)
        cf.object_types.set(object_types)
        
        custom_fields[cf_name] = cf
        
        if logger:
            logger.info(f"  Custom Field créé: {cf_def.get('label', cf_name)}")
    
    return custom_fields


def get_custom_field(name):
    """
    Récupère un Custom Field par son nom.
    
    Args:
        name: Nom du Custom Field
    
    Returns:
        CustomField ou None
    """
    try:
        return CustomField.objects.get(name=name)
    except CustomField.DoesNotExist:
        return None