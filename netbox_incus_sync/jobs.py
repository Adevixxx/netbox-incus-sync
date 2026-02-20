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
    TenantSyncService,
)
from .custom_fields import ensure_custom_fields_exist


class SyncIncusJob(JobRunner):
    """
    Job to synchronize Incus instances to NetBox.
    
    Supports syncing all enabled hosts (default) or specific hosts
    by passing host_ids=[...] to enqueue().
    """
    
    class Meta:
        name = "Incus Synchronization"

    def run(self, *args, **kwargs):
        # Support filtering by specific host IDs (for single/multi-host sync)
        host_ids = kwargs.get('host_ids', None)
        
        if host_ids:
            hosts = IncusHost.objects.filter(pk__in=host_ids, enabled=True)
            host_names = ', '.join(hosts.values_list('name', flat=True))
            self.logger.info(f"Initializing Incus synchronization for: {host_names}")
        else:
            self.logger.info("Initializing Incus synchronization...")
            hosts = IncusHost.objects.filter(enabled=True)
        
        # Create Custom Fields if necessary
        ensure_custom_fields_exist(logger=self.logger)
        
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
        tenant_service = TenantSyncService(logger=self.logger)
        
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
            'tenants_created': 0,
            'tenants_removed': 0,
            'projects_synced': 0,
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
                tenant_service,
                stats
            )

        # Summary
        self.logger.info(
            f"Synchronization finished. "
            f"Projects: {stats['projects_synced']} | "
            f"Tenants: +{stats['tenants_created']} -{stats['tenants_removed']} | "
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
                      ipam_service, tenant_service, stats):
        """
        Processes an Incus host.
        
        Flow:
        1. Connect and gather server/cluster info
        2. Sync projects → Tenants (builds tenant_map)
        3. For each project:
           a. Sync networks (if features.networks=true for that project, else skip)
           b. Sync profiles (if features.profiles=true for that project, else skip)
           c. Sync instances (with tenant assignment)
           d. Sync disks, interfaces, IPs, config contexts per instance
        4. Handle deletions
        5. Sync logs
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
            
            # Log server info and retrieve Incus version
            incus_version = self._log_server_info(client)
            
            # Pass Incus version to instance service for Device custom field
            if incus_version:
                instance_service.set_incus_version(incus_version)
            
            # Retrieve Incus cluster info
            cluster_info = self._get_cluster_info(client)
            
            # ====================================================
            # Phase -1: Sync projects → Tenants
            # ====================================================
            projects = client.get_projects(recursion=1)
            
            if not projects:
                self.logger.info("  No projects found (or only default). Using default project.")
                projects = [{
                    'name': 'default',
                    'description': 'Default Incus project',
                    'config': {},
                }]
            
            # Filter projects if sync_projects is configured
            if host.sync_projects:
                projects = [p for p in projects if p.get('name') in host.sync_projects]
                self.logger.info(f"  Filtered to {len(projects)} project(s): {host.sync_projects}")
            
            tenant_result = tenant_service.sync_all_projects(projects, host=host)
            tenant_map = tenant_result['tenant_map']
            stats['tenants_created'] += tenant_result['tenants_created']
            stats['tenants_removed'] += tenant_result['tenants_removed']
            stats['projects_synced'] += len(tenant_map)
            
            self.logger.info(f"  > {len(tenant_map)} projects synced as tenants")
            
            # Resolve NetBox Cluster
            cluster = instance_service.resolve_cluster(host, cluster_info)
            
            if cluster:
                self.logger.info(f"  NetBox Cluster: {cluster.name}")
            else:
                self.logger.info(f"  No cluster (VMs created without cluster)")
            
            # Collect ALL UUIDs across all projects for deletion handling
            all_incus_uuids = set()
            
            # ====================================================
            # Process each project
            # ====================================================
            for project_data in projects:
                project_name = project_data.get('name', 'default')
                project_config = project_data.get('config', {})
                tenant = tenant_map.get(project_name)
                
                self.logger.info(f"  --- Project: {project_name} ---")
                self.logger.debug(f"    Tenant: {tenant}")
                
                features = {
                    'profiles': project_config.get('features.profiles', 'true' if project_name == 'default' else 'false').lower() == 'true',
                    'networks': project_config.get('features.networks', 'false').lower() == 'true',
                    'storage_volumes': project_config.get('features.storage.volumes', 'true' if project_name == 'default' else 'false').lower() == 'true',
                    'images': project_config.get('features.images', 'true' if project_name == 'default' else 'false').lower() == 'true',
                }
                
                # ====================================================
                # Phase 0: Sync networks for this project
                # ====================================================
                if features['networks'] or project_name == 'default':
                    networks = client.get_networks(project=project_name)
                    network_service.log_networks_info(networks)
                    
                    net_stats = ipam_service.sync_networks(networks, host)
                    stats['prefixes_created'] += net_stats['prefixes_created']
                    stats['prefixes_updated'] += net_stats['prefixes_updated']
                    stats['vlans_created'] += net_stats['vlans_created']
                else:
                    self.logger.info(f"    Networks inherited from default (features.networks=false)")
                
                # ====================================================
                # Phase 0.5: Sync profiles for this project
                # ====================================================
                if features['profiles'] or project_name == 'default':
                    profiles = client.get_profiles(recursion=1, project=project_name)
                    profile_stats = profile_service.sync_profiles(profiles, host)
                    stats['profiles_synced'] += profile_stats['profiles_synced']
                    stats['profiles_created'] += profile_stats['profiles_created']
                    stats['profiles_updated'] += profile_stats['profiles_updated']
                    stats['profiles_removed'] += profile_stats['profiles_removed']
                else:
                    self.logger.info(f"    Profiles inherited from default (features.profiles=false)")
                
                # ====================================================
                # Phase 1: Instance sync for this project
                # ====================================================
                instances = client.get_instances(recursion=2, project=project_name)

                project_created = 0
                project_updated = 0
                project_ifaces = 0
                project_ips = 0
                project_disks = 0
                
                for instance_data in instances:
                    config = instance_data.get('config', {})
                    incus_uuid = config.get('volatile.uuid', '')
                    
                    if incus_uuid:
                        all_incus_uuids.add(incus_uuid)
                    
                    vm, created, updated = instance_service.sync_instance(
                        instance_data, cluster, host, 
                        tenant=tenant, project=project_name
                    )
                    
                    if created:
                        project_created += 1
                        stats['instances_created'] += 1
                    elif updated:
                        project_updated += 1
                        stats['instances_updated'] += 1
                    
                    if vm:
                        iface_count, ip_count = network_service.sync_instance_network(
                            vm, instance_data, client
                        )
                        project_ifaces += iface_count
                        project_ips += ip_count
                        stats['interfaces_synced'] += iface_count
                        stats['ips_synced'] += ip_count
                        
                        # VLAN assignment + IP→Prefix linkage
                        devices = instance_data.get('expanded_devices') or instance_data.get('devices', {})
                        self._sync_interface_vlans_and_ips(
                            vm, devices, host, ipam_service, stats
                        )
                        
                        # Disks Sync
                        disk_count = disk_service.sync_instance_disks(
                            vm, instance_data, client
                        )
                        project_disks += disk_count
                        stats['disks_synced'] += disk_count
                        
                        # Config Context Sync
                        cc_updated, cc_created = config_context_service.sync_instance_config_context(
                            vm, instance_data, host
                        )
                        if cc_created:
                            stats['config_contexts_created'] += 1
                        elif cc_updated:
                            stats['config_contexts_updated'] += 1
                        
                        # Assign profile tags to VM
                        instance_profiles = instance_data.get('profiles', [])
                        profile_service.assign_profile_tags_to_vm(vm, instance_profiles)
                
                self.logger.info(
                    f"    Project '{project_name}': "
                    f"+{project_created} ~{project_updated} instances, "
                    f"{project_ifaces} ifaces, {project_ips} IPs, {project_disks} disks"
                )
            
            # ====================================================
            # Handle deletions (using UUIDs across all projects)
            # ====================================================
            deleted = instance_service.handle_deletions(cluster, host, all_incus_uuids)
            stats['instances_removed'] += deleted
            
            # Instance logs synchronization
            logs_count = event_service.sync_events(host, client)
            stats['logs_synced'] += logs_count
                
        except Exception as e:
            self.logger.error(f"Error processing {host.name}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
    
    def _sync_interface_vlans_and_ips(self, vm, devices, host, ipam_service, stats):
        """
        Post-sync step: assign VLANs to VM interfaces and link IPs to Prefixes/VRFs.
        """
        from virtualization.models import VMInterface
        from ipam.models import IPAddress
        from django.contrib.contenttypes.models import ContentType
        
        vm_iface_ct = ContentType.objects.get_for_model(VMInterface)
        
        for iface in VMInterface.objects.filter(virtual_machine=vm):
            device_name = iface.custom_field_data.get('incus_device_name', iface.name)
            device_config = devices.get(device_name, {})
            
            if device_config:
                ipam_service.assign_vlan_to_interface(iface, device_config, host)
        
        for ip in IPAddress.objects.filter(
            assigned_object_type=vm_iface_ct,
            assigned_object_id__in=VMInterface.objects.filter(
                virtual_machine=vm
            ).values_list('pk', flat=True)
        ):
            ipam_service.link_ip_to_prefix(ip)
    
    def _log_server_info(self, client):
        """
        Logs Incus server information and returns the server version.
        
        Returns:
            str or None: The Incus server version, or None if unavailable.
        """
        try:
            server_info = client.get_server_info()
            if server_info:
                env = server_info.get('environment', {})
                version = env.get('server_version', '')
                self.logger.info(
                    f"  Server: {env.get('server_name', 'unknown')} "
                    f"v{version or '?'} "
                    f"({env.get('kernel', 'unknown')} {env.get('kernel_version', '')})"
                )
                return version or None
        except Exception:
            pass
        return None
    
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
        
        self.logger.info(f"Logs synchronization finished. Total: {total_logs} log entries")