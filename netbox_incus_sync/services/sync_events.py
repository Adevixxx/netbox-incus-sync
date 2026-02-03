"""
Incus events synchronization service to NetBox Journal Entries.
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from extras.models import JournalEntry
from extras.choices import JournalEntryKindChoices
from virtualization.models import VirtualMachine


# Mapping Incus events to Journal Entry kinds
EVENT_KIND_MAPPING = {
    # Lifecycle events
    'instance-created': JournalEntryKindChoices.KIND_SUCCESS,
    'instance-started': JournalEntryKindChoices.KIND_INFO,
    'instance-stopped': JournalEntryKindChoices.KIND_WARNING,
    'instance-shutdown': JournalEntryKindChoices.KIND_WARNING,
    'instance-restarted': JournalEntryKindChoices.KIND_INFO,
    'instance-paused': JournalEntryKindChoices.KIND_WARNING,
    'instance-resumed': JournalEntryKindChoices.KIND_INFO,
    'instance-deleted': JournalEntryKindChoices.KIND_DANGER,
    'instance-renamed': JournalEntryKindChoices.KIND_INFO,
    'instance-updated': JournalEntryKindChoices.KIND_INFO,
    # Snapshot events
    'instance-snapshot-created': JournalEntryKindChoices.KIND_SUCCESS,
    'instance-snapshot-deleted': JournalEntryKindChoices.KIND_WARNING,
    'instance-snapshot-renamed': JournalEntryKindChoices.KIND_INFO,
    'instance-snapshot-restored': JournalEntryKindChoices.KIND_SUCCESS,
    # Migration events
    'instance-migrated': JournalEntryKindChoices.KIND_INFO,
    # Backup events
    'instance-backup-created': JournalEntryKindChoices.KIND_SUCCESS,
    'instance-backup-deleted': JournalEntryKindChoices.KIND_WARNING,
    'instance-backup-restored': JournalEntryKindChoices.KIND_SUCCESS,
}

# Readable labels for events
EVENT_LABELS = {
    'instance-created': 'Instance created',
    'instance-started': 'Instance started',
    'instance-stopped': 'Instance stopped',
    'instance-shutdown': 'Instance shutdown',
    'instance-restarted': 'Instance restarted',
    'instance-paused': 'Instance paused',
    'instance-resumed': 'Instance resumed',
    'instance-deleted': 'Instance deleted',
    'instance-renamed': 'Instance renamed',
    'instance-updated': 'Instance configuration updated',
    'instance-snapshot-created': 'Snapshot created',
    'instance-snapshot-deleted': 'Snapshot deleted',
    'instance-snapshot-renamed': 'Snapshot renamed',
    'instance-snapshot-restored': 'Snapshot restored',
    'instance-migrated': 'Instance migrated',
    'instance-backup-created': 'Backup created',
    'instance-backup-deleted': 'Backup deleted',
    'instance-backup-restored': 'Backup restored',
}


class EventSyncService:
    """
    Service to synchronize Incus events to NetBox Journal Entries.
    """
    
    def __init__(self, logger=None):
        """
        Initializes the service.
        
        Args:
            logger: Logger for messages (optional)
        """
        self.logger = logger
        self._vm_content_type = None
    
    def log(self, level, message):
        """Log a message if logger is available."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    @property
    def vm_content_type(self):
        """Returns ContentType for VirtualMachine (cached)."""
        if self._vm_content_type is None:
            self._vm_content_type = ContentType.objects.get_for_model(VirtualMachine)
        return self._vm_content_type
    
    def sync_events(self, host, client, since_minutes=60):
        """
        Synchronizes recent events from an Incus host.
        
        Args:
            host: IncusHost instance
            client: Connected Incus Client
            since_minutes: Retrieve events from last N minutes
        
        Returns:
            int: Number of synchronized events
        """
        events_synced = 0
        
        # Retrieve recent operations (lifecycle events are in operations)
        operations = client.get_operations()
        
        if not operations:
            self.log('info', f"  No recent operations found")
            return 0
        
        # Calculate minimum timestamp
        since_time = timezone.now() - timedelta(minutes=since_minutes)
        
        self.log('info', f"  Analyzing {len(operations)} operations...")
        
        for operation in operations:
            # Filter by date
            op_created = self._parse_timestamp(operation.get('created_at', ''))
            if not op_created or op_created < since_time:
                continue
            
            # Extract operation info
            op_class = operation.get('class', '')
            op_description = operation.get('description', '')
            op_status = operation.get('status', '')
            op_resources = operation.get('resources', {})
            
            # Process only instance-related operations
            instances = op_resources.get('instances', [])
            if not instances:
                continue
            
            # For each affected instance
            for instance_url in instances:
                instance_name = instance_url.split('/')[-1]
                
                # Create journal entry
                created = self._create_journal_entry(
                    instance_name=instance_name,
                    host=host,
                    operation=operation,
                    op_created=op_created
                )
                
                if created:
                    events_synced += 1
        
        return events_synced
    
    def sync_lifecycle_events(self, host, client, since_minutes=60):
        """
        Synchronizes lifecycle events via events endpoint (if available).
        
        Note: The /1.0/events API is a WebSocket stream, not REST.
        We use /1.0/operations for history instead.
        
        Args:
            host: IncusHost instance
            client: Connected Incus Client
            since_minutes: Time window
        
        Returns:
            int: Number of synchronized events
        """
        # For now, delegate to sync_events which uses operations
        return self.sync_events(host, client, since_minutes)
    
    def _create_journal_entry(self, instance_name, host, operation, op_created):
        """
        Creates a Journal Entry for an event.
        
        Args:
            instance_name: Incus instance name
            host: Source IncusHost
            operation: Incus operation data
            op_created: Operation timestamp
        
        Returns:
            bool: True if created, False if already existing or VM not found
        """
        # Find corresponding VM
        vm = self._find_vm(instance_name, host)
        if not vm:
            self.log('debug', f"    VM not found for {instance_name}, skip")
            return False
        
        # Extract operation info
        op_id = operation.get('id', '')
        op_description = operation.get('description', '')
        op_status = operation.get('status', '')
        op_err = operation.get('err', '')
        
        # Determine event type from description
        event_type = self._detect_event_type(op_description)
        
        # Check if this entry already exists (avoid duplicates)
        if self._journal_entry_exists(vm, op_id, op_created):
            return False
        
        # Determine entry kind
        if op_status == 'Failure' or op_err:
            kind = JournalEntryKindChoices.KIND_DANGER
        else:
            kind = EVENT_KIND_MAPPING.get(event_type, JournalEntryKindChoices.KIND_INFO)
        
        # Build comment
        label = EVENT_LABELS.get(event_type, op_description)
        comments = self._build_comments(label, operation, host)
        
        # Create entry
        JournalEntry.objects.create(
            assigned_object_type=self.vm_content_type,
            assigned_object_id=vm.pk,
            kind=kind,
            comments=comments,
            created=op_created,
        )
        
        self.log('info', f"    Journal: {instance_name} - {label}")
        return True
    
    def _find_vm(self, instance_name, host):
        """
        Finds the NetBox VM corresponding to an Incus instance.
        
        Args:
            instance_name: Instance name
            host: Source IncusHost
        
        Returns:
            VirtualMachine or None
        """
        # Search by name and incus_host custom field
        vm = VirtualMachine.objects.filter(
            name=instance_name,
            custom_field_data__incus_host=host.name
        ).first()
        
        if vm:
            return vm
        
        # Fallback: search by name alone if only one VM exists
        vms = VirtualMachine.objects.filter(name=instance_name)
        if vms.count() == 1:
            return vms.first()
        
        return None
    
    def _detect_event_type(self, description):
        """
        Detects event type from operation description.
        
        Args:
            description: Operation description (e.g., "Starting instance")
        
        Returns:
            str: Event type (e.g., "instance-started")
        """
        description_lower = description.lower()
        
        # Mapping description -> event type
        mappings = [
            ('creating instance', 'instance-created'),
            ('starting instance', 'instance-started'),
            ('stopping instance', 'instance-stopped'),
            ('shutting down', 'instance-shutdown'),
            ('restarting instance', 'instance-restarted'),
            ('pausing instance', 'instance-paused'),
            ('resuming instance', 'instance-resumed'),
            ('deleting instance', 'instance-deleted'),
            ('renaming instance', 'instance-renamed'),
            ('updating instance', 'instance-updated'),
            ('creating instance snapshot', 'instance-snapshot-created'),
            ('deleting instance snapshot', 'instance-snapshot-deleted'),
            ('renaming instance snapshot', 'instance-snapshot-renamed'),
            ('restoring instance snapshot', 'instance-snapshot-restored'),
            ('migrating instance', 'instance-migrated'),
            ('creating instance backup', 'instance-backup-created'),
            ('deleting instance backup', 'instance-backup-deleted'),
            ('restoring instance backup', 'instance-backup-restored'),
        ]
        
        for pattern, event_type in mappings:
            if pattern in description_lower:
                return event_type
        
        return 'unknown'
    
    def _journal_entry_exists(self, vm, op_id, op_created):
        """
        Checks if a Journal Entry already exists for this operation.
        
        Uses a combination of object, timestamp, and operation ID
        (stored in the comment) to avoid duplicates.
        
        Args:
            vm: VirtualMachine
            op_id: Incus operation ID
            op_created: Operation timestamp
        
        Returns:
            bool: True if already exists
        """
        # Search for an entry with the same timestamp (down to the second)
        # and containing the operation ID in the comment
        time_window_start = op_created - timedelta(seconds=1)
        time_window_end = op_created + timedelta(seconds=1)
        
        existing = JournalEntry.objects.filter(
            assigned_object_type=self.vm_content_type,
            assigned_object_id=vm.pk,
            created__gte=time_window_start,
            created__lte=time_window_end,
            comments__contains=op_id[:8] if op_id else ''
        ).exists()
        
        return existing
    
    def _build_comments(self, label, operation, host):
        """
        Builds the comment text for the Journal Entry.
        
        Args:
            label: Event label
            operation: Operation data
            host: Source IncusHost
        
        Returns:
            str: Formatted comment (Markdown)
        """
        op_id = operation.get('id', 'N/A')
        op_status = operation.get('status', 'N/A')
        op_err = operation.get('err', '')
        op_description = operation.get('description', '')
        
        lines = [
            f"**{label}**",
            "",
            f"- **Source**: Incus host `{host.name}`",
            f"- **Operation**: `{op_id[:8]}...`",
            f"- **Status**: {op_status}",
        ]
        
        if op_description and op_description != label:
            lines.append(f"- **Description**: {op_description}")
        
        if op_err:
            lines.append(f"- **Error**: {op_err}")
        
        return "\n".join(lines)
    
    def _parse_timestamp(self, ts_string):
        """
        Parses an Incus timestamp.
        
        Args:
            ts_string: ISO format timestamp
        
        Returns:
            datetime or None
        """
        if not ts_string:
            return None
        
        try:
            # Incus Format: 2026-01-27T13:58:42.690298037Z
            if '.' in ts_string:
                base, frac = ts_string.split('.')
                frac_clean = frac.rstrip('Z')[:6]
                ts_string = f"{base}.{frac_clean}Z"
            
            return datetime.fromisoformat(ts_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def create_sync_journal_entry(self, vm, host, action="synced"):
        """
        Creates a Journal Entry to mark a synchronization.
        
        Useful for tracking when a VM was synchronized.
        
        Args:
            vm: VirtualMachine
            host: Source IncusHost
            action: Action performed (synced, created, updated)
        
        Returns:
            JournalEntry
        """
        kind_map = {
            'synced': JournalEntryKindChoices.KIND_INFO,
            'created': JournalEntryKindChoices.KIND_SUCCESS,
            'updated': JournalEntryKindChoices.KIND_INFO,
            'removed': JournalEntryKindChoices.KIND_WARNING,
        }
        
        comments = f"**Instance {action}** by Incus Sync\n\n- **Host**: `{host.name}`"
        
        return JournalEntry.objects.create(
            assigned_object_type=self.vm_content_type,
            assigned_object_id=vm.pk,
            kind=kind_map.get(action, JournalEntryKindChoices.KIND_INFO),
            comments=comments,
        )