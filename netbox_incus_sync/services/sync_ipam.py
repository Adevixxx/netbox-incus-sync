"""
Incus IPAM synchronization service — Prefixes, VLANs, VRFs.

This service synchronizes Incus managed networks into NetBox IPAM objects:
- Incus managed network → NetBox Prefix (IPv4 and/or IPv6)
- Incus NIC device with vlan → NetBox VLAN
- VLAN ↔ Prefix association
- VMInterface ↔ VLAN assignment (untagged_vlan / tagged_vlans)
- IPAddress ↔ Prefix/VRF linkage
"""

import netaddr

from ipam.models import Prefix, VLAN, VRF, IPAddress
from virtualization.models import VMInterface
from django.contrib.contenttypes.models import ContentType
from extras.models import Tag


class IpamSyncService:
    """IPAM synchronization service for Incus networks."""
    
    def __init__(self, logger=None):
        self.logger = logger
        self._managed_tag = None
        self._vminterface_ct = None
        # Cache: incus network name → {'prefixes_v4': Prefix, 'prefixes_v6': Prefix, 'vlan': VLAN}
        self._network_cache = {}
    
    def log(self, level, message):
        if self.logger:
            getattr(self.logger, level)(message)
    
    @property
    def managed_tag(self):
        """Gets or creates the 'incus-managed' tag."""
        if self._managed_tag is None:
            self._managed_tag, _ = Tag.objects.get_or_create(
                slug='incus-managed',
                defaults={'name': 'Incus Managed'}
            )
        return self._managed_tag
    
    @property
    def vminterface_content_type(self):
        if self._vminterface_ct is None:
            self._vminterface_ct = ContentType.objects.get_for_model(VMInterface)
        return self._vminterface_ct
    
    # ========================================================================
    # Phase 1: Sync Incus managed networks → Prefixes (+ VLANs if applicable)
    # ========================================================================
    
    def sync_networks(self, networks, host):
        """
        Synchronizes Incus managed networks to NetBox Prefixes and VLANs.
        
        Called once per host, before instance sync, so that Prefixes/VLANs
        exist when we later assign them to interfaces and IPs.
        
        Args:
            networks: List of Incus network dicts from client.get_networks()
            host: IncusHost instance
            
        Returns:
            dict: Stats {prefixes_created, prefixes_updated, vlans_created}
        """
        stats = {
            'prefixes_created': 0,
            'prefixes_updated': 0,
            'vlans_created': 0,
        }
        
        for net_data in networks:
            if not net_data.get('managed', False):
                continue
            
            net_name = net_data.get('name', '')
            net_type = net_data.get('type', '')
            config = net_data.get('config', {})
            description = net_data.get('description', '')
            
            self.log('debug', f"    Syncing network: {net_name} ({net_type})")
            
            cache_entry = {
                'prefix_v4': None,
                'prefix_v6': None,
                'vlan': None,
            }
            
            # --- IPv4 Prefix ---
            # Sources of IPv4 CIDR (in priority order):
            #   1. ipv4.address  → bridges, OVN networks (e.g. "10.43.252.1/24")
            #   2. ipv4.gateway  → physical uplinks for OVN (e.g. "172.31.254.1/24")
            ipv4_cidr = config.get('ipv4.address', '')
            if not ipv4_cidr or ipv4_cidr == 'none':
                ipv4_cidr = config.get('ipv4.gateway', '')
            
            if ipv4_cidr and ipv4_cidr != 'none':
                prefix_obj, created = self._sync_prefix(
                    cidr=ipv4_cidr,
                    network_name=net_name,
                    network_type=net_type,
                    description=description,
                    config=config,
                    host=host,
                    family='ipv4',
                )
                if prefix_obj:
                    cache_entry['prefix_v4'] = prefix_obj
                    if created:
                        stats['prefixes_created'] += 1
                    else:
                        stats['prefixes_updated'] += 1
            
            # --- IPv6 Prefix ---
            # Same logic: ipv6.address first, then ipv6.gateway for uplinks
            ipv6_cidr = config.get('ipv6.address', '')
            if not ipv6_cidr or ipv6_cidr == 'none':
                ipv6_cidr = config.get('ipv6.gateway', '')
            
            if ipv6_cidr and ipv6_cidr != 'none':
                prefix_obj, created = self._sync_prefix(
                    cidr=ipv6_cidr,
                    network_name=net_name,
                    network_type=net_type,
                    description=description,
                    config=config,
                    host=host,
                    family='ipv6',
                )
                if prefix_obj:
                    cache_entry['prefix_v6'] = prefix_obj
                    if created:
                        stats['prefixes_created'] += 1
                    else:
                        stats['prefixes_updated'] += 1
            
            # --- VLAN from network config (bridge.external_interfaces or raw.dnsmasq) ---
            # Incus managed networks can themselves have a VLAN parent:
            #   config: { "vlan.id": "100" } (for OVN) or maas.subnet.ipv4
            # This is rare but we handle it.
            vlan_id = config.get('vlan.id', '')
            if vlan_id:
                vlan_obj, vlan_created = self._sync_vlan(
                    vid=int(vlan_id),
                    name=f"incus-{net_name}",
                    network_name=net_name,
                    host=host,
                )
                if vlan_obj:
                    cache_entry['vlan'] = vlan_obj
                    if vlan_created:
                        stats['vlans_created'] += 1
                    
                    # Associate VLAN to prefixes
                    self._associate_vlan_to_prefix(vlan_obj, cache_entry['prefix_v4'])
                    self._associate_vlan_to_prefix(vlan_obj, cache_entry['prefix_v6'])
            
            self._network_cache[net_name] = cache_entry
        
        self.log('info', 
            f"  Networks sync: {stats['prefixes_created']} prefixes created, "
            f"{stats['prefixes_updated']} updated, {stats['vlans_created']} VLANs created"
        )
        
        return stats
    
    def _sync_prefix(self, cidr, network_name, network_type, description, config, host, family='ipv4'):
        """
        Creates or updates a NetBox Prefix from an Incus network address.
        
        Incus gives us the gateway address (e.g. "10.0.0.1/24"), but the NetBox
        Prefix should be the network address (e.g. "10.0.0.0/24").
        
        Args:
            cidr: IP/mask from Incus config (e.g. "10.0.0.1/24")
            network_name: Incus network name
            network_type: Incus network type (bridge, ovn, etc.)
            description: Network description
            config: Full Incus network config dict
            host: IncusHost instance
            family: 'ipv4' or 'ipv6'
            
        Returns:
            tuple: (Prefix, created: bool)
        """
        try:
            # Parse the CIDR — Incus gives gateway IP, we need network prefix
            ip_network = netaddr.IPNetwork(cidr)
            prefix_cidr = str(ip_network.cidr)  # "10.0.0.1/24" → "10.0.0.0/24"
            
            is_nat = config.get(f'{family}.nat', 'false') == 'true'
            
            # Build description
            prefix_description = (
                f"Incus network: {network_name} ({network_type})"
            )
            if description:
                prefix_description += f" — {description}"
            if is_nat:
                prefix_description += " [NAT]"
            
            # Add OVN ranges if present (useful for physical uplinks)
            ovn_ranges = config.get(f'{family}.ovn.ranges', '')
            if ovn_ranges:
                prefix_description += f" [OVN pool: {ovn_ranges}]"
            
            # Add DNS info if present
            dns_domain = config.get('dns.domain', '')
            if dns_domain:
                prefix_description += f" [DNS: {dns_domain}]"
            
            # Try to find existing prefix with this CIDR
            # We match on exact prefix to avoid conflicts
            existing = Prefix.objects.filter(
                prefix=prefix_cidr,
                description__contains=f"Incus network: {network_name}",
            ).first()
            
            if not existing:
                # Also check without description filter (user may have pre-created it)
                existing = Prefix.objects.filter(prefix=prefix_cidr).first()
            
            if existing:
                # Update description if it was created by us
                updated = False
                if f"Incus network:" in (existing.description or ''):
                    if existing.description != prefix_description:
                        existing.description = prefix_description
                        updated = True
                
                # Ensure tag
                if self.managed_tag not in existing.tags.all():
                    existing.tags.add(self.managed_tag)
                    updated = True
                
                if updated:
                    existing.save()
                    self.log('debug', f"    Prefix updated: {prefix_cidr} ({network_name})")
                else:
                    self.log('debug', f"    Prefix exists: {prefix_cidr} ({network_name})")
                
                return existing, False
            
            # Create new prefix
            prefix_obj = Prefix.objects.create(
                prefix=prefix_cidr,
                description=prefix_description,
                is_pool=True,  # Incus managed networks act as IP pools
            )
            prefix_obj.tags.add(self.managed_tag)
            
            self.log('info', f"    Prefix created: {prefix_cidr} (from {network_name})")
            return prefix_obj, True
            
        except (netaddr.AddrFormatError, ValueError) as e:
            self.log('warning', f"    Invalid CIDR '{cidr}' for network {network_name}: {e}")
            return None, False
    
    # ========================================================================
    # Phase 2: Sync NIC device VLANs
    # ========================================================================
    
    def sync_device_vlan(self, device_config, host):
        """
        Syncs a VLAN from an Incus NIC device config if it has a vlan tag.
        
        Called per NIC device during instance network sync.
        
        Args:
            device_config: Incus device config dict (type=nic)
            host: IncusHost instance
            
        Returns:
            VLAN or None
        """
        vlan_str = device_config.get('vlan', '')
        if not vlan_str:
            return None
        
        try:
            vid = int(vlan_str)
        except (ValueError, TypeError):
            self.log('warning', f"    Invalid VLAN ID: {vlan_str}")
            return None
        
        # Determine a name from the network or parent
        network_name = device_config.get('network', '') or device_config.get('parent', '')
        vlan_name = f"incus-{network_name}-vlan{vid}" if network_name else f"incus-vlan{vid}"
        
        vlan_obj, created = self._sync_vlan(
            vid=vid,
            name=vlan_name,
            network_name=network_name,
            host=host,
        )
        
        return vlan_obj
    
    def _sync_vlan(self, vid, name, network_name, host):
        """
        Creates or finds a VLAN in NetBox.
        
        Args:
            vid: VLAN ID (1-4094)
            name: VLAN name
            network_name: Source Incus network name
            host: IncusHost instance
            
        Returns:
            tuple: (VLAN, created: bool)
        """
        if vid < 1 or vid > 4094:
            self.log('warning', f"    VLAN ID {vid} out of range, skipping")
            return None, False
        
        # Try to find by VID first
        existing = VLAN.objects.filter(vid=vid, name=name).first()
        if not existing:
            # Also match by VID alone if tagged as incus-managed
            existing = VLAN.objects.filter(
                vid=vid, 
                tags=self.managed_tag
            ).first()
        
        if existing:
            self.log('debug', f"    VLAN exists: {existing.name} (VID {vid})")
            return existing, False
        
        # Check if a VLAN with this VID exists at all (user-created)
        any_existing = VLAN.objects.filter(vid=vid).first()
        if any_existing:
            self.log('debug', f"    Using existing VLAN: {any_existing.name} (VID {vid})")
            return any_existing, False
        
        # Create new VLAN
        vlan_obj = VLAN.objects.create(
            vid=vid,
            name=name,
            description=f"Incus network: {network_name} (auto-created)",
        )
        vlan_obj.tags.add(self.managed_tag)
        
        self.log('info', f"    VLAN created: {name} (VID {vid})")
        return vlan_obj, True
    
    def _associate_vlan_to_prefix(self, vlan, prefix):
        """Associates a VLAN to a Prefix if not already done."""
        if not vlan or not prefix:
            return
        
        if prefix.vlan_id != vlan.pk:
            prefix.vlan = vlan
            prefix.save(update_fields=['vlan'])
            self.log('debug', f"    Prefix {prefix.prefix} linked to VLAN {vlan.name}")
    
    # ========================================================================
    # Phase 3: Link VMInterfaces to VLANs
    # ========================================================================
    
    def assign_vlan_to_interface(self, interface, device_config, host):
        """
        Assigns VLAN(s) to a VMInterface based on the Incus NIC device config.
        
        Logic:
        - If device has a 'vlan' tag → find/create VLAN, set as untagged_vlan
        - If device is a trunk (multiple VLANs) → add to tagged_vlans
        - Otherwise → no VLAN assignment
        
        Args:
            interface: NetBox VMInterface instance
            device_config: Incus device config dict
            host: IncusHost instance
            
        Returns:
            bool: True if interface was modified
        """
        vlan_str = device_config.get('vlan', '')
        
        if not vlan_str:
            return False
        
        vlan_obj = self.sync_device_vlan(device_config, host)
        if not vlan_obj:
            return False
        
        updated = False
        
        # Set mode to 'access' and assign untagged VLAN
        if interface.mode != 'access':
            interface.mode = 'access'
            updated = True
        
        if interface.untagged_vlan_id != vlan_obj.pk:
            interface.untagged_vlan = vlan_obj
            updated = True
        
        if updated:
            interface.save()
            self.log('info', f"    Interface {interface.name}: VLAN {vlan_obj.vid} assigned (access mode)")
        
        return updated
    
    # ========================================================================
    # Phase 4: Link IPAddresses to Prefixes/VRFs
    # ========================================================================
    
    def link_ip_to_prefix(self, ip_obj):
        """
        Links an IPAddress to a matching Prefix's VRF if one exists.
        
        This ensures IPs created during instance sync inherit the VRF
        of their containing Prefix.
        
        Args:
            ip_obj: NetBox IPAddress instance
            
        Returns:
            bool: True if IP was modified
        """
        if not ip_obj:
            return False
        
        try:
            ip_address = netaddr.IPAddress(str(ip_obj.address).split('/')[0])
            
            # Find a matching prefix that contains this IP
            matching_prefix = Prefix.objects.filter(
                prefix__net_contains=str(ip_address)
            ).first()
            
            if not matching_prefix:
                return False
            
            updated = False
            
            # Inherit VRF from prefix if the IP doesn't already have one
            if matching_prefix.vrf and not ip_obj.vrf:
                ip_obj.vrf = matching_prefix.vrf
                updated = True
                self.log('debug', 
                    f"    IP {ip_obj.address}: VRF set to {matching_prefix.vrf.name} "
                    f"(from prefix {matching_prefix.prefix})"
                )
            
            if updated:
                ip_obj.save(update_fields=['vrf'])
            
            return updated
            
        except (netaddr.AddrFormatError, ValueError) as e:
            self.log('debug', f"    Cannot parse IP for prefix matching: {e}")
            return False
    
    # ========================================================================
    # Lookup helpers (used by NetworkSyncService)
    # ========================================================================
    
    def get_network_prefix(self, network_name, family='ipv4'):
        """
        Returns the cached Prefix for a given Incus network name.
        
        Args:
            network_name: Incus network name (e.g. "incusbr0")
            family: 'ipv4' or 'ipv6'
            
        Returns:
            Prefix or None
        """
        cache = self._network_cache.get(network_name, {})
        if family == 'ipv4':
            return cache.get('prefix_v4')
        return cache.get('prefix_v6')
    
    def get_network_vlan(self, network_name):
        """
        Returns the cached VLAN for a given Incus network name.
        
        Args:
            network_name: Incus network name
            
        Returns:
            VLAN or None
        """
        return self._network_cache.get(network_name, {}).get('vlan')
    
    def get_vlan_for_device(self, device_config):
        """
        Finds the appropriate VLAN for an Incus NIC device.
        
        Checks:
        1. Explicit 'vlan' tag in device config
        2. VLAN associated with the managed network
        
        Args:
            device_config: Incus device config dict
            
        Returns:
            VLAN or None
        """
        # 1. Explicit VLAN tag
        vlan_str = device_config.get('vlan', '')
        if vlan_str:
            try:
                vid = int(vlan_str)
                vlan = VLAN.objects.filter(vid=vid).first()
                if vlan:
                    return vlan
            except (ValueError, TypeError):
                pass
        
        # 2. From managed network cache
        network_name = device_config.get('network', '')
        if network_name:
            return self.get_network_vlan(network_name)
        
        return None