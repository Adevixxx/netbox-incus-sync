"""
Service to synchronize Incus instances to NetBox.
"""

from datetime import datetime
from django.utils import timezone
from virtualization.models import VirtualMachine, Cluster, ClusterType
from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from extras.models import Tag

from .sync_utils import parse_memory, parse_size, ensure_tags_exist

INCUS_CLUSTER_TYPE_SLUG = "incus"
INCUS_DEVICE_ROLE_SLUG = "hypervisor"
INCUS_MANUFACTURER_SLUG = "generic"
INCUS_DEVICE_TYPE_SLUG = "generic-server"


class InstanceSyncService:
    """Service to synchronize Incus instances to NetBox VirtualMachines."""

    def __init__(self, logger=None):
        self.logger = logger
        self.tags = {}
        self._cluster_type = None
        self._device_role = None
        self._device_type = None
        self._incus_version = None
        # Deduplication tracking for repetitive warnings
        self._warned_no_site = {}  # host.name -> set of location names

    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)

    def setup(self):
        self.tags = ensure_tags_exist(self.logger)

    def set_incus_version(self, version):
        """
        Sets the Incus server version to be stored on Devices.

        Called by the job orchestrator after retrieving server info.

        Args:
            version: Incus server version string (e.g. '6.7')
        """
        self._incus_version = version

    # ========== Cluster Management ==========

    @property
    def incus_cluster_type(self):
        if self._cluster_type is None:
            self._cluster_type, created = ClusterType.objects.get_or_create(
                slug=INCUS_CLUSTER_TYPE_SLUG,
                defaults={
                    "name": "Incus",
                    "description": "Incus Cluster (containers and VMs)",
                },
            )
            if created:
                self.log("info", f"  ClusterType 'Incus' created")
        return self._cluster_type

    def resolve_cluster(self, host, cluster_info=None):
        """Determines the cluster to use for a host's VMs. Now always creates one per host."""
        cluster_name = host.name
        return self._get_or_create_cluster(cluster_name, host)

    def _get_or_create_cluster(self, cluster_name, host):
        cluster, created = Cluster.objects.get_or_create(
            name=cluster_name,
            type=self.incus_cluster_type,
            defaults={
                "description": f"Incus Cluster synchronized from {host.name}",
            },
        )

        if created:
            self.log("info", f"  NetBox Cluster created: {cluster_name}")

        return cluster

    # ========== Device Management (for cluster nodes) ==========

    @property
    def hypervisor_role(self):
        """Gets or creates the Hypervisor device role."""
        if self._device_role is None:
            self._device_role, created = DeviceRole.objects.get_or_create(
                slug=INCUS_DEVICE_ROLE_SLUG,
                defaults={
                    "name": "Hypervisor",
                    "description": "Hypervisor running Incus containers and VMs",
                    "vm_role": True,
                },
            )
            if created:
                self.log("info", f"  DeviceRole 'Hypervisor' created")
        return self._device_role

    @property
    def generic_device_type(self):
        """Gets or creates the Generic Server device type."""
        if self._device_type is None:
            manufacturer, mfr_created = Manufacturer.objects.get_or_create(
                slug=INCUS_MANUFACTURER_SLUG,
                defaults={
                    "name": "Generic",
                    "description": "Generic manufacturer for auto-discovered devices",
                },
            )
            if mfr_created:
                self.log("info", f"  Manufacturer 'Generic' created")

            self._device_type, dt_created = DeviceType.objects.get_or_create(
                slug=INCUS_DEVICE_TYPE_SLUG,
                manufacturer=manufacturer,
                defaults={
                    "model": "Server",
                    "description": "Generic server (auto-created by Incus Sync)",
                },
            )
            if dt_created:
                self.log("info", f"  DeviceType 'Generic Server' created")
        return self._device_type

    def resolve_device(self, location, host, cluster=None):
        """
        Resolves or creates a Device for an Incus cluster node.

        Also updates the Incus version custom field on the Device if available.

        Args:
            location: Incus cluster node name (from instance 'location' field)
            host: IncusHost instance (for default_site)

        Returns:
            Device or None: The Device for this node, or None if no location
        """
        if not location:
            return None

        # Try to find existing Device by name
        device = Device.objects.filter(name=location).first()

        if device:
            updated = False

            if cluster and device.cluster != cluster:
                device.cluster = cluster
                updated = True
                self.log(
                    "info",
                    f"  Device '{location}' assigned to cluster '{cluster.name}'",
                )

            # Update Incus version on existing device
            if (
                self._incus_version
                and device.custom_field_data.get("incus_version") != self._incus_version
            ):
                device.custom_field_data["incus_version"] = self._incus_version
                updated = True
                self.log(
                    "debug",
                    f"  Device '{location}' Incus version updated to {self._incus_version}",
                )

            if updated:
                device.save()

            return device

        # Auto-create the Device
        site = host.default_site
        if not site:
            # Cannot create a Device without a site - deduplicate warnings
            host_name = host.name
            if host_name not in self._warned_no_site:
                # First time seeing this host, log the detailed warning
                self._warned_no_site[host_name] = set()
                self.log(
                    "warning",
                    f"  Cannot auto-create Device '{location}': no default_site configured on host '{host_name}'. "
                    f"Set a Default Site on the Incus Host to enable automatic Device creation.",
                )
            # Track the location name for summary
            self._warned_no_site[host_name].add(location)
            return None

        device = Device.objects.create(
            name=location,
            site=site,
            cluster=cluster,
            device_type=self.generic_device_type,
            role=self.hypervisor_role,
            status="active",
            description=f"Incus cluster node (auto-created by Incus Sync from {host.name})",
        )

        # Set Incus version on newly created device
        if self._incus_version:
            device.custom_field_data["incus_version"] = self._incus_version
            device.save()

        self.log(
            "info",
            f"  Device auto-created: {location} (site: {site.name}, cluster: {cluster.name if cluster else 'none'})",
        )
        return device

    # ========== Instance Synchronization ==========

    def sync_instance(self, data, cluster, host, tenant=None, project=None):
        """Synchronizes an Incus instance to NetBox."""
        vm_name = data.get("name")
        status_raw = data.get("status")
        instance_type = data.get("type", "container")
        location = data.get("location", "")

        # Use expanded_config for limits (includes profile-inherited values)
        # Fall back to config if expanded_config is not available
        expanded_config = data.get("expanded_config", {})
        config = data.get("config", {})

        # UUID is always in volatile config (instance-specific)
        incus_uuid = config.get("volatile.uuid", "")

        nb_status = "active" if status_raw == "Running" else "offline"

        # Extract resources from expanded_config (profile + instance overrides)
        vcpus = self._extract_cpu(expanded_config, config)
        memory_mb = self._extract_memory(expanded_config, config)

        # Disk size from expanded_devices
        expanded_devices = data.get("expanded_devices", {})
        devices = data.get("devices", {})
        disk_mb = self._extract_disk(expanded_devices if expanded_devices else devices)

        # Resolve Device for cluster node
        device = self.resolve_device(location, host, cluster=cluster)

        defaults = {
            "status": nb_status,
            "vcpus": vcpus,
            "cluster": cluster,
            "device": device,
            "tenant": tenant,  # Project → Tenant mapping
        }

        if memory_mb:
            defaults["memory"] = memory_mb
        if disk_mb:
            defaults["disk"] = disk_mb

        existing_vm = self._find_existing_vm(incus_uuid, host)
        created = existing_vm is None
        renamed = False
        old_name = None

        if existing_vm:
            if existing_vm.name != vm_name:
                old_name = existing_vm.name
                renamed = True
                self.log("info", f"  Rename detected: {old_name} -> {vm_name}")

            existing_vm.name = vm_name
            existing_vm.tenant = tenant  # Update tenant on existing VMs
            for key, value in defaults.items():
                setattr(existing_vm, key, value)
            existing_vm.save()
            vm = existing_vm
        else:
            vm = VirtualMachine.objects.create(name=vm_name, **defaults)

        # Store UUID in native serial field
        if incus_uuid and vm.serial != incus_uuid:
            vm.serial = incus_uuid
            vm.save(update_fields=["serial"])

        # Inject project name for custom field tracking
        data["_incus_project"] = project or "default"

        self._update_vm_custom_fields(vm, data, host)
        self._apply_tags(vm, instance_type)

        if renamed:
            action = f"Renamed ({old_name} ->)"
        elif created:
            action = "Created"
        else:
            action = "Updated"

        type_label = "container" if instance_type == "container" else "VM"
        cluster_info_str = f" in {cluster.name}" if cluster else " (no cluster)"
        location_info = f" on {location}" if location else ""
        device_info = f" [device: {device.name}]" if device else ""
        tenant_info = f" [tenant: {tenant.name}]" if tenant else ""
        project_info = (
            f" [project: {project}]" if project and project != "default" else ""
        )

        mem_str = f"{memory_mb}MB" if memory_mb else "N/A"
        cpu_str = f"{vcpus}" if vcpus else "N/A"
        log_level = "info" if action in ("Created", "Renamed (") else "debug"
        self.log(
            log_level,
            f"  {action}: {vm_name} ({type_label}, vCPU={cpu_str}, RAM={mem_str}){cluster_info_str}{location_info}{device_info}{tenant_info}{project_info}",
        )

        return vm, created, not created

    def _find_existing_vm(self, incus_uuid, host):
        """Searches for an existing VM by UUID (stored in native serial field)."""
        if not incus_uuid:
            return None

        return VirtualMachine.objects.filter(serial=incus_uuid).first()

    def _update_vm_custom_fields(self, vm, data, host):
        """Updates VM Custom Fields."""
        # Use expanded_config for image info (may come from profile)
        expanded_config = data.get("expanded_config", {})
        config = data.get("config", {})

        instance_type = data.get("type", "container")
        created_at = data.get("created_at", "")
        profiles = data.get("profiles", [])

        # Image info: check both expanded_config and config
        image_info = (
            expanded_config.get("image.description")
            or config.get("image.description")
            or (
                expanded_config.get("image.os", "")
                + " "
                + expanded_config.get("image.release", "")
            ).strip()
            or (
                config.get("image.os", "") + " " + config.get("image.release", "")
            ).strip()
            or config.get("volatile.base_image", "")
            or "Unknown"
        ).strip()

        updated = False

        if vm.custom_field_data.get("incus_host") != host.name:
            vm.custom_field_data["incus_host"] = host.name
            updated = True

        if vm.custom_field_data.get("incus_type") != instance_type:
            vm.custom_field_data["incus_type"] = instance_type
            updated = True

        if image_info and image_info != "Unknown":
            if vm.custom_field_data.get("incus_image") != image_info:
                vm.custom_field_data["incus_image"] = image_info
                updated = True

        if created_at:
            created_datetime = self._parse_incus_datetime(created_at)
            if created_datetime:
                created_iso = created_datetime.isoformat()
                if vm.custom_field_data.get("incus_created") != created_iso:
                    vm.custom_field_data["incus_created"] = created_iso
                    updated = True

        now_iso = timezone.now().isoformat()
        vm.custom_field_data["incus_last_sync"] = now_iso
        updated = True

        if profiles:
            profiles_str = ", ".join(profiles)
            if vm.custom_field_data.get("incus_profiles") != profiles_str:
                vm.custom_field_data["incus_profiles"] = profiles_str
                updated = True
        elif "incus_profiles" in vm.custom_field_data:
            del vm.custom_field_data["incus_profiles"]
            updated = True

        # Store Incus project name
        incus_project = data.get("_incus_project", "default")
        if vm.custom_field_data.get("incus_project") != incus_project:
            vm.custom_field_data["incus_project"] = incus_project
            updated = True

        # Clean up legacy custom fields that are now native fields
        for legacy_field in ["incus_uuid", "incus_location"]:
            if legacy_field in vm.custom_field_data:
                del vm.custom_field_data[legacy_field]
                updated = True

        if updated:
            vm.save()

    def _parse_incus_datetime(self, dt_string):
        """Parses an Incus datetime (ISO format with nanoseconds)."""
        if not dt_string:
            return None

        try:
            if "." in dt_string:
                base, frac = dt_string.split(".")
                frac_clean = frac.rstrip("Z")[:6]
                dt_string = f"{base}.{frac_clean}Z"

            return datetime.fromisoformat(dt_string.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as e:
            self.log("debug", f"    Unable to parse date: {dt_string} - {e}")
            return None

    def handle_deletions(self, cluster, host, incus_instance_uuids):
        """Deletes VMs that no longer exist in Incus."""
        deleted_count = 0

        try:
            managed_tag = Tag.objects.get(slug="incus-managed")
        except Tag.DoesNotExist:
            return 0

        managed_vms = VirtualMachine.objects.filter(
            tags=managed_tag, custom_field_data__incus_host=host.name
        )

        for vm in managed_vms:
            # UUID is now in native serial field
            vm_uuid = vm.serial or ""

            if vm_uuid and vm_uuid not in incus_instance_uuids:
                vm_name = vm.name
                self.log(
                    "warning",
                    f"  Instance disappeared from Incus: {vm_name} (UUID: {vm_uuid[:8]}...)",
                )
                vm.delete()
                deleted_count += 1
                self.log("info", f"  Deleted from NetBox: {vm_name}")

        return deleted_count

    def log_deferred_warnings(self):
        """
        Logs summary warnings for deduplicated messages.

        Call this at the end of host processing to emit summaries
        for warnings that were deduplicated during sync.
        """
        # Summary for devices that couldn't be auto-created due to missing default_site
        for host_name, locations in self._warned_no_site.items():
            if len(locations) > 1:
                sorted_locations = ", ".join(sorted(locations))
                self.log(
                    "warning",
                    f"  {len(locations)} devices could not be auto-created for host '{host_name}' "
                    f"(no default_site): {sorted_locations}",
                )
        # Clear tracking for next host
        self._warned_no_site.clear()

    def _extract_cpu(self, expanded_config, config):
        """
        Extracts CPU count from expanded_config (preferred) or config.

        Handles both integer values and range formats (e.g., "0-3" = 4 CPUs).
        """
        cpu_str = expanded_config.get("limits.cpu") or config.get("limits.cpu")
        if not cpu_str:
            return None

        cpu_str = str(cpu_str).strip()

        # Range format: "0-3" means CPUs 0,1,2,3 = 4 CPUs
        if "-" in cpu_str and not cpu_str.startswith("-"):
            try:
                parts = cpu_str.split("-")
                start = int(parts[0])
                end = int(parts[1])
                return end - start + 1
            except (ValueError, IndexError):
                pass

        # Comma-separated: "0,1,2,3" = 4 CPUs
        if "," in cpu_str:
            return len(cpu_str.split(","))

        # Simple integer
        try:
            return int(cpu_str)
        except ValueError:
            return None

    def _extract_memory(self, expanded_config, config):
        """Extracts memory in MB from expanded_config (preferred) or config."""
        mem_str = expanded_config.get("limits.memory") or config.get("limits.memory")
        if not mem_str:
            return None
        return parse_memory(str(mem_str))

    def _extract_disk(self, devices):
        """Extracts root disk size in MB from devices."""
        for dev_name, dev_config in devices.items():
            if dev_config.get("type") == "disk" and dev_config.get("path") == "/":
                size_str = dev_config.get("size", "")
                if size_str:
                    return parse_size(size_str)
        return None

    def _apply_tags(self, vm, instance_type):
        """Applies tags to the VM."""
        # Managed tag
        managed_tag = self.tags.get("incus-managed")
        if managed_tag and managed_tag not in vm.tags.all():
            vm.tags.add(managed_tag)

        # Type tag
        type_tag_slug = f"incus-{instance_type}"
        type_tag = self.tags.get(type_tag_slug)
        if type_tag and type_tag not in vm.tags.all():
            vm.tags.add(type_tag)
