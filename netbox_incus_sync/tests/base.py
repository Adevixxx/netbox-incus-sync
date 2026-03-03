from django.contrib.auth.models import User
from utilities.testing import TestCase
from dcim.models import Site
from virtualization.models import Cluster, ClusterType
from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices


class IncusSyncTestCase(TestCase):
    """
    Base test case for NetBox Incus Sync plugin.
    Provides common setup data used across most tests.
    """

    @classmethod
    def setUpTestData(cls):
        # Create common objects needed for testing
        cls.site = Site.objects.create(name="Test Site", slug="test-site")
        cls.cluster_type = ClusterType.objects.create(name="Incus", slug="incus")
        cls.cluster = Cluster.objects.create(
            name="Test Cluster",
            type=cls.cluster_type,
        )

        # Create a default Incus host
        cls.incus_host = IncusHost.objects.create(
            name="test-host",
            connection_type=ConnectionTypeChoices.UNIX_SOCKET,
            socket_path="http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket",
            default_cluster=cls.cluster,
            default_site=cls.site,
            enabled=True,
        )
