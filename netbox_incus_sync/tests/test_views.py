from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices

User = get_user_model()


class IncusHostViewTestCase(TestCase):
    """View tests using plain Django TestCase to avoid user conflicts
    with utilities.testing.TestCase which auto-creates 'testuser'."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username="viewtestuser", email="test@example.com", password="password"
        )
        cls.incus_host = IncusHost.objects.create(
            name="view-test-host",
            connection_type=ConnectionTypeChoices.UNIX_SOCKET,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_incushost_list_view(self):
        url = reverse("plugins:netbox_incus_sync:incushost_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_incushost_detail_view(self):
        url = reverse(
            "plugins:netbox_incus_sync:incushost", kwargs={"pk": self.incus_host.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_incushost_add_view(self):
        url = reverse("plugins:netbox_incus_sync:incushost_add")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_incushost_edit_view(self):
        url = reverse(
            "plugins:netbox_incus_sync:incushost_edit",
            kwargs={"pk": self.incus_host.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_incushost_delete_view(self):
        url = reverse(
            "plugins:netbox_incus_sync:incushost_delete",
            kwargs={"pk": self.incus_host.pk},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_incushost_clear_cache_view(self):
        self.incus_host.update_working_url("https://working.local")
        url = reverse(
            "plugins:netbox_incus_sync:incushost_clear_cache",
            kwargs={"pk": self.incus_host.pk},
        )
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.incus_host.refresh_from_db()
        self.assertEqual(self.incus_host.last_working_url, "")

    def test_sync_host_redirects(self):
        url = reverse(
            "plugins:netbox_incus_sync:sync_host", kwargs={"pk": self.incus_host.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_sync_all_redirects(self):
        url = reverse("plugins:netbox_incus_sync:sync")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
