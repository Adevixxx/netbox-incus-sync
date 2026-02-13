"""
Custom Fields management for the Incus Sync plugin.

This module creates and manages necessary Custom Fields for the plugin.
These fields store Incus metadata that have no native equivalent in NetBox.
"""

from django.contrib.contenttypes.models import ContentType
from extras.models import CustomField
from extras.choices import CustomFieldTypeChoices, CustomFieldUIVisibleChoices, CustomFieldUIEditableChoices


# Plugin Custom Fields definition
# Only Create fields that have NO native equivalent in NetBox
CUSTOM_FIELDS = [
    # ========== Custom Fields for VMInterface ==========
    {
        'name': 'incus_bridge',
        'label': 'Incus Bridge',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Incus Bridge or network this interface is connected to',
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
        'description': 'Host-side veth interface',
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
        'description': 'Incus NIC type (bridged, macvlan, etc.)',
        'object_types': ['virtualization.vminterface'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': True,
        'group_name': 'Incus',
    },
    # ========== Custom Fields for VirtualDisk ==========
    {
        'name': 'incus_mount_path',
        'label': 'Mount Path',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Disk mount point in container/VM',
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
        'description': 'Incus storage pool containing this disk',
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
        'description': 'Incus source volume name (for additional volumes)',
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
        'description': 'Disk type (root, data, etc.)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    {
        'name': 'incus_storage_driver',
        'label': 'Storage Driver',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Storage driver type (zfs, btrfs, lvm, dir, ceph, etc.)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    # ========== Disk Usage Statistics ==========
    {
        'name': 'incus_disk_used',
        'label': 'Used Space (MB)',
        'type': CustomFieldTypeChoices.TYPE_INTEGER,
        'description': 'Actual disk space used in MB',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus Usage',
    },
    {
        'name': 'incus_disk_total',
        'label': 'Total Space (MB)',
        'type': CustomFieldTypeChoices.TYPE_INTEGER,
        'description': 'Total available disk space in MB (if reported by driver)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus Usage',
    },
    {
        'name': 'incus_disk_usage_percent',
        'label': 'Usage %',
        'type': CustomFieldTypeChoices.TYPE_DECIMAL,
        'description': 'Disk usage percentage (0-100)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus Usage',
    },
    {
        'name': 'incus_disk_content_type',
        'label': 'Content Type',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Volume content type (filesystem or block)',
        'object_types': ['virtualization.virtualdisk'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus Usage',
    },
    # ========== Custom Fields for VirtualMachine ==========
    {
        'name': 'incus_host',
        'label': 'Incus Host',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Source Incus Host name',
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
        'description': 'Incus Instance Type (container or virtual-machine)',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.ALWAYS,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
        'choice_set_choices': ['container', 'virtual-machine'],
    },
    {
        'name': 'incus_image',
        'label': 'Image',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Source image or template of the instance',
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
        'description': 'Instance creation date in Incus',
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
        'description': 'Last synchronization date',
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
        'description': 'Incus Profiles applied to the instance',
        'object_types': ['virtualization.virtualmachine'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
    # ========== Custom Fields for VMInterface (Incus Networks) ==========
    {
        'name': 'incus_device_name',
        'label': 'Incus Device Name',
        'type': CustomFieldTypeChoices.TYPE_TEXT,
        'description': 'Incus device name (e.g. "lan", "mgmt") — may differ from guest interface name (eth0)',
        'object_types': ['virtualization.vminterface'],
        'ui_visible': CustomFieldUIVisibleChoices.IF_SET,
        'ui_editable': CustomFieldUIEditableChoices.HIDDEN,
        'is_cloneable': False,
        'group_name': 'Incus',
    },
]


def ensure_custom_fields_exist(logger=None):
    """
    Creates necessary Custom Fields if they don't exist.
    
    Args:
        logger: Optional logger for messages
    
    Returns:
        dict: Created/Retrieved Custom Fields by name
    """
    custom_fields = {}
    
    for cf_def in CUSTOM_FIELDS:
        cf_name = cf_def['name']
        
        # Check if Custom Field already exists
        try:
            cf = CustomField.objects.get(name=cf_name)
            custom_fields[cf_name] = cf
            continue
        except CustomField.DoesNotExist:
            pass
        
        # Retrieve ContentTypes for object_types
        object_types = []
        for ct_string in cf_def['object_types']:
            app_label, model = ct_string.split('.')
            try:
                ct = ContentType.objects.get(app_label=app_label, model=model)
                object_types.append(ct)
            except ContentType.DoesNotExist:
                if logger:
                    logger.warning(f"ContentType {ct_string} not found")
                continue
        
        if not object_types:
            continue
        
        # Prepare creation parameters
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
        
        # Create Custom Field
        cf = CustomField.objects.create(**create_params)
        
        # Associate object_types (ManyToMany)
        cf.object_types.set(object_types)
        
        # For SELECT fields, create choices via CustomFieldChoiceSet
        if cf_def['type'] == CustomFieldTypeChoices.TYPE_SELECT and 'choice_set_choices' in cf_def:
            _create_choice_set(cf, cf_def['choice_set_choices'], logger)
        
        custom_fields[cf_name] = cf
        
        if logger:
            logger.info(f"  Custom Field created: {cf_def.get('label', cf_name)}")
    
    return custom_fields


def _create_choice_set(custom_field, choices, logger=None):
    """
    Creates a CustomFieldChoiceSet for a SELECT field.
    
    Args:
        custom_field: CustomField instance
        choices: List of choices
        logger: Optional logger
    """
    from extras.models import CustomFieldChoiceSet
    
    choice_set_name = f"{custom_field.name}_choices"
    
    try:
        choice_set = CustomFieldChoiceSet.objects.get(name=choice_set_name)
    except CustomFieldChoiceSet.DoesNotExist:
        # Format choices as expected by NetBox: list of tuples (value, label)
        extra_choices = [[choice, choice] for choice in choices]
        
        choice_set = CustomFieldChoiceSet.objects.create(
            name=choice_set_name,
            extra_choices=extra_choices,
        )
        if logger:
            logger.info(f"    ChoiceSet created: {choice_set_name}")
    
    # Associate choice_set to custom field
    custom_field.choice_set = choice_set
    custom_field.save()


def get_custom_field(name):
    """
    Retrieves a Custom Field by its name.
    
    Args:
        name: Custom Field Name
    
    Returns:
        CustomField or None
    """
    try:
        return CustomField.objects.get(name=name)
    except CustomField.DoesNotExist:
        return None