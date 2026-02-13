"""
Incus synchronization jobs for NetBox.

This file contains only orchestration logic.
Business logic is located in the services/ directory.
"""

from netbox.jobs import JobRunner

from .incus_client import IncusClient
from .models import IncusHost
from .services import (
    InstanceSyncService, 
    NetworkSyncService, 
    DiskSyncService, 
    EventSyncService,
    ConfigContextSyncService,
    ProfileSyncService,
    IpamSyncService,
)
from .custom_fields import ensure_custom_fields_exist


class SyncIncusJob(JobRunner):
    """
    Job to synchronize Incus instances to NetBox.
    
    Synchronizes:
    - Incus managed networks to NetBox Prefixes and VLANs
    - Incus profiles to NetBox Config Contexts (tag-based stacking)
    - Instances (VMs/containers) to VirtualMachine
    - NetBox Cluster (automatically created if Incus is in cluster mode)
    - Network Interfaces (with VLAN assignment)
    - IP Addresses (with Prefix/VRF linkage)
    - Virtual Disks
    - Instance logs (QEMU logs to Journal Entries)
    - Config Contexts (instance-specific overrides to local_context_data)
    """
    
    class Meta:
        name = "Incus Synchronization"

    def run(self, *args, **kwargs):
        self.logger.info("Initializing Incus synchronization...")
        
        # Create Custom Fields if necessary
        ensure_custom_fields_exist(logger=self.logger)
        
        # Retrieve configured hosts
        hosts = IncusHost.objects.filter(enabled=True)
        
        if not hosts.exists():
            self.logger.warning("No Incus host configured or enabled.")
            return

        # Initialize services
        instance_service = InstanceSyncService(logger=self.logger)
        network_service = NetworkSyncService(logger=self.logger)
        disk_service = DiskSyncService(logger=self.logger)
        event_service = EventSyncService(logger=self.logger)
        config_context_service = ConfigContextSyncService(logger=self.logger)
        profile_service = ProfileSyncService(logger=self.logger)
        ipam_service = IpamSyncService(logger=self.logger)
        
        # Prepare tags
        instance_service.setup()
        
        # Statistics
        stats = {
            'instances_created': 0,
            'instances_updated': 0,
            'instances_removed': 0,
            'interfaces_synced': 0,
            'ips_synced': 0,
            'disks_synced': 0,
            'logs_synced': 0,
            'config_contexts_created': 0,
            'config_contexts_updated': 0,
            'profiles_synced': 0,
            'profiles_created': 0,
            'profiles_updated': 0,
            'profiles_removed': 0,
            'prefixes_created': 0,
            'prefixes_updated': 0,
            'vlans_created': 0,
        }
        
        # Process each host
        for host in hosts:
            self._process_host(
                host, 
                instance_service, 
                network_service, 
                disk_service, 
                event_service,
                config_context_service,
                profile_service,
                ipam_service,
                stats
            )

        # Summary
        self.logger.info(
            f"Synchronization finished. "
            f"Instances: +{stats['instances_created']} ~{stats['instances_updated']} -{stats['instances_removed']} | "
            f"Interfaces: {stats['interfaces_synced']} | IPs: {stats['ips_synced']} | "
            f"Disks: {stats['disks_synced']} | Logs: {stats['logs_synced']} | "
            f"Profiles: +{stats['profiles_created']} ~{stats['profiles_updated']} -{stats['profiles_removed']} | "
            f"Contexts: +{stats['config_contexts_created']} ~{stats['config_contexts_updated']} | "
            f"Prefixes: +{stats['prefixes_created']} ~{stats['prefixes_updated']} | "
            f"VLANs: +{stats['vlans_created']}"
        )

    def _process_host(self, host, instance_service, network_service, disk_service, 
                      event_service, config_context_service, profile_service, 
                      ipam_service, stats):
        """
        Processes an Incus host.
        """
        self.logger.info(f"Processing host: {host.name} ({host.get_connection_type_display()})")
        
        try:
            # Connection to client
            client = IncusClient(host=host)
            
            # Connection test
            success, message, _ = client.test_connection()
            if not success:
                self.logger.error(f"  Connection failure: {message}")
                return
                
            self.logger.info(f"  {message}")
            
            # Log server info
            self._log_server_info(client)
            
            # Retrieve Incus cluster info
            cluster_info = self._get_cluster_info(client)
            
            # ====================================================
            # Phase 0: Sync Incus managed networks → Prefixes/VLANs
            # This MUST run before instance sync so that Prefixes
            # and VLANs exist when we assign them to interfaces.
            # ====================================================
            networks = client.get_networks()
            network_service.log_networks_info(networks)
            
            net_stats = ipam_service.sync_networks(networks, host)
            stats['prefixes_created'] += net_stats['prefixes_created']
            stats['prefixes_updated'] += net_stats['prefixes_updated']
            stats['vlans_created'] += net_stats['vlans_created']
            
            # ====================================================
            # Phase 0.5: Sync Incus profiles → NetBox Config Contexts
            # This MUST run before instance sync so that Config
            # Contexts and their tags exist when we assign profile
            # tags to VMs.
            # ====================================================
            profiles = client.get_profiles(recursion=1)
            profile_stats = profile_service.sync_profiles(profiles, host)
            stats['profiles_synced'] += profile_stats['profiles_synced']
            stats['profiles_created'] += profile_stats['profiles_created']
            stats['profiles_updated'] += profile_stats['profiles_updated']
            stats['profiles_removed'] += profile_stats['profiles_removed']
            
            # ====================================================
            # Phase 1: Instance sync
            # ====================================================
            instances = client.get_instances(recursion=2)
            self.logger.info(f"  > {len(instances)} instances found.")
            
            # Resolve NetBox Cluster
            cluster = instance_service.resolve_cluster(host, cluster_info)
            
            if cluster:
                self.logger.info(f"  NetBox Cluster: {cluster.name}")
            else:
                self.logger.info(f"  No cluster (VMs created without cluster)")
            
            # Collect UUIDs for deletion handling
            incus_instance_uuids = set()
            
            # Synchronize each instance
            for instance_data in instances:
                instance_name = instance_data.get('name')
                config = instance_data.get('config', {})
                incus_uuid = config.get('volatile.uuid', '')
                
                # Collect UUID
                if incus_uuid:
                    incus_instance_uuids.add(incus_uuid)
                
                # Instance Sync
                vm, created, updated = instance_service.sync_instance(
                    instance_data, cluster, host
                )
                
                if created:
                    stats['instances_created'] += 1
                elif updated:
                    stats['instances_updated'] += 1
                
                # Network Sync (interfaces + IPs)
                if vm:
                    iface_count, ip_count = network_service.sync_instance_network(
                        vm, instance_data, client
                    )
                    stats['interfaces_synced'] += iface_count
                    stats['ips_synced'] += ip_count
                    
                    # ====================================================
                    # Phase 2: VLAN assignment to interfaces + IP→Prefix linkage
                    # ====================================================
                    devices = instance_data.get('expanded_devices') or instance_data.get('devices', {})
                    self._sync_interface_vlans_and_ips(
                        vm, devices, host, ipam_service, stats
                    )
                    
                    # Disks Sync
                    disk_count = disk_service.sync_instance_disks(
                        vm, instance_data, client
                    )
                    stats['disks_synced'] += disk_count
                    
                    # Config Context Sync (instance-specific overrides to local_context_data)
                    cc_updated, cc_created = config_context_service.sync_instance_config_context(
                        vm, instance_data, host
                    )
                    if cc_created:
                        stats['config_contexts_created'] += 1
                    elif cc_updated:
                        stats['config_contexts_updated'] += 1
                    
                    # ====================================================
                    # Phase 3: Assign profile tags to VM
                    # This links the VM to the Config Contexts created
                    # in Phase 0.5 via NetBox's tag-based association.
                    # ====================================================
                    instance_profiles = instance_data.get('profiles', [])
                    profile_service.assign_profile_tags_to_vm(vm, instance_profiles)
            
            # Handle deletions (using UUIDs)
            deleted = instance_service.handle_deletions(cluster, host, incus_instance_uuids)
            stats['instances_removed'] += deleted
            
            # Instance logs synchronization (QEMU logs -> Journal Entries)
            self.logger.info(f"  Synchronizing instance logs...")
            logs_count = event_service.sync_events(host, client)
            stats['logs_synced'] += logs_count
                
        except Exception as e:
            self.logger.error(f"Error processing {host.name}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _sync_interface_vlans_and_ips(self, vm, devices, host, ipam_service, stats):
        """
        Post-sync step: assign VLANs to VM interfaces and link IPs to Prefixes/VRFs.
        
        This runs after NetworkSyncService has created the interfaces and IPs,
        so we can now enrich them with VLAN and VRF data.
        """
        from virtualization.models import VMInterface
        from ipam.models import IPAddress
        from django.contrib.contenttypes.models import ContentType
        
        vm_iface_ct = ContentType.objects.get_for_model(VMInterface)
        
        # Assign VLANs to interfaces
        for iface in VMInterface.objects.filter(virtual_machine=vm):
            # Find the matching device config
            device_name = iface.custom_field_data.get('incus_device_name', iface.name)
            device_config = devices.get(device_name, {})
            
            if device_config:
                ipam_service.assign_vlan_to_interface(iface, device_config, host)
        
        # Link IPs to Prefixes/VRFs
        for ip in IPAddress.objects.filter(
            assigned_object_type=vm_iface_ct,
            assigned_object_id__in=VMInterface.objects.filter(
                virtual_machine=vm
            ).values_list('pk', flat=True)
        ):
            ipam_service.link_ip_to_prefix(ip)
    
    def _log_server_info(self, client):
        """Logs Incus server information."""
        try:
            server_info = client.get_server_info()
            if server_info:
                env = server_info.get('environment', {})
                self.logger.info(
                    f"  Server: {env.get('server_name', 'unknown')} "
                    f"v{env.get('server_version', '?')} "
                    f"({env.get('kernel', 'unknown')} {env.get('kernel_version', '')})"
                )
        except Exception:
            pass
    
    def _get_cluster_info(self, client):
        """Retrieves Incus cluster info (or None if not clustered)."""
        try:
            cluster = client.get_cluster()
            if cluster and cluster.get('enabled'):
                members = client.get_cluster_members()
                return {
                    'enabled': True,
                    'server_name': cluster.get('server_name', ''),
                    'members': members,
                }
        except Exception:
            pass
        return None


class SyncEventsJob(JobRunner):
    """
    Job to synchronize only Incus instance logs (lighter sync).
    """
    
    class Meta:
        name = "Incus Logs Synchronization"
    
    def run(self, *args, **kwargs):
        self.logger.info("Starting Incus logs synchronization...")
        
        hosts = IncusHost.objects.filter(enabled=True)
        if not hosts.exists():
            self.logger.warning("No Incus host configured or enabled.")
            return
        
        event_service = EventSyncService(logger=self.logger)
        total_logs = 0
        
        for host in hosts:
            self.logger.info(f"Processing host: {host.name}")
            try:
                client = IncusClient(host=host)
                success, message, _ = client.test_connection()
                if not success:
                    self.logger.error(f"  Connection failure: {message}")
                    continue
                
                logs_count = event_service.sync_events(host, client)
                total_logs += logs_count
                
            except Exception as e:
                self.logger.error(f"Error processing {host.name}: {e}")
        
        self.logger.info(f"Logs synchronization finished. {total_logs} log entries synced.")