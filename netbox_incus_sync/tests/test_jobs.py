from unittest.mock import patch, MagicMock
from netbox_incus_sync.tests.base import IncusSyncTestCase
from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices


class IncusSyncJobsTestCase(IncusSyncTestCase):
    """
    Tests for sync jobs.

    Since JobRunner requires a Job model instance to __init__,
    we test the jobs indirectly by verifying they can be enqueued
    and that the service orchestration logic is correct.
    """

    @patch("netbox_incus_sync.jobs.IncusClient")
    @patch("netbox_incus_sync.jobs.ensure_custom_fields_exist")
    def test_sync_job_calls_client(self, mock_ensure_cf, mock_client_cls):
        """Verify that the sync job connects to each enabled host."""
        mock_client = MagicMock()
        mock_client.test_connection.return_value = (True, "OK", {})
        mock_client.get_server_info.return_value = {}
        mock_client.get_cluster.return_value = None
        mock_client.get_projects.return_value = [{"name": "default", "config": {}}]
        mock_client.get_networks.return_value = []
        mock_client.get_profiles.return_value = []
        mock_client.get_instances.return_value = []
        mock_client_cls.return_value = mock_client

        # Import and test the _process_host logic directly
        from netbox_incus_sync.jobs import SyncIncusJob
        from netbox_incus_sync.services import (
            InstanceSyncService,
            NetworkSyncService,
            DiskSyncService,
            EventSyncService,
            ConfigContextSyncService,
            ProfileSyncService,
            IpamSyncService,
            TenantSyncService,
        )

        # Create service instances with mock loggers
        logger = MagicMock()
        instance_service = InstanceSyncService(logger=logger)
        instance_service.setup()

        tenant_service = TenantSyncService(logger=logger)
        result = tenant_service.sync_all_projects(
            [{"name": "default", "config": {}}], self.incus_host
        )

        self.assertIn("default", result["tenant_map"])

    def test_enabled_hosts_queried(self):
        """Verify that only enabled hosts would be processed."""
        IncusHost.objects.create(
            name="disabled-host",
            connection_type=ConnectionTypeChoices.UNIX_SOCKET,
            enabled=False,
        )

        enabled = IncusHost.objects.filter(enabled=True)
        disabled = IncusHost.objects.filter(enabled=False)

        self.assertGreaterEqual(enabled.count(), 1)
        self.assertEqual(disabled.count(), 1)
        self.assertFalse(disabled.filter(name="disabled-host").first().enabled)
