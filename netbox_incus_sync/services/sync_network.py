"""
Service de synchronisation réseau des instances Incus vers NetBox.

Compatible NetBox 4.2+ où les adresses MAC sont des objets séparés.
"""

from virtualization.models import VMInterface
from ipam.models import IPAddress
from dcim.models import MACAddress
from django.contrib.contenttypes.models import ContentType


class NetworkSyncService:
    """
    Service pour synchroniser les interfaces réseau et IPs des instances Incus.
    """
    
    def __init__(self, logger=None):
        """
        Initialise le service.
        
        Args:
            logger: Logger pour les messages (optionnel)
        """
        self.logger = logger
        self._vminterface_ct = None
    
    def log(self, level, message):
        """Log un message si logger disponible."""
        if self.logger:
            getattr(self.logger, level)(message)
    
    @property
    def vminterface_content_type(self):
        """Retourne le ContentType pour VMInterface (cached)."""
        if self._vminterface_ct is None:
            self._vminterface_ct = ContentType.objects.get_for_model(VMInterface)
        return self._vminterface_ct
    
    def sync_instance_network(self, vm, instance_data, client):
        """
        Synchronise les interfaces réseau et IPs d'une instance.
        
        Args:
            vm: Instance VirtualMachine NetBox
            instance_data: Données de l'instance Incus
            client: Client Incus pour requêtes supplémentaires
        
        Returns:
            tuple: (interfaces_count, ips_count)
        """
        interfaces_synced = 0
        ips_synced = 0
        
        # Récupérer l'état réseau
        network_state = self._get_network_state(vm.name, instance_data, client)
        
        if not network_state:
            return 0, 0
        
        # Récupérer les devices pour les infos de connexion (bridge, parent)
        devices = instance_data.get('expanded_devices', {})
        if not devices:
            devices = instance_data.get('devices', {})
        
        # Pour tracker les IPs primaires candidates
        primary_ip4_candidate = None
        primary_ip6_candidate = None
        
        # Parcourir les interfaces
        current_iface_names = set()
        
        for iface_name, iface_data in network_state.items():
            # Ignorer loopback
            if iface_name == 'lo':
                continue
            
            current_iface_names.add(iface_name)
            
            # Récupérer les infos du device correspondant
            device_config = devices.get(iface_name, {})
            
            # Sync de l'interface
            interface, iface_created = self._sync_interface(
                vm, iface_name, iface_data, device_config
            )
            interfaces_synced += 1
            
            if iface_created:
                self.log('info', f"    Interface créée: {iface_name}")
            
            # Sync de l'adresse MAC (NetBox 4.2+) et définir comme primaire
            hwaddr = iface_data.get('hwaddr', '')
            if hwaddr and hwaddr != '00:00:00:00:00:00':
                self._sync_mac_address(interface, hwaddr)
            
            # Sync des IPs et récupérer les candidates pour IP primaire
            ip4, ip6, ip_count = self._sync_interface_ips(interface, iface_data, vm.name)
            ips_synced += ip_count
            
            # Garder la première IP globale trouvée comme candidate
            if ip4 and not primary_ip4_candidate:
                primary_ip4_candidate = ip4
            if ip6 and not primary_ip6_candidate:
                primary_ip6_candidate = ip6
        
        # Définir les IPs primaires de la VM
        self._set_primary_ips(vm, primary_ip4_candidate, primary_ip6_candidate)
        
        # Nettoyer les interfaces obsolètes
        self._cleanup_old_interfaces(vm, current_iface_names)
        
        return interfaces_synced, ips_synced
    
    def _get_network_state(self, vm_name, instance_data, client):
        """
        Récupère l'état réseau d'une instance.
        
        Args:
            vm_name: Nom de l'instance
            instance_data: Données de l'instance (peut contenir state)
            client: Client Incus
        
        Returns:
            dict: État réseau ou None
        """
        # D'abord essayer depuis instance_data
        state = instance_data.get('state', {})
        network_state = state.get('network', {})
        
        if network_state:
            return network_state
        
        # Sinon, requête séparée
        try:
            instance_state = client.get_instance_state(vm_name)
            if instance_state:
                return instance_state.get('network', {})
        except Exception as e:
            self.log('warning', f"    Impossible de récupérer l'état réseau de {vm_name}: {e}")
        
        return None
    
    def _sync_interface(self, vm, iface_name, iface_data, device_config):
        """
        Synchronise une interface réseau.
        
        Note: Dans NetBox 4.2+, mac_address n'est plus un champ direct.
        Il faut créer un objet MACAddress séparé.
        
        Args:
            vm: VirtualMachine NetBox
            iface_name: Nom de l'interface (eth0, etc.)
            iface_data: Données de l'état réseau depuis Incus
            device_config: Configuration du device depuis expanded_devices
        
        Returns:
            tuple: (interface, created)
        """
        iface_state = iface_data.get('state', 'down')
        mtu = iface_data.get('mtu', None)
        host_name = iface_data.get('host_name', '')  # vethXXX côté hôte
        
        # Infos de connexion depuis device_config
        network = device_config.get('network', '')  # Bridge managé (incusbr0)
        parent = device_config.get('parent', '')    # Interface parente directe
        nictype = device_config.get('nictype', '')  # bridged, macvlan, etc.
        
        # Le bridge effectif est soit 'network' soit 'parent'
        bridge = network or parent
        
        # Construire une description simplifiée (les détails sont dans les custom fields)
        description = f"Synced from Incus | State: {iface_state}"
        
        defaults = {
            'enabled': iface_state == 'up',
            'description': description,
        }
        
        # MTU si disponible
        if mtu:
            defaults['mtu'] = mtu
        
        interface, created = VMInterface.objects.update_or_create(
            virtual_machine=vm,
            name=iface_name,
            defaults=defaults
        )
        
        # Mettre à jour les Custom Fields
        self._update_interface_custom_fields(interface, bridge, host_name, nictype)
        
        return interface, created
    
    def _update_interface_custom_fields(self, interface, bridge, host_name, nictype):
        """
        Met à jour les Custom Fields de l'interface.
        
        Args:
            interface: VMInterface NetBox
            bridge: Nom du bridge/network Incus
            host_name: Interface veth côté hôte
            nictype: Type de NIC
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
        Synchronise l'adresse MAC d'une interface (NetBox 4.2+).
        
        Dans NetBox 4.2+, les adresses MAC sont des objets séparés
        liés aux interfaces via une relation générique.
        Cette méthode crée la MAC et la définit comme primaire.
        
        Args:
            interface: Instance VMInterface
            hwaddr: Adresse MAC (string)
        """
        try:
            # Normaliser l'adresse MAC (majuscules)
            hwaddr_normalized = hwaddr.upper()
            
            # Vérifier si cette interface a déjà cette MAC comme primaire
            current_primary = interface.primary_mac_address
            if current_primary and str(current_primary.mac_address).upper() == hwaddr_normalized:
                # Déjà configuré correctement
                return
            
            # Chercher si cette MAC existe déjà et est assignée à cette interface
            existing_mac = MACAddress.objects.filter(
                mac_address=hwaddr_normalized,
                assigned_object_type=self.vminterface_content_type,
                assigned_object_id=interface.pk
            ).first()
            
            if existing_mac:
                # MAC existe et est déjà assignée à cette interface
                mac_obj = existing_mac
            else:
                # Chercher si cette MAC existe mais assignée ailleurs
                existing_mac_elsewhere = MACAddress.objects.filter(
                    mac_address=hwaddr_normalized
                ).first()
                
                if existing_mac_elsewhere:
                    # Réassigner à cette interface
                    existing_mac_elsewhere.assigned_object_type = self.vminterface_content_type
                    existing_mac_elsewhere.assigned_object_id = interface.pk
                    existing_mac_elsewhere.save()
                    mac_obj = existing_mac_elsewhere
                    self.log('info', f"    MAC réassignée: {hwaddr_normalized}")
                else:
                    # Créer une nouvelle MAC
                    mac_obj = MACAddress.objects.create(
                        mac_address=hwaddr_normalized,
                        assigned_object_type=self.vminterface_content_type,
                        assigned_object_id=interface.pk,
                        description=f"Synced from Incus - {interface.virtual_machine.name}",
                    )
                    self.log('info', f"    MAC créée: {hwaddr_normalized}")
            
            # Définir comme primaire seulement si pas déjà fait
            if interface.primary_mac_address_id != mac_obj.pk:
                interface.primary_mac_address = mac_obj
                interface.save()
                
        except Exception as e:
            self.log('warning', f"    Erreur lors de la sync MAC {hwaddr}: {e}")
    
    def _sync_interface_ips(self, interface, iface_data, vm_name):
        """
        Synchronise les adresses IP d'une interface.
        
        Returns:
            tuple: (first_ipv4, first_ipv6, count)
                - first_ipv4: Première IPv4 globale trouvée (ou None)
                - first_ipv6: Première IPv6 globale trouvée (ou None)
                - count: Nombre total d'IPs synchronisées
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
            
            # Ignorer les adresses link-local et localhost
            if ip_scope in ('link', 'local'):
                continue
            
            if not ip_address or not ip_netmask:
                continue
            
            # Construire l'adresse CIDR
            ip_cidr = f"{ip_address}/{ip_netmask}"
            
            try:
                ip_obj = self._sync_ip_address(ip_cidr, interface, vm_name)
                if ip_obj:
                    ips_synced += 1
                    
                    # Garder la première IP de chaque famille comme candidate primaire
                    if ip_family == 'inet' and first_ipv4 is None:
                        first_ipv4 = ip_obj
                    elif ip_family == 'inet6' and first_ipv6 is None:
                        first_ipv6 = ip_obj
                        
            except Exception as e:
                self.log('warning', f"    Erreur lors de la sync IP {ip_cidr}: {e}")
        
        return first_ipv4, first_ipv6, ips_synced
    
    def _sync_ip_address(self, ip_cidr, interface, vm_name):
        """
        Synchronise une adresse IP.
        
        Returns:
            IPAddress ou None
        """
        # Chercher d'abord si cette IP existe déjà
        existing_ip = IPAddress.objects.filter(address=ip_cidr).first()
        
        if existing_ip:
            # Vérifier si elle est déjà assignée à cette interface
            if (existing_ip.assigned_object_id == interface.pk and 
                existing_ip.assigned_object_type == self.vminterface_content_type):
                # Déjà correctement assignée
                return existing_ip
            
            # Réassigner à cette interface
            existing_ip.assigned_object_type = self.vminterface_content_type
            existing_ip.assigned_object_id = interface.pk
            existing_ip.save()
            return existing_ip
        
        # Créer une nouvelle IP
        ip_obj = IPAddress.objects.create(
            address=ip_cidr,
            assigned_object_type=self.vminterface_content_type,
            assigned_object_id=interface.pk,
            description=f"Incus instance: {vm_name} ({interface.name})",
        )
        
        self.log('info', f"    IP créée: {ip_cidr} sur {interface.name}")
        return ip_obj
    
    def _set_primary_ips(self, vm, ip4, ip6):
        """
        Définit les IPs primaires de la VM.
        
        Gère correctement le cas où l'IP est déjà primaire sur une autre VM
        (ce qui peut arriver lors d'un renommage ou d'une reconstruction).
        
        Args:
            vm: Instance VirtualMachine
            ip4: IPAddress IPv4 candidate (ou None)
            ip6: IPAddress IPv6 candidate (ou None)
        """
        from virtualization.models import VirtualMachine
        
        updated = False
        
        # Définir IPv4 primaire
        if ip4 and vm.primary_ip4_id != ip4.pk:
            # Vérifier si cette IP est déjà primaire sur une autre VM
            other_vm = VirtualMachine.objects.filter(primary_ip4=ip4).exclude(pk=vm.pk).first()
            if other_vm:
                # Retirer l'IP primaire de l'autre VM
                self.log('warning', f"    IP {ip4.address} était primaire sur {other_vm.name}, réassignation...")
                other_vm.primary_ip4 = None
                other_vm.save()
            
            vm.primary_ip4 = ip4
            updated = True
            self.log('info', f"    IP primaire v4: {ip4.address}")
        
        # Définir IPv6 primaire
        if ip6 and vm.primary_ip6_id != ip6.pk:
            # Vérifier si cette IP est déjà primaire sur une autre VM
            other_vm = VirtualMachine.objects.filter(primary_ip6=ip6).exclude(pk=vm.pk).first()
            if other_vm:
                # Retirer l'IP primaire de l'autre VM
                self.log('warning', f"    IP {ip6.address} était primaire sur {other_vm.name}, réassignation...")
                other_vm.primary_ip6 = None
                other_vm.save()
            
            vm.primary_ip6 = ip6
            updated = True
            self.log('info', f"    IP primaire v6: {ip6.address}")
        
        if updated:
            vm.save()
    
    def _cleanup_old_interfaces(self, vm, current_iface_names):
        """
        Supprime les interfaces qui n'existent plus.
        
        Args:
            vm: Instance VirtualMachine
            current_iface_names: Set des noms d'interfaces actuelles
        """
        old_interfaces = VMInterface.objects.filter(
            virtual_machine=vm
        ).exclude(name__in=current_iface_names)
        
        for old_iface in old_interfaces:
            self.log('info', f"    Interface supprimée: {old_iface.name}")
            old_iface.delete()
    
    def log_networks_info(self, networks):
        """
        Log les informations sur les réseaux Incus.
        
        Args:
            networks: Liste des réseaux depuis l'API Incus
        """
        if not networks:
            return
        
        self.log('info', f"  Réseaux Incus: {len(networks)}")
        for net in networks:
            net_name = net.get('name', 'unknown')
            net_type = net.get('type', 'unknown')
            managed = net.get('managed', False)
            config = net.get('config', {})
            ipv4 = config.get('ipv4.address', 'N/A')
            self.log('info', f"    - {net_name} ({net_type}, managed={managed}, IPv4={ipv4})")