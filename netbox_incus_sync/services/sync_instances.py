"""
Service to synchronize Incus instances to NetBox.

Uses native NetBox objects:
- ClusterType: "Incus" type created automatically
- Cluster: One cluster per Incus host (if Incus clustering is enabled)
- VirtualMachine: The Incus instances
"""

from datetime import datetime
from django.utils import timezone
from virtualization.models import VirtualMachine, Cluster, ClusterType
from extras.models import Tag

from .sync_utils import parse_memory, parse_size, ensure_tags_exist


# Incus ClusterType Slug
INCUS_CLUSTER_TYPE_SLUG = 'incus'


class InstanceSyncService:
    """
    Service to synchronize Incus instances to NetBox VirtualMachines.
    
    Cluster management:
    - If Incus is NOT in cluster mode: VMs are created without a cluster
      (unless default_cluster is manually defined on the IncusHost)
    - If Incus IS in cluster mode: A NetBox Cluster is automatically created
      and all VMs are assigned to it
    """
    
    def __init__(self, logger=None):
        """
        Initializes the service.
        
        Args:
            logger: Logger for messages (optional)
        """
        self.logger = logger
        self.tags = {}
        self._cluster_type = None
    
    def log(self, level, message):
        """Log a message if logger is available."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    def setup(self):
        """Prepares the service (creates tags, etc.)."""
        self.tags = ensure_tags_exist(self.logger)
    
    @property
    def incus_cluster_type(self):
        """
        Returns the "Incus" ClusterType, creates it if necessary.
        
        Returns:
            ClusterType: The Incus cluster type
        """
        if self._cluster_type is None:
            self._cluster_type, created = ClusterType.objects.get_or_create(
                slug=INCUS_CLUSTER_TYPE_SLUG,
                defaults={
                    'name': 'Incus',
                    'description': 'Incus Cluster (containers and VMs)',
                }
            )
            if created:
                self.log('info', f"  ClusterType 'Incus' created")
        return self._cluster_type
    
    def resolve_cluster(self, host, cluster_info=None):
        """
        Determines the cluster to use for a host's VMs.
        
        Logic:
        1. If cluster_info indicates Incus is in cluster mode -> create/use a NetBox Cluster
        2. Else, if default_cluster is defined on the host -> use it
        3. Else -> no cluster (None)
        
        Args:
            host: IncusHost instance
            cluster_info: Dict with cluster info from Incus API (optional)
                         {'enabled': bool, 'server_name': str, 'member_count': int}
        
        Returns:
            Cluster or None: The cluster to use
        """
        # Case 1: Incus is in cluster mode
        if cluster_info and cluster_info.get('enabled'):
            cluster_name = cluster_info.get('server_name') or f"incus-{host.name}"
            return self._get_or_create_cluster(cluster_name, host)
        
        # Case 2: Use default cluster if defined
        if host.default_cluster:
            return host.default_cluster
        
        # Case 3: No cluster
        return None
    
    def _get_or_create_cluster(self, cluster_name, host):
        """
        Retrieves or creates a NetBox Cluster for an Incus cluster.
        
        Args:
            cluster_name: Cluster name
            host: Source IncusHost
        
        Returns:
            Cluster: The NetBox Cluster
        """
        cluster, created = Cluster.objects.get_or_create(
            name=cluster_name,
            type=self.incus_cluster_type,
            defaults={
                'description': f"Incus Cluster synchronized from {host.name}",
            }
        )
        
        if created:
            self.log('info', f"  NetBox Cluster created: {cluster_name}")
        
        return cluster
    
    def sync_instance(self, data, cluster, host):
        """
        Synchronizes an Incus instance to NetBox.
        
        Uses the Incus UUID (volatile.uuid) as a unique identifier to:
        - Find an existing VM even if it was renamed
        - Avoid duplicates
        
        Args:
            data: Incus instance data
            cluster: Target NetBox Cluster (can be None)
            host: Source IncusHost instance
        
        Returns:
            tuple: (vm, created: bool, updated: bool)
        """
        vm_name = data.get('name')
        status_raw = data.get('status')
        instance_type = data.get('type', 'container')
        config = data.get('config', {})
        
        # Unique Incus instance UUID
        incus_uuid = config.get('volatile.uuid', '')
        
        # Location field for clustering - indicates which node the instance is running on
        location = data.get('location', '')
        
        # Status mapping
        nb_status = 'active' if status_raw == 'Running' else 'offline'
        
        # Resource extraction
        vcpus = self._extract_cpu(config)
        memory_mb = parse_memory(config.get('limits.memory', ''))
        disk_mb = self._extract_disk(data.get('devices', {}))
        
        # Defaults for update_or_create
        defaults = {
            'status': nb_status,
            'vcpus': vcpus,
            'cluster': cluster,  # Can be None - this is intended!
        }
        
        if memory_mb:
            defaults['memory'] = memory_mb
        if disk_mb:
            defaults['disk'] = disk_mb
        
        # Search for existing VM by UUID first, then by name
        existing_vm = self._find_existing_vm(vm_name, incus_uuid, host)
        created = existing_vm is None
        renamed = False
        old_name = None
        
        if existing_vm:
            # Check if instance was renamed
            if existing_vm.name != vm_name:
                old_name = existing_vm.name
                renamed = True
                self.log('info', f"  Rename detected: {old_name} -> {vm_name}")
            
            # Update existing VM
            existing_vm.name = vm_name  # Update name if renamed
            for key, value in defaults.items():
                setattr(existing_vm, key, value)
            existing_vm.save()
            vm = existing_vm
        else:
            # Create new VM
            vm = VirtualMachine.objects.create(
                name=vm_name,
                **defaults
            )
        
        # Update Custom Fields (including UUID)
        self._update_vm_custom_fields(vm, data, host, location, incus_uuid)
        
        # Apply tags
        self._apply_tags(vm, instance_type)
        
        # Log
        if renamed:
            action = f"Renamed ({old_name} ->)"
        elif created:
            action = "Created"
        else:
            action = "Updated"
        
        type_label = "container" if instance_type == 'container' else "VM"
        cluster_info = f" in {cluster.name}" if cluster else " (no cluster)"
        location_info = f" on {location}" if location else ""
        self.log('info', f"  {action}: {vm_name} ({type_label}){cluster_info}{location_info}")
        
        return vm, created, not created
    
    def _find_existing_vm(self, vm_name, incus_uuid, host):
        """
        Searches for an existing VM, first by UUID then by name.
        
        Search strategy (in order):
        1. By Incus UUID (most reliable, survives renames)
        2. By name + Incus host (fallback for old VMs without UUID)
        
        Args:
            vm_name: Current VM name in Incus
            incus_uuid: Incus instance UUID (volatile.uuid)
            host: Source IncusHost
        
        Returns:
            VirtualMachine or None
        """
        # 1. Search by UUID (preferred method)
        if incus_uuid:
            vm = VirtualMachine.objects.filter(
                custom_field_data__incus_uuid=incus_uuid
            ).first()
            if vm:
                return vm
        
        # 2. Fallback: search by name + Incus host
        # (for VMs created before UUID tracking was added)
        vm = VirtualMachine.objects.filter(
            name=vm_name,
            custom_field_data__incus_host=host.name
        ).first()
        
        return vm
    
    def _update_vm_custom_fields(self, vm, data, host, location='', incus_uuid=''):
        """
        Updates VM Custom Fields.
        
        Args:
            vm: NetBox VirtualMachine instance
            data: Incus instance data
            host: Source IncusHost instance
            location: Cluster node name (optional)
            incus_uuid: Unique Incus instance UUID
        """
        config = data.get('config', {})
        instance_type = data.get('type', 'container')
        created_at = data.get('created_at', '')
        profiles = data.get('profiles', [])
        
        # Image: try multiple possible keys
        image_info = (
            config.get('image.description') or 
            config.get('image.os', '') + ' ' + config.get('image.release', '') or
            config.get('volatile.base_image', '') or
            'Unknown'
        ).strip()
        
        updated = False
        
        # Incus UUID (unique identifier for tracking)
        if incus_uuid and vm.custom_field_data.get('incus_uuid') != incus_uuid:
            vm.custom_field_data['incus_uuid'] = incus_uuid
            updated = True
        
        # Source Incus Host
        if vm.custom_field_data.get('incus_host') != host.name:
            vm.custom_field_data['incus_host'] = host.name
            updated = True
        
        # Instance Type
        if vm.custom_field_data.get('incus_type') != instance_type:
            vm.custom_field_data['incus_type'] = instance_type
            updated = True
        
        # Image
        if image_info and image_info != 'Unknown':
            if vm.custom_field_data.get('incus_image') != image_info:
                vm.custom_field_data['incus_image'] = image_info
                updated = True
        
        # Created in Incus (convert ISO to datetime)
        if created_at:
            created_datetime = self._parse_incus_datetime(created_at)
            if created_datetime:
                created_iso = created_datetime.isoformat()
                if vm.custom_field_data.get('incus_created') != created_iso:
                    vm.custom_field_data['incus_created'] = created_iso
                    updated = True
        
        # Last Sync (always update)
        now_iso = timezone.now().isoformat()
        vm.custom_field_data['incus_last_sync'] = now_iso
        updated = True
        
        # Profiles (list -> comma separated string)
        if profiles:
            profiles_str = ', '.join(profiles)
            if vm.custom_field_data.get('incus_profiles') != profiles_str:
                vm.custom_field_data['incus_profiles'] = profiles_str
                updated = True
        elif 'incus_profiles' in vm.custom_field_data:
            del vm.custom_field_data['incus_profiles']
            updated = True
        
        # Cluster Node Location (for Incus cluster instances)
        if location:
            if vm.custom_field_data.get('incus_location') != location:
                vm.custom_field_data['incus_location'] = location
                updated = True
        elif 'incus_location' in vm.custom_field_data:
            # Remove if no location (instance moved out of cluster)
            del vm.custom_field_data['incus_location']
            updated = True
        
        if updated:
            vm.save()
    
    def _parse_incus_datetime(self, dt_string):
        """
        Parses an Incus datetime (ISO format with nanoseconds).
        
        Args:
            dt_string: Datetime string in Incus format
        
        Returns:
            datetime or None
        """
        if not dt_string:
            return None
        
        try:
            # Incus Format: 2026-01-27T13:58:42.690298037Z
            # Python does not handle nanoseconds, truncate to microseconds
            if '.' in dt_string:
                base, frac = dt_string.split('.')
                frac_clean = frac.rstrip('Z')[:6]
                dt_string = f"{base}.{frac_clean}Z"
            
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            self.log('debug', f"    Unable to parse date: {dt_string} - {e}")
            return None
    
    def handle_deletions(self, cluster, host, incus_instance_uuids):
        """
        Deletes VMs that no longer exist in Incus.
        
        Uses UUIDs to identify VMs to delete.
        
        Args:
            cluster: NetBox Cluster (can be None)
            host: Source IncusHost
            incus_instance_uuids: Set of current instance UUIDs in Incus
        
        Returns:
            int: Number of VMs deleted
        """
        deleted_count = 0
        
        try:
            managed_tag = Tag.objects.get(slug='incus-managed')
        except Tag.DoesNotExist:
            return 0
        
        # Filter VMs managed by this Incus host
        managed_vms = VirtualMachine.objects.filter(
            tags=managed_tag,
            custom_field_data__incus_host=host.name
        )
        
        for vm in managed_vms:
            vm_uuid = vm.custom_field_data.get('incus_uuid', '')
            
            # If VM has a UUID and it is not in Incus
            if vm_uuid and vm_uuid not in incus_instance_uuids:
                vm_name = vm.name
                self.log('warning', f"  Instance disappeared from Incus: {vm_name} (UUID: {vm_uuid[:8]}...)")
                
                # Delete VM from NetBox
                vm.delete()
                deleted_count += 1
                self.log('info', f"  Deleted from NetBox: {vm_name}")
            
            # Fallback for VMs without UUID (old)
            elif not vm_uuid:
                self.log('debug', f"  VM without UUID ignored for deletion: {vm.name}")
        
        return deleted_count
    
    def _extract_cpu(self, config):
        """Extracts the number of vCPUs from config."""
        try:
            return float(config.get('limits.cpu', 1))
        except (ValueError, TypeError):
            return 1
    
    def _extract_disk(self, devices):
        """Extracts the root disk size from devices."""
        for dev_name, dev_conf in devices.items():
            if dev_conf.get('type') == 'disk' and dev_conf.get('path') == '/':
                raw_disk = dev_conf.get('size', '0')
                return parse_size(raw_disk)
        return 0
    
    def _apply_tags(self, vm, instance_type):
        """Applies appropriate tags to the VM."""
        managed_tag = self.tags.get('incus-managed') or Tag.objects.get(slug='incus-managed')
        
        if instance_type == 'container':
            type_tag = self.tags.get('incus-container') or Tag.objects.get(slug='incus-container')
            other_tag_slug = 'incus-vm'
        else:
            type_tag = self.tags.get('incus-vm') or Tag.objects.get(slug='incus-vm')
            other_tag_slug = 'incus-container'
        
        vm.tags.add(managed_tag)
        vm.tags.add(type_tag)
        
        # Remove the other type tag if present
        try:
            other_tag = Tag.objects.get(slug=other_tag_slug)
            vm.tags.remove(other_tag)
        except Tag.DoesNotExist:
            pass
        
        vm.save()