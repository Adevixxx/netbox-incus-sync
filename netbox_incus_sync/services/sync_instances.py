"""
Service to synchronize Incus instances to NetBox.
"""

from datetime import datetime
from django.utils import timezone
from virtualization.models import VirtualMachine, Cluster, ClusterType
from extras.models import Tag

from .sync_utils import parse_memory, parse_size, ensure_tags_exist


INCUS_CLUSTER_TYPE_SLUG = 'incus'


class InstanceSyncService:
    """Service to synchronize Incus instances to NetBox VirtualMachines."""
    
    def __init__(self, logger=None):
        self.logger = logger
        self.tags = {}
        self._cluster_type = None
    
    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)
    
    def setup(self):
        self.tags = ensure_tags_exist(self.logger)
    
    @property
    def incus_cluster_type(self):
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
        """Determines the cluster to use for a host's VMs."""
        if cluster_info and cluster_info.get('enabled'):
            cluster_name = cluster_info.get('server_name') or f"incus-{host.name}"
            return self._get_or_create_cluster(cluster_name, host)
        
        if host.default_cluster:
            return host.default_cluster
        
        return None
    
    def _get_or_create_cluster(self, cluster_name, host):
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
        """Synchronizes an Incus instance to NetBox."""
        vm_name = data.get('name')
        status_raw = data.get('status')
        instance_type = data.get('type', 'container')
        config = data.get('config', {})
        incus_uuid = config.get('volatile.uuid', '')
        location = data.get('location', '')
        
        nb_status = 'active' if status_raw == 'Running' else 'offline'
        
        vcpus = self._extract_cpu(config)
        memory_mb = parse_memory(config.get('limits.memory', ''))
        disk_mb = self._extract_disk(data.get('devices', {}))
        
        defaults = {
            'status': nb_status,
            'vcpus': vcpus,
            'cluster': cluster,
        }
        
        if memory_mb:
            defaults['memory'] = memory_mb
        if disk_mb:
            defaults['disk'] = disk_mb
        
        existing_vm = self._find_existing_vm(incus_uuid, host)
        created = existing_vm is None
        renamed = False
        old_name = None
        
        if existing_vm:
            if existing_vm.name != vm_name:
                old_name = existing_vm.name
                renamed = True
                self.log('info', f"  Rename detected: {old_name} -> {vm_name}")
            
            existing_vm.name = vm_name
            for key, value in defaults.items():
                setattr(existing_vm, key, value)
            existing_vm.save()
            vm = existing_vm
        else:
            vm = VirtualMachine.objects.create(
                name=vm_name,
                **defaults
            )
        
        self._update_vm_custom_fields(vm, data, host, location, incus_uuid)
        self._apply_tags(vm, instance_type)
        
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
    
    def _find_existing_vm(self, incus_uuid, host):
        """Searches for an existing VM by UUID."""
        if not incus_uuid:
            return None
        
        return VirtualMachine.objects.filter(
            custom_field_data__incus_uuid=incus_uuid
        ).first()
    
    def _update_vm_custom_fields(self, vm, data, host, location='', incus_uuid=''):
        """Updates VM Custom Fields."""
        config = data.get('config', {})
        instance_type = data.get('type', 'container')
        created_at = data.get('created_at', '')
        profiles = data.get('profiles', [])
        
        image_info = (
            config.get('image.description') or 
            config.get('image.os', '') + ' ' + config.get('image.release', '') or
            config.get('volatile.base_image', '') or
            'Unknown'
        ).strip()
        
        updated = False
        
        if incus_uuid and vm.custom_field_data.get('incus_uuid') != incus_uuid:
            vm.custom_field_data['incus_uuid'] = incus_uuid
            updated = True
        
        if vm.custom_field_data.get('incus_host') != host.name:
            vm.custom_field_data['incus_host'] = host.name
            updated = True
        
        if vm.custom_field_data.get('incus_type') != instance_type:
            vm.custom_field_data['incus_type'] = instance_type
            updated = True
        
        if image_info and image_info != 'Unknown':
            if vm.custom_field_data.get('incus_image') != image_info:
                vm.custom_field_data['incus_image'] = image_info
                updated = True
        
        if created_at:
            created_datetime = self._parse_incus_datetime(created_at)
            if created_datetime:
                created_iso = created_datetime.isoformat()
                if vm.custom_field_data.get('incus_created') != created_iso:
                    vm.custom_field_data['incus_created'] = created_iso
                    updated = True
        
        now_iso = timezone.now().isoformat()
        vm.custom_field_data['incus_last_sync'] = now_iso
        updated = True
        
        if profiles:
            profiles_str = ', '.join(profiles)
            if vm.custom_field_data.get('incus_profiles') != profiles_str:
                vm.custom_field_data['incus_profiles'] = profiles_str
                updated = True
        elif 'incus_profiles' in vm.custom_field_data:
            del vm.custom_field_data['incus_profiles']
            updated = True
        
        if location:
            if vm.custom_field_data.get('incus_location') != location:
                vm.custom_field_data['incus_location'] = location
                updated = True
        elif 'incus_location' in vm.custom_field_data:
            del vm.custom_field_data['incus_location']
            updated = True
        
        if updated:
            vm.save()
    
    def _parse_incus_datetime(self, dt_string):
        """Parses an Incus datetime (ISO format with nanoseconds)."""
        if not dt_string:
            return None
        
        try:
            if '.' in dt_string:
                base, frac = dt_string.split('.')
                frac_clean = frac.rstrip('Z')[:6]
                dt_string = f"{base}.{frac_clean}Z"
            
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            self.log('debug', f"    Unable to parse date: {dt_string} - {e}")
            return None
    
    def handle_deletions(self, cluster, host, incus_instance_uuids):
        """Deletes VMs that no longer exist in Incus."""
        deleted_count = 0
        
        try:
            managed_tag = Tag.objects.get(slug='incus-managed')
        except Tag.DoesNotExist:
            return 0
        
        managed_vms = VirtualMachine.objects.filter(
            tags=managed_tag,
            custom_field_data__incus_host=host.name
        )
        
        for vm in managed_vms:
            vm_uuid = vm.custom_field_data.get('incus_uuid', '')
            
            if vm_uuid and vm_uuid not in incus_instance_uuids:
                vm_name = vm.name
                self.log('warning', f"  Instance disappeared from Incus: {vm_name} (UUID: {vm_uuid[:8]}...)")
                vm.delete()
                deleted_count += 1
                self.log('info', f"  Deleted from NetBox: {vm_name}")
        
        return deleted_count
    
    def _extract_cpu(self, config):
        try:
            return float(config.get('limits.cpu', 1))
        except (ValueError, TypeError):
            return 1
    
    def _extract_disk(self, devices):
        for dev_name, dev_conf in devices.items():
            if dev_conf.get('type') == 'disk' and dev_conf.get('path') == '/':
                raw_disk = dev_conf.get('size', '0')
                return parse_size(raw_disk)
        return 0
    
    def _apply_tags(self, vm, instance_type):
        managed_tag = self.tags.get('incus-managed') or Tag.objects.get(slug='incus-managed')
        
        if instance_type == 'container':
            type_tag = self.tags.get('incus-container') or Tag.objects.get(slug='incus-container')
            other_tag_slug = 'incus-vm'
        else:
            type_tag = self.tags.get('incus-vm') or Tag.objects.get(slug='incus-vm')
            other_tag_slug = 'incus-container'
        
        vm.tags.add(managed_tag)
        vm.tags.add(type_tag)
        
        try:
            other_tag = Tag.objects.get(slug=other_tag_slug)
            vm.tags.remove(other_tag)
        except Tag.DoesNotExist:
            pass
        
        vm.save()