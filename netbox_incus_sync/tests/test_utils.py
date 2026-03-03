"""
Tests for netbox_incus_sync.services.sync_utils

Pure function tests — no database needed (SimpleTestCase).
"""

from django.test import SimpleTestCase
from netbox_incus_sync.services.sync_utils import (
    parse_memory,
    parse_size,
    sanitize_config,
    sanitize_devices,
    extract_limits,
    extract_security,
    get_instance_type_tag,
)


class ParseMemoryTests(SimpleTestCase):

    def test_gibibytes(self):
        self.assertEqual(parse_memory("1GiB"), 1024)
        self.assertEqual(parse_memory("2GiB"), 2048)

    def test_case_insensitive(self):
        self.assertEqual(parse_memory("2gib"), 2048)

    def test_gigabytes(self):
        self.assertEqual(parse_memory("4GB"), 4096)

    def test_mebibytes(self):
        self.assertEqual(parse_memory("512MiB"), 512)

    def test_megabytes(self):
        self.assertEqual(parse_memory("1024MB"), 1024)

    def test_raw_bytes(self):
        self.assertEqual(parse_memory("1073741824"), 1024)

    def test_fractional(self):
        self.assertEqual(parse_memory("1.5GiB"), 1536)

    def test_none(self):
        self.assertIsNone(parse_memory(None))

    def test_empty(self):
        self.assertIsNone(parse_memory(""))

    def test_invalid(self):
        self.assertIsNone(parse_memory("abc"))

    def test_zero(self):
        self.assertEqual(parse_memory("0"), 0)

    def test_whitespace(self):
        self.assertEqual(parse_memory("  4GiB  "), 4096)


class SanitizeConfigTests(SimpleTestCase):

    def test_removes_volatile(self):
        r = sanitize_config({"volatile.uuid": "x", "limits.cpu": "2"})
        self.assertNotIn("volatile.uuid", r)
        self.assertEqual(r["limits.cpu"], "2")

    def test_removes_image(self):
        r = sanitize_config({"image.os": "Ubuntu", "security.nesting": "true"})
        self.assertNotIn("image.os", r)

    def test_removes_secrets(self):
        r = sanitize_config({"user.password": "s", "user.description": "ok"})
        self.assertNotIn("user.password", r)
        self.assertEqual(r["user.description"], "ok")

    def test_none(self):
        self.assertEqual(sanitize_config(None), {})


class SanitizeDevicesTests(SimpleTestCase):

    def test_removes_user_keys(self):
        r = sanitize_devices({"eth0": {"type": "nic", "user.tag": "x"}})
        self.assertNotIn("user.tag", r["eth0"])

    def test_none(self):
        self.assertEqual(sanitize_devices(None), {})


class ExtractLimitsTests(SimpleTestCase):

    def test_cpu_memory(self):
        r = extract_limits({"limits.cpu": "4", "limits.memory": "8GiB"})
        self.assertEqual(r["cpu"], "4")

    def test_no_limits(self):
        self.assertIsNone(extract_limits({}))


class ExtractSecurityTests(SimpleTestCase):

    def test_booleans(self):
        r = extract_security(
            {"security.nesting": "true", "security.privileged": "false"}
        )
        self.assertTrue(r["nesting"])
        self.assertFalse(r["privileged"])

    def test_no_security(self):
        self.assertIsNone(extract_security({}))


class GetInstanceTypeTagTests(SimpleTestCase):

    def test_container(self):
        self.assertEqual(get_instance_type_tag("container"), "incus-container")

    def test_vm(self):
        self.assertEqual(get_instance_type_tag("virtual-machine"), "incus-vm")
