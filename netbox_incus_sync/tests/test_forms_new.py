"""
Tests for the new forms: IncusHostFilterForm, IncusHostBulkEditForm, IncusHostImportForm.

Place this file in netbox_incus_sync/tests/test_forms_new.py
Run with: python manage.py test netbox_incus_sync.tests.test_forms_new -v2
"""

from netbox_incus_sync.forms import (
    IncusHostFilterForm,
    IncusHostBulkEditForm,
    IncusHostImportForm,
)
from netbox_incus_sync.models import IncusHost, ConnectionTypeChoices
from netbox_incus_sync.tests.base import IncusSyncTestCase


# ============================================
# FilterForm Tests
# ============================================

class IncusHostFilterFormTestCase(IncusSyncTestCase):
    """Tests for the sidebar filter form."""

    def test_empty_form_is_valid(self):
        """An empty filter form should be valid (no filters applied)."""
        form = IncusHostFilterForm(data={})
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_by_connection_type(self):
        form = IncusHostFilterForm(data={
            'connection_type': [ConnectionTypeChoices.HTTPS],
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_by_enabled(self):
        form = IncusHostFilterForm(data={'enabled': 'true'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_by_verify_ssl(self):
        form = IncusHostFilterForm(data={'verify_ssl': 'false'})
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_by_cluster(self):
        form = IncusHostFilterForm(data={
            'default_cluster_id': [self.cluster.pk],
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_by_site(self):
        form = IncusHostFilterForm(data={
            'default_site_id': [self.site.pk],
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_combined(self):
        """Multiple filters at once should be valid."""
        form = IncusHostFilterForm(data={
            'connection_type': [ConnectionTypeChoices.UNIX_SOCKET],
            'enabled': 'true',
            'default_cluster_id': [self.cluster.pk],
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_filter_with_search(self):
        form = IncusHostFilterForm(data={'q': 'prod'})
        self.assertTrue(form.is_valid(), form.errors)


# ============================================
# BulkEditForm Tests
# ============================================

class IncusHostBulkEditFormTestCase(IncusSyncTestCase):
    """Tests for the bulk edit form.

    NetBoxModelBulkEditForm requires a 'pk' field listing the objects
    to edit. We create a second host and pass both PKs in every test.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.host2 = IncusHost.objects.create(
            name='bulk-edit-host',
            connection_type=ConnectionTypeChoices.UNIX_SOCKET,
            enabled=True,
        )

    def _pk_data(self, **extra):
        """Return data dict with pk field pre-filled."""
        data = {'pk': [self.incus_host.pk, self.host2.pk]}
        data.update(extra)
        return data

    def test_empty_form_is_valid(self):
        """A bulk edit form with only PKs is valid (nothing to change)."""
        form = IncusHostBulkEditForm(data=self._pk_data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_enabled(self):
        """Changing enabled in bulk."""
        form = IncusHostBulkEditForm(data=self._pk_data(enabled='true'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_connection_type(self):
        form = IncusHostBulkEditForm(data=self._pk_data(
            connection_type=ConnectionTypeChoices.HTTPS,
        ))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_cluster(self):
        form = IncusHostBulkEditForm(data=self._pk_data(
            default_cluster=self.cluster.pk,
        ))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_site(self):
        form = IncusHostBulkEditForm(data=self._pk_data(
            default_site=self.site.pk,
        ))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_url_cache_ttl(self):
        form = IncusHostBulkEditForm(data=self._pk_data(url_cache_ttl=600))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_verify_ssl(self):
        form = IncusHostBulkEditForm(data=self._pk_data(verify_ssl='false'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_multiple_fields(self):
        """Changing several fields at once."""
        form = IncusHostBulkEditForm(data=self._pk_data(
            enabled='true',
            verify_ssl='true',
            url_cache_ttl=120,
            default_cluster=self.cluster.pk,
            default_site=self.site.pk,
        ))
        self.assertTrue(form.is_valid(), form.errors)

    def test_bulk_edit_nullable_cluster(self):
        """default_cluster is in nullable_fields, so it can be set to null."""
        self.assertIn('default_cluster', IncusHostBulkEditForm.nullable_fields)

    def test_bulk_edit_nullable_site(self):
        """default_site is in nullable_fields, so it can be set to null."""
        self.assertIn('default_site', IncusHostBulkEditForm.nullable_fields)

    def test_bulk_edit_negative_ttl_rejected(self):
        """url_cache_ttl has min_value=0, negative should fail."""
        form = IncusHostBulkEditForm(data=self._pk_data(url_cache_ttl=-1))
        self.assertFalse(form.is_valid())
        self.assertIn('url_cache_ttl', form.errors)


# ============================================
# ImportForm Tests
# ============================================

class IncusHostImportFormTestCase(IncusSyncTestCase):
    """Tests for the CSV import form."""

    def test_import_unix_host(self):
        """Import a minimal unix socket host."""
        form = IncusHostImportForm(data={
            'name': 'imported-unix',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_import_https_host(self):
        """Import an HTTPS host."""
        form = IncusHostImportForm(data={
            'name': 'imported-https',
            'connection_type': ConnectionTypeChoices.HTTPS,
            'https_urls': 'https://incus.example.com:8443',
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_import_with_cluster_by_name(self):
        """FK resolution: cluster by name."""
        form = IncusHostImportForm(data={
            'name': 'imported-with-cluster',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
            'default_cluster': 'Test Cluster',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['default_cluster'], self.cluster)

    def test_import_with_site_by_slug(self):
        """FK resolution: site by slug."""
        form = IncusHostImportForm(data={
            'name': 'imported-with-site',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
            'default_site': 'test-site',
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['default_site'], self.site)

    def test_import_with_nonexistent_cluster_fails(self):
        """Referencing a cluster that doesn't exist should fail."""
        form = IncusHostImportForm(data={
            'name': 'imported-bad-cluster',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
            'default_cluster': 'Does Not Exist',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('default_cluster', form.errors)

    def test_import_with_nonexistent_site_fails(self):
        """Referencing a site slug that doesn't exist should fail."""
        form = IncusHostImportForm(data={
            'name': 'imported-bad-site',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
            'default_site': 'no-such-site',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('default_site', form.errors)

    def test_import_missing_name_fails(self):
        """name is required."""
        form = IncusHostImportForm(data={
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_import_saves_to_db(self):
        """Verify the form actually creates a DB object."""
        form = IncusHostImportForm(data={
            'name': 'imported-saved',
            'connection_type': ConnectionTypeChoices.UNIX_SOCKET,
            'enabled': True,
            'url_cache_ttl': 300,
            'verify_ssl': True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        host = form.save()
        self.assertIsNotNone(host.pk)
        self.assertEqual(host.name, 'imported-saved')
        self.assertTrue(IncusHost.objects.filter(name='imported-saved').exists())