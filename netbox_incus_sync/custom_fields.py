"""
Gestion des Custom Fields pour le plugin Incus Sync.

Ce module crée et gère les Custom Fields nécessaires au plugin.
"""

from django.contrib.contenttypes.models import ContentType
from extras.models import CustomField
from extras.choices import CustomFieldTypeChoices, CustomFieldUIVisibleChoices, CustomFieldUIEditableChoices


# Définition des Custom Fields du plugin
CUSTOM_FIELDS = [
    # ========== Custom Fields pour VMInterface ==========
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
    # ========== Custom Fields pour VirtualDisk ==========
    {
        'name': 'incus_mount_path',
        'label': 'Mount Path',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Point de montage du disque dans le conteneur/VM',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_storage_pool',
        'label': 'Storage Pool',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Pool de stockage Incus contenant ce disque',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_volume_source',
        'label': 'Volume Source',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Nom du volume source Incus (pour les volumes additionnels)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_disk_type',
        'label': 'Disk Type',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Type de disque (root, data, etc.)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    # ========== Custom Fields pour VirtualMachine ==========
    {
        'name': 'incus_host',
        'label': 'Incus Host',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Nom de l\'hôte Incus source',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_type',
        'label': 'Instance Type',
        'type': CustomFieldTypeChoices.TYPE_SELECT,
        'description': 'Type d\'instance Incus',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
        'choice_set_choices': ['container', 'virtual-machine'],
    },
    {
        'name': 'incus_architecture',
        'label': 'Architecture',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Architecture CPU de l\'instance (x86_64, aarch64, etc.)',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_image',
        'label': 'Image',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Image ou template source de l\'instance',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_created',
        'label': 'Created in Incus',
        'type': CustomFieldTypeChoices.TYPE_DATETIME,
        'description': 'Date de création de l\'instance dans Incus',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_last_sync',
        'label': 'Last Sync',
        'type': CustomFieldTypeChoices.TYPE_DATETIME,
        'description': 'Date de la dernière synchronisation',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_profiles',
        'label': 'Profiles',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Profils Incus appliqués à l\'instance',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
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
        
        # Préparer les paramètres de création
        create_params = {
            'name': cf_name,
            'label': cf_def.get('label', cf_name),
            'type': cf_def['type'],
            'description': cf_def.get('description', ''),
            'ui_visible': cf_def.get('ui_visible', CustomFieldUIVisibleChoices.ALWAYS),
            'ui_editable': cf_def.get('ui_editable', CustomFieldUIEditableChoices.YES),
            'is_cloneable': cf_def.get('is_cloneable', True),
            'group_name': cf_def.get('group_name', ''),
        }
        
        # Créer le Custom Field
        cf = CustomField.objects.create(**create_params)
        
        # Associer les object_types (ManyToMany)
        cf.object_types.set(object_types)
        
        # Pour les champs SELECT, créer les choix via CustomFieldChoiceSet
        if cf_def['type'] == CustomFieldTypeChoices.TYPE_SELECT and 'choice_set_choices' in cf_def:
            _create_choice_set(cf, cf_def['choice_set_choices'], logger)
        
        custom_fields[cf_name] = cf
        
        if logger:
            logger.info(f"  Custom Field créé: {cf_def.get('label', cf_name)}")
    
    return custom_fields


def _create_choice_set(custom_field, choices, logger=None):
    """
    Crée un CustomFieldChoiceSet pour un champ SELECT.
    
    Args:
        custom_field: Instance CustomField
        choices: Liste des choix
        logger: Logger optionnel
    """
    from extras.models import CustomFieldChoiceSet
    
    choice_set_name = f"{custom_field.name}_choices"
    
    try:
        choice_set = CustomFieldChoiceSet.objects.get(name=choice_set_name)
    except CustomFieldChoiceSet.DoesNotExist:
        # Formater les choix comme attendu par NetBox: liste de tuples (value, label)
        extra_choices = [[choice, choice] for choice in choices]
        
        choice_set = CustomFieldChoiceSet.objects.create(
            name=choice_set_name,
            extra_choices=extra_choices,
        )
        if logger:
            logger.info(f"    ChoiceSet créé: {choice_set_name}")
    
    # Associer le choice_set au custom field
    custom_field.choice_set = choice_set
    custom_field.save()


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