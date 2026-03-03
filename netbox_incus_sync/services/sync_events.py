"""
Incus log synchronization service to NetBox Journal Entries.

Fetches instance log files via the Incus API and stores them
as Journal Entries on the corresponding VirtualMachine.

At each sync, previous log entries are deleted and replaced with fresh ones.
"""

from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from extras.models import JournalEntry
from extras.choices import JournalEntryKindChoices
from virtualization.models import VirtualMachine

# Prefix used to identify journal entries created by this service
JOURNAL_PREFIX = "[Incus Logs]"


class EventSyncService:
    """Service to synchronize Incus instance logs to NetBox Journal Entries."""

    def __init__(self, logger=None):
        self.logger = logger
        self._vm_content_type = None

    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)

    @property
    def vm_content_type(self):
        if self._vm_content_type is None:
            self._vm_content_type = ContentType.objects.get_for_model(VirtualMachine)
        return self._vm_content_type

    def sync_events(self, host, client):
        """
        Synchronizes instance log files from an Incus host as Journal Entries.

        For each VM managed by this host, fetches available log files and
        stores their content as journal entries. Previous log entries from
        this service are deleted first (replace strategy).

        Args:
            host: IncusHost instance
            client: IncusClient instance

        Returns:
            int: Number of log entries created
        """
        logs_synced = 0

        managed_vms = VirtualMachine.objects.filter(
            custom_field_data__incus_host=host.name
        )

        if not managed_vms.exists():
            self.log("debug", f"  No managed VMs found for host {host.name}")
            return 0

        self.log("debug", f"  Scanning logs for {managed_vms.count()} instances...")

        for vm in managed_vms:
            count = self._sync_instance_logs(vm, host, client)
            logs_synced += count

        self.log(
            "info",
            f"  Logs: {logs_synced} journal entries synced "
            f"for {managed_vms.count()} instances",
        )

        return logs_synced

    def _sync_instance_logs(self, vm, host, client):
        """
        Fetches and stores log files for a single instance.

        Uses get_instance_logs() to discover available log files dynamically,
        then fetches each one and stores it as a journal entry.
        Deletes all previous log journal entries for this VM first.

        Args:
            vm: VirtualMachine instance
            host: IncusHost instance
            client: IncusClient instance

        Returns:
            int: Number of journal entries created
        """
        log_files = client.get_instance_logs(vm.name)

        if not log_files:
            self.log("debug", f"    {vm.name}: no log files available")
            return 0

        self._delete_old_log_entries(vm)

        entries_created = 0

        for log_file in log_files:
            content = client.get_instance_log_content(vm.name, log_file)

            if not content or not content.strip():
                self.log("debug", f"    {vm.name}/{log_file}: empty")
                continue

            self._create_log_journal_entry(vm, host, log_file, content)
            entries_created += 1
            self.log(
                "debug", f"    Journal: {vm.name} - {log_file} ({len(content)} bytes)"
            )

        return entries_created

    def _delete_old_log_entries(self, vm):
        """Deletes all previous log journal entries created by this service for a VM."""
        deleted_count, _ = JournalEntry.objects.filter(
            assigned_object_type=self.vm_content_type,
            assigned_object_id=vm.pk,
            comments__startswith=JOURNAL_PREFIX,
        ).delete()

        if deleted_count:
            self.log(
                "debug", f"    Deleted {deleted_count} old log entries for {vm.name}"
            )

    def _create_log_journal_entry(self, vm, host, log_file, content):
        """
        Creates a Journal Entry containing the log file content.

        Args:
            vm: VirtualMachine instance
            host: IncusHost instance
            log_file: Log filename (e.g. 'lxc.log')
            content: Log file text content
        """
        MAX_CONTENT_LENGTH = 10000
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[-MAX_CONTENT_LENGTH:]
            content = (
                f"[... truncated to last {MAX_CONTENT_LENGTH} chars ...]\n{content}"
            )

        comments = (
            f"{JOURNAL_PREFIX}\n" f"## {log_file}\n" f"---\n" f"```\n{content}\n```"
        )

        JournalEntry.objects.create(
            assigned_object_type=self.vm_content_type,
            assigned_object_id=vm.pk,
            kind=JournalEntryKindChoices.KIND_INFO,
            comments=comments,
        )
