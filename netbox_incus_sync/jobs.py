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
)
from .custom_fields import ensure_custom_fields_exist


class SyncIncusJob(JobRunner):
    """
    Job to synchronize Incus instances to NetBox.
    
    Synchronizes:
    - Instances (VMs/containers) to VirtualMachine
    - NetBox Cluster (automatically created if Incus is in cluster mode)
    - Network Interfaces
    - IP Addresses
    - Virtual Disks
    - Events (to Journal Entries)
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
            'events_synced': 0,
        }
        
        # Process each host
        for host in hosts:
            self._process_host(
                host, 
                instance_service, 
                network_service, 
                disk_service, 
                event_service,
                stats
            )

        # Summary
        self.logger.info(
            f"Synchronization finished. "
            f"Instances: +{stats['instances_created']} ~{stats['instances_updated']} -{stats['instances_removed']} | "
            f"Interfaces: {stats['interfaces_synced']} | IPs: {stats['ips_synced']} | "
            f"Disks: {stats['disks_synced']} | Events: {stats['events_synced']}"
        )

    def _process_host(self, host, instance_service, network_service, disk_service, 
                      event_service, stats):
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
            
            # Retrieve instances with recursion=2 to get expanded_config and state
            instances = client.get_instances(recursion=2)
            self.logger.info(f"  > {len(instances)} instances found.")
            
            # Resolve NetBox Cluster
            # - If Incus is in cluster mode -> create/use a NetBox Cluster
            # - Else -> use default_cluster or None
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
                
                # Network Sync
                if vm:
                    iface_count, ip_count = network_service.sync_instance_network(
                        vm, instance_data, client
                    )
                    stats['interfaces_synced'] += iface_count
                    stats['ips_synced'] += ip_count
                    
                    # Disks Sync
                    disk_count = disk_service.sync_instance_disks(
                        vm, instance_data, client
                    )
                    stats['disks_synced'] += disk_count
            
            # Handle deletions (using UUIDs)
            deleted = instance_service.handle_deletions(cluster, host, incus_instance_uuids)
            stats['instances_removed'] += deleted
            
            # Events synchronization
            self.logger.info(f"  Synchronizing events...")
            events_count = event_service.sync_events(host, client, since_minutes=60)
            stats['events_synced'] += events_count
            
            # Log Incus networks (informative)
            networks = client.get_networks()
            network_service.log_networks_info(networks)
                
        except Exception as e:
            self.logger.error(f"Error processing {host.name}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _get_cluster_info(self, client):
        """
        Retrieves Incus cluster information.
        
        Returns:
            dict: {'enabled': bool, 'server_name': str, 'member_count': int} or None
        """
        try:
            cluster_data = client.get_cluster()
            if cluster_data and cluster_data.get('enabled'):
                # Count members if possible
                members = client.get_cluster_members()
                member_count = len(members) if members else 0
                
                self.logger.info(f"  Incus cluster mode enabled: {cluster_data.get('server_name')} ({member_count} members)")
                
                return {
                    'enabled': True,
                    'server_name': cluster_data.get('server_name', ''),
                    'member_count': member_count,
                }
            else:
                self.logger.info(f"  Standalone mode (no Incus cluster)")
                return {'enabled': False}
        except Exception as e:
            self.logger.debug(f"  Unable to retrieve cluster info: {e}")
            return None

    def _log_server_info(self, client):
        """Logs Incus server information."""
        try:
            server_info = client.get_server_info()
            if server_info:
                env = server_info.get('environment', {})
                self.logger.info(f"  Server: {env.get('server_name', 'N/A')}")
                self.logger.info(f"  Version: {env.get('server_version', 'N/A')}")
        except Exception as e:
            self.logger.warning(f"  Unable to retrieve server info: {e}")


class SyncEventsJob(JobRunner):
    """
    Job dedicated to Incus events synchronization.
    
    Can be executed more frequently than the full sync job
    to capture events quickly.
    """
    
    class Meta:
        name = "Incus Events Synchronization"

    def run(self, *args, **kwargs):
        # Optional parameter: time window in minutes
        since_minutes = kwargs.get('since_minutes', 30)
        
        self.logger.info(f"Synchronizing Incus events (last {since_minutes} min)...")
        
        hosts = IncusHost.objects.filter(enabled=True)
        
        if not hosts.exists():
            self.logger.warning("No Incus host configured or enabled.")
            return

        event_service = EventSyncService(logger=self.logger)
        total_events = 0
        
        for host in hosts:
            self.logger.info(f"  Host: {host.name}")
            
            try:
                client = IncusClient(host=host)
                
                success, message, _ = client.test_connection()
                if not success:
                    self.logger.error(f"    Connection failure: {message}")
                    continue
                
                events_count = event_service.sync_events(host, client, since_minutes)
                total_events += events_count
                
            except Exception as e:
                self.logger.error(f"    Error: {e}")
        
        self.logger.info(f"Finished. {total_events} events synchronized.")
