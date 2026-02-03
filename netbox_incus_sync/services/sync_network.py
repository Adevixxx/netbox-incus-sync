"""
Incus instance network synchronization service to NetBox.

Compatible with NetBox 4.2+ where MAC addresses are separate objects.
"""

from virtualization.models import VMInterface
from ipam.models import IPAddress
from dcim.models import MACAddress
from django.contrib.contenttypes.models import ContentType


class NetworkSyncService:
    """
    Service to synchronize network interfaces and IPs of Incus instances.
    """
    
    def __init__(self, logger=None):
        """
        Initializes the service.
        
        Args:
            logger: Logger for messages (optional)
        """
        self.logger = logger
        self._vminterface_ct = None
    
    def log(self, level, message):
        """Log a message if logger is available."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    @property
    def vminterface_content_type(self):
        """Returns ContentType for VMInterface (cached)."""
        if self._vminterface_ct is None:
            self._vminterface_ct = ContentType.objects.get_for_model(VMInterface)
        return self._vminterface_ct
    
    def sync_instance_network(self, vm, instance_data, client):
        """
        Synchronizes network interfaces and IPs of an instance.
        
        Args:
            vm: NetBox VirtualMachine instance
            instance_data: Incus instance data
            client: Incus Client for additional requests
        
        Returns:
            tuple: (interfaces_count, ips_count)
        """
        interfaces_synced = 0
        ips_synced = 0
        
        # Get network state
        network_state = self._get_network_state(vm.name, instance_data, client)
        
        if not network_state:
            return 0, 0
        
        # Get devices for connection info (bridge, parent)
        devices = instance_data.get('expanded_devices', {})
        if not devices:
            devices = instance_data.get('devices', {})
        
        # To track primary IP candidates
        primary_ip4_candidate = None
        primary_ip6_candidate = None
        
        # Iterate over interfaces
        current_iface_names = set()
        
        for iface_name, iface_data in network_state.items():
            # Ignore loopback
            if iface_name == 'lo':
                continue
            
            current_iface_names.add(iface_name)
            
            # Get corresponding device info
            device_config = devices.get(iface_name, {})
            
            # Sync interface
            interface, iface_created = self._sync_interface(
                vm, iface_name, iface_data, device_config
            )
            interfaces_synced += 1
            
            if iface_created:
                self.log('info', f"    Interface created: {iface_name}")
            
            # Sync MAC address (NetBox 4.2+) and set as primary
            hwaddr = iface_data.get('hwaddr', '')
            if hwaddr and hwaddr != '00:00:00:00:00:00':
                self._sync_mac_address(interface, hwaddr)
            
            # Sync IPs and get candidates for primary IP
            ip4, ip6, ip_count = self._sync_interface_ips(interface, iface_data, vm.name)
            ips_synced += ip_count
            
            # Keep the first global IP found as candidate
            if ip4 and not primary_ip4_candidate:
                primary_ip4_candidate = ip4
            if ip6 and not primary_ip6_candidate:
                primary_ip6_candidate = ip6
        
        # Set primary IPs for the VM
        self._set_primary_ips(vm, primary_ip4_candidate, primary_ip6_candidate)
        
        # Cleanup obsolete interfaces
        self._cleanup_old_interfaces(vm, current_iface_names)
        
        return interfaces_synced, ips_synced
    
    def _get_network_state(self, vm_name, instance_data, client):
        """
        Retrieves the network state of an instance.
        
        Args:
            vm_name: Instance name
            instance_data: Instance data (may contain state)
            client: Incus Client
        
        Returns:
            dict: Network state or None
        """
        # First try from instance_data
        state = instance_data.get('state', {})
        network_state = state.get('network', {})
        
        if network_state:
            return network_state
        
        # Otherwise, separate request
        try:
            instance_state = client.get_instance_state(vm_name)
            if instance_state:
                return instance_state.get('network', {})
        except Exception as e:
            self.log('warning', f"    Unable to retrieve network state for {vm_name}: {e}")
        
        return None
    
    def _sync_interface(self, vm, iface_name, iface_data, device_config):
        """
        Synchronizes a network interface.
        
        Note: In NetBox 4.2+, mac_address is no longer a direct field.
        A separate MACAddress object must be created.
        
        Args:
            vm: NetBox VirtualMachine
            iface_name: Interface name (eth0, etc.)
            iface_data: Network state data from Incus
            device_config: Device configuration from expanded_devices
        
        Returns:
            tuple: (interface, created)
        """
        iface_state = iface_data.get('state', 'down')
        mtu = iface_data.get('mtu', None)
        host_name = iface_data.get('host_name', '')  # vethXXX on host side
        
        # Connection info from device_config
        network = device_config.get('network', '')  # Managed bridge (incusbr0)
        parent = device_config.get('parent', '')    # Direct parent interface
        nictype = device_config.get('nictype', '')  # bridged, macvlan, etc.
        
        # Effective bridge is either 'network' or 'parent'
        bridge = network or parent
        
        # Build simplified description (details are in custom fields)
        description = f"Synced from Incus | State: {iface_state}"
        
        defaults = {
            'enabled': iface_state == 'up',
            'description': description,
        }
        
        # MTU if available
        if mtu:
            defaults['mtu'] = mtu
        
        interface, created = VMInterface.objects.update_or_create(
            virtual_machine=vm,
            name=iface_name,
            defaults=defaults
        )
        
        # Update Custom Fields
        self._update_interface_custom_fields(interface, bridge, host_name, nictype)
        
        return interface, created
    
    def _update_interface_custom_fields(self, interface, bridge, host_name, nictype):
        """
        Updates Interface Custom Fields.
        
        Args:
            interface: NetBox VMInterface
            bridge: Incus bridge/network name
            host_name: veth interface on host side
            nictype: NIC type
        """
        updated = False
        
        # Incus Bridge
        if bridge and interface.custom_field_data.get('incus_bridge') != bridge:
            interface.custom_field_data['incus_bridge'] = bridge
            updated = True
        
        # Host Interface (veth)
        if host_name and interface.custom_field_data.get('incus_host_interface') != host_name:
            interface.custom_field_data['incus_host_interface'] = host_name
            updated = True
        
        # NIC Type
        if nictype and interface.custom_field_data.get('incus_nic_type') != nictype:
            interface.custom_field_data['incus_nic_type'] = nictype
            updated = True
        
        if updated:
            interface.save()
    
    def _sync_mac_address(self, interface, hwaddr):
        """
        Synchronizes the MAC address of an interface (NetBox 4.2+).
        
        In NetBox 4.2+, MAC addresses are separate objects
        linked to interfaces via a generic relation.
        This method creates the MAC and sets it as primary.
        
        Args:
            interface: VMInterface instance
            hwaddr: MAC address (string)
        """
        try:
            # Normalize MAC address (upper case)
            hwaddr_normalized = hwaddr.upper()
            
            # Check if this interface already has this MAC as primary
            current_primary = interface.primary_mac_address
            if current_primary and str(current_primary.mac_address).upper() == hwaddr_normalized:
                # Already configured correctly
                return
            
            # Check if this MAC already exists and is assigned to this interface
            existing_mac = MACAddress.objects.filter(
                mac_address=hwaddr_normalized,
                assigned_object_type=self.vminterface_content_type,
                assigned_object_id=interface.pk
            ).first()
            
            if existing_mac:
                # MAC exists and is already assigned to this interface
                mac_obj = existing_mac
            else:
                # Check if this MAC exists but assigned elsewhere
                existing_mac_elsewhere = MACAddress.objects.filter(
                    mac_address=hwaddr_normalized
                ).first()
                
                if existing_mac_elsewhere:
                    # Reassign to this interface
                    existing_mac_elsewhere.assigned_object_type = self.vminterface_content_type
                    existing_mac_elsewhere.assigned_object_id = interface.pk
                    existing_mac_elsewhere.save()
                    mac_obj = existing_mac_elsewhere
                    self.log('info', f"    MAC reassigned: {hwaddr_normalized}")
                else:
                    # Create new MAC
                    mac_obj = MACAddress.objects.create(
                        mac_address=hwaddr_normalized,
                        assigned_object_type=self.vminterface_content_type,
                        assigned_object_id=interface.pk,
                        description=f"Synced from Incus - {interface.virtual_machine.name}",
                    )
                    self.log('info', f"    MAC created: {hwaddr_normalized}")
            
            # Set as primary only if not already done
            if interface.primary_mac_address_id != mac_obj.pk:
                interface.primary_mac_address = mac_obj
                interface.save()
                
        except Exception as e:
            self.log('warning', f"    Error syncing MAC {hwaddr}: {e}")
    
    def _sync_interface_ips(self, interface, iface_data, vm_name):
        """
        Synchronizes IP addresses of an interface.
        
        Returns:
            tuple: (first_ipv_4, first_ipv_6, count)
                - first_ipv_4: First global IPv4 found (or None)
                - first_ipv_6: First global IPv6 found (or None)
                - count: Total number of IPs synchronized
        """
        ips_synced = 0
        first_ipv4 = None
        first_ipv6 = None
        
        addresses = iface_data.get('addresses', [])
        
        for addr_info in addresses:
            ip_address = addr_info.get('address', '')
            ip_netmask = addr_info.get('netmask', '')
            ip_scope = addr_info.get('scope', '')
            ip_family = addr_info.get('family', '')
            
            # Ignore link-local and localhost addresses
            if ip_scope in ('link', 'local'):
                continue
            
            if not ip_address or not ip_netmask:
                continue
            
            # Build CIDR address
            ip_cidr = f"{ip_address}/{ip_netmask}"
            
            try:
                ip_obj = self._sync_ip_address(ip_cidr, interface, vm_name)
                if ip_obj:
                    ips_synced += 1
                    
                    # Keep the first IP of each family as primary candidate
                    if ip_family == 'inet' and first_ipv4 is None:
                        first_ipv4 = ip_obj
                    elif ip_family == 'inet6' and first_ipv6 is None:
                        first_ipv6 = ip_obj
                        
            except Exception as e:
                self.log('warning', f"    Error syncing IP {ip_cidr}: {e}")
        
        return first_ipv4, first_ipv6, ips_synced
    
    def _sync_ip_address(self, ip_cidr, interface, vm_name):
        """
        Synchronizes an IP address.
        
        Returns:
            IPAddress or None
        """
        # Check first if this IP already exists
        existing_ip = IPAddress.objects.filter(address=ip_cidr).first()
        
        if existing_ip:
            # Check if it is already assigned to this interface
            if (existing_ip.assigned_object_id == interface.pk and 
                existing_ip.assigned_object_type == self.vminterface_content_type):
                # Already correctly assigned
                return existing_ip
            
            # Reassign to this interface
            existing_ip.assigned_object_type = self.vminterface_content_type
            existing_ip.assigned_object_id = interface.pk
            existing_ip.save()
            return existing_ip
        
        # Create new IP
        ip_obj = IPAddress.objects.create(
            address=ip_cidr,
            assigned_object_type=self.vminterface_content_type,
            assigned_object_id=interface.pk,
            description=f"Incus instance: {vm_name} ({interface.name})",
        )
        
        self.log('info', f"    IP created: {ip_cidr} on {interface.name}")
        return ip_obj
    
    def _set_primary_ips(self, vm, ip4, ip6):
        """
        Sets the primary IPs for the VM.
        
        Correctly handles cases where the IP is already primary on another VM
        (which can happen during a rename or rebuild).
        
        Args:
            vm: VirtualMachine instance
            ip4: Candidate IPv4 IPAddress (or None)
            ip6: Candidate IPv6 IPAddress (or None)
        """
        from virtualization.models import VirtualMachine
        
        updated = False
        
        # Set primary IPv4
        if ip4 and vm.primary_ip4_id != ip4.pk:
            # Check if this IP is already primary on another VM
            other_vm = VirtualMachine.objects.filter(primary_ip4=ip4).exclude(pk=vm.pk).first()
            if other_vm:
                # Remove primary IP from other VM
                self.log('warning', f"    IP {ip4.address} was primary on {other_vm.name}, reassigning...")
                other_vm.primary_ip4 = None
                other_vm.save()
            
            vm.primary_ip4 = ip4
            updated = True
            self.log('info', f"    Primary v4 IP: {ip4.address}")
        
        # Set primary IPv6
        if ip6 and vm.primary_ip6_id != ip6.pk:
            # Check if this IP is already primary on another VM
            other_vm = VirtualMachine.objects.filter(primary_ip6=ip6).exclude(pk=vm.pk).first()
            if other_vm:
                # Remove primary IP from other VM
                self.log('warning', f"    IP {ip6.address} was primary on {other_vm.name}, reassigning...")
                other_vm.primary_ip6 = None
                other_vm.save()
            
            vm.primary_ip6 = ip6
            updated = True
            self.log('info', f"    Primary v6 IP: {ip6.address}")
        
        if updated:
            vm.save()
    
    def _cleanup_old_interfaces(self, vm, current_iface_names):
        """
        Deletes interfaces that no longer exist.
        
        Args:
            vm: VirtualMachine instance
            current_iface_names: Set of current interface names
        """
        old_interfaces = VMInterface.objects.filter(
            virtual_machine=vm
        ).exclude(name__in=current_iface_names)
        
        for old_iface in old_interfaces:
            self.log('info', f"    Interface deleted: {old_iface.name}")
            old_iface.delete()
    
    def log_networks_info(self, networks):
        """
        Logs information about Incus networks.
        
        Args:
            networks: List of networks from Incus API
        """
        if not networks:
            return
        
        self.log('info', f"  Incus Networks: {len(networks)}")
        for net in networks:
            net_name = net.get('name', 'unknown')
            net_type = net.get('type', 'unknown')
            managed = net.get('managed', False)
            config = net.get('config', {})
            ipv4 = config.get('ipv4.address', 'N/A')
            self.log('info', f"    - {net_name} ({net_type}, managed={managed}, IPv4={ipv4})")