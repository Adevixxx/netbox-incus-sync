"""
Service de synchronisation des événements Incus vers NetBox Journal Entries.
"""

from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from extras.models import JournalEntry
from extras.choices import JournalEntryKindChoices
from virtualization.models import VirtualMachine


# Mapping des événements Incus vers les types de Journal Entry
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

# Labels lisibles pour les événements
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
    Service pour synchroniser les événements Incus vers NetBox Journal Entries.
    """
    
    def __init__(self, logger=None):
        """
        Initialise le service.
        
        Args:
            logger: Logger pour les messages (optionnel)
        """
        self.logger = logger
        self._vm_content_type = None
    
    def log(self, level, message):
        """Log un message si logger disponible."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    @property
    def vm_content_type(self):
        """Retourne le ContentType pour VirtualMachine (cached)."""
        if self._vm_content_type is None:
            self._vm_content_type = ContentType.objects.get_for_model(VirtualMachine)
        return self._vm_content_type
    
    def sync_events(self, host, client, since_minutes=60):
        """
        Synchronise les événements récents d'un hôte Incus.
        
        Args:
            host: Instance IncusHost
            client: Client Incus connecté
            since_minutes: Récupérer les événements des N dernières minutes
        
        Returns:
            int: Nombre d'événements synchronisés
        """
        events_synced = 0
        
        # Récupérer les opérations récentes (les events lifecycle sont dans les operations)
        operations = client.get_operations()
        
        if not operations:
            self.log('info', f"  Aucune opération récente trouvée")
            return 0
        
        # Calculer le timestamp minimum
        since_time = timezone.now() - timedelta(minutes=since_minutes)
        
        self.log('info', f"  Analyse de {len(operations)} opérations...")
        
        for operation in operations:
            # Filtrer par date
            op_created = self._parse_timestamp(operation.get('created_at', ''))
            if not op_created or op_created < since_time:
                continue
            
            # Extraire les infos de l'opération
            op_class = operation.get('class', '')
            op_description = operation.get('description', '')
            op_status = operation.get('status', '')
            op_resources = operation.get('resources', {})
            
            # Ne traiter que les opérations liées aux instances
            instances = op_resources.get('instances', [])
            if not instances:
                continue
            
            # Pour chaque instance concernée
            for instance_url in instances:
                instance_name = instance_url.split('/')[-1]
                
                # Créer l'entrée de journal
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
        Synchronise les événements lifecycle via l'endpoint events (si disponible).
        
        Note: L'API /1.0/events est un stream WebSocket, pas REST.
        On utilise plutôt /1.0/operations pour l'historique.
        
        Args:
            host: Instance IncusHost
            client: Client Incus connecté  
            since_minutes: Fenêtre de temps
        
        Returns:
            int: Nombre d'événements synchronisés
        """
        # Pour l'instant, on délègue à sync_events qui utilise les operations
        return self.sync_events(host, client, since_minutes)
    
    def _create_journal_entry(self, instance_name, host, operation, op_created):
        """
        Crée une Journal Entry pour un événement.
        
        Args:
            instance_name: Nom de l'instance Incus
            host: IncusHost source
            operation: Données de l'opération Incus
            op_created: Timestamp de l'opération
        
        Returns:
            bool: True si créée, False si déjà existante ou VM non trouvée
        """
        # Trouver la VM correspondante
        vm = self._find_vm(instance_name, host)
        if not vm:
            self.log('debug', f"    VM non trouvée pour {instance_name}, skip")
            return False
        
        # Extraire les infos de l'opération
        op_id = operation.get('id', '')
        op_description = operation.get('description', '')
        op_status = operation.get('status', '')
        op_err = operation.get('err', '')
        
        # Déterminer le type d'événement depuis la description
        event_type = self._detect_event_type(op_description)
        
        # Vérifier si cette entrée existe déjà (éviter les doublons)
        if self._journal_entry_exists(vm, op_id, op_created):
            return False
        
        # Déterminer le kind de l'entrée
        if op_status == 'Failure' or op_err:
            kind = JournalEntryKindChoices.KIND_DANGER
        else:
            kind = EVENT_KIND_MAPPING.get(event_type, JournalEntryKindChoices.KIND_INFO)
        
        # Construire le commentaire
        label = EVENT_LABELS.get(event_type, op_description)
        comments = self._build_comments(label, operation, host)
        
        # Créer l'entrée
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
        Trouve la VM NetBox correspondant à une instance Incus.
        
        Args:
            instance_name: Nom de l'instance
            host: IncusHost source
        
        Returns:
            VirtualMachine ou None
        """
        # Chercher par nom et incus_host custom field
        vm = VirtualMachine.objects.filter(
            name=instance_name,
            custom_field_data__incus_host=host.name
        ).first()
        
        if vm:
            return vm
        
        # Fallback: chercher par nom seul si une seule VM existe
        vms = VirtualMachine.objects.filter(name=instance_name)
        if vms.count() == 1:
            return vms.first()
        
        return None
    
    def _detect_event_type(self, description):
        """
        Détecte le type d'événement depuis la description de l'opération.
        
        Args:
            description: Description de l'opération (ex: "Starting instance")
        
        Returns:
            str: Type d'événement (ex: "instance-started")
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
        Vérifie si une Journal Entry existe déjà pour cette opération.
        
        On utilise une combinaison de l'objet, le timestamp et l'ID d'opération
        (stocké dans le commentaire) pour éviter les doublons.
        
        Args:
            vm: VirtualMachine
            op_id: ID de l'opération Incus
            op_created: Timestamp de l'opération
        
        Returns:
            bool: True si existe déjà
        """
        # Chercher une entrée avec le même timestamp (à la seconde près)
        # et contenant l'ID d'opération dans le commentaire
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
        Construit le texte du commentaire pour la Journal Entry.
        
        Args:
            label: Label de l'événement
            operation: Données de l'opération
            host: IncusHost source
        
        Returns:
            str: Commentaire formaté (Markdown)
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
        Parse un timestamp Incus.
        
        Args:
            ts_string: Timestamp au format ISO
        
        Returns:
            datetime ou None
        """
        if not ts_string:
            return None
        
        try:
            # Format Incus: 2026-01-27T13:58:42.690298037Z
            if '.' in ts_string:
                base, frac = ts_string.split('.')
                frac_clean = frac.rstrip('Z')[:6]
                ts_string = f"{base}.{frac_clean}Z"
            
            return datetime.fromisoformat(ts_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def create_sync_journal_entry(self, vm, host, action="synced"):
        """
        Crée une Journal Entry pour marquer une synchronisation.
        
        Utile pour tracer quand une VM a été synchronisée.
        
        Args:
            vm: VirtualMachine
            host: IncusHost source
            action: Action effectuée (synced, created, updated)
        
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