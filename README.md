# NetBox Incus Sync

[![Pylint](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/Adevixxx/2fdad721bdc8ce07f0ceaf198eda22c6/raw/pylint-badge.json)](https://github.com/Adevixxx/netbox-incus-sync/actions/workflows/pylint-badge.yml)

A NetBox plugin that automatically synchronizes [Incus](https://linuxcontainers.org/incus/) containers and virtual machines into NetBox, providing a complete and up-to-date inventory of your infrastructure.

## Features

- **Instance synchronization** — Containers and VMs synced as NetBox `VirtualMachine` objects with CPU, memory, disk, status, and image metadata
- **Network & IPAM** — Interfaces, IP addresses, MAC addresses, managed networks...
- **Storage** — Virtual disks with pool info, usage statistics (used/total/%), storage driver detection
- **Cluster support** — Automatic `Cluster` and `ClusterType` creation when Incus runs in cluster mode, with per-node `Device` tracking
- **Multi-project** — Full Incus project isolation support; each project is synced as a NetBox `Tenant` with feature flags
- **Profiles** — Incus profiles synced as NetBox `ConfigContext` objects (tag-based), automatically assigned to VMs
- **Config contexts** — Instance-specific configuration stored in `local_context_data`
- **Events / Journal** — Incus operations synced as NetBox `JournalEntry` records
- **VGA screenshots** — Capture console screenshots for VMs (Incus ≥ 6.7) and attach them as `ImageAttachment`
- **Multi-host** — Manage multiple Incus servers from a single NetBox instance
- **Connection modes** — Unix socket (local) and HTTPS with TLS mutual authentication (remote)
- **Multi-URL failover** — Configure multiple HTTPS URLs per host with automatic failover and caching

## Requirements

| Component | Version |
|-----------|---------|
| NetBox    | ≥ 4.2.0 |
| Incus     | ≥ 6.0 (≥ 6.7 for VGA screenshots) |
| Python    | ≥ 3.10 |

## Installation

### From Git (recommended)

```bash
source /opt/netbox/venv/bin/activate
pip install git+https://github.com/Adevixxx/netbox-incus-sync.git
```

### Manual

```bash
cd /opt/netbox/netbox
source /opt/netbox/venv/bin/activate
git clone https://github.com/Adevixxx/netbox-incus-sync.git
cd netbox-incus-sync
pip install .
```

### Enable the plugin

Add to your NetBox `configuration.py`:

```python
PLUGINS = ['netbox_incus_sync']
```

Apply migrations and restart:

```bash
cd /opt/netbox/netbox
python manage.py migrate
systemctl restart netbox netbox-rq
```

## Configuration

### Unix Socket (local)

1. Go to **Plugins → Incus Sync → Incus Hosts**
2. Click **+ Add**
3. Connection type: **Unix Socket**
4. Socket path: `http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket` (default)

### HTTPS (remote)

1. Generate TLS client certificates and add them to the Incus trust store
2. Store certificate files on the NetBox server with restrictive permissions (`chmod 600`)
3. In NetBox, add a host with connection type **HTTPS**
4. Fill in the HTTPS URL(s), client certificate path, private key path, and optionally a CA certificate path

You can configure **multiple URLs** (one per line) for failover. The plugin tests each URL in order, caches the working one, and re-tests after the configurable TTL (default: 5 minutes).

### Optional settings

| Field | Description |
|-------|-------------|
| Default Cluster | Pre-existing NetBox Cluster to assign VMs to (standalone mode) |
| Default Site | Site assigned to auto-created Devices for cluster nodes |
| URL Cache TTL | How long to cache the working URL in seconds (HTTPS only) |
| Verify SSL | Disable only for test environments |

## Usage

### Manual sync

Go to **Plugins → Incus Sync → Incus Hosts** and click the **Sync** button in the top bar to synchronize all enabled hosts, or use the sync button on an individual host's detail page.

### Viewing results

| Data | Where in NetBox |
|------|-----------------|
| Instances | **Virtualization → Virtual Machines** |
| Clusters | **Virtualization → Clusters** |
| Interfaces | VM detail → **Interfaces** tab |
| IP addresses | **IPAM → IP Addresses** |
| Prefixes / VLANs | **IPAM → Prefixes** / **VLANs** |
| Disks | VM detail → **Virtual Disks** tab |
| Profiles (ConfigContexts) | **Extras → Config Contexts** |
| Tenants (projects) | **Tenancy → Tenants** |
| Events | VM detail → **Journal** tab |
| Screenshots | Host detail → **Managed Instances** panel |

### Connection testing

On the host detail page you can:

- **Test Connection** — verify connectivity and view server info (version, cluster status, instance count, storage pools, networks)
- **Test All URLs** — test each configured HTTPS URL individually
- **Clear Cache** — force re-testing the working URL on next sync

## What Gets Synced

### Instances → VirtualMachine

| Incus | NetBox | Notes |
|-------|--------|-------|
| Instance name | `VirtualMachine.name` | Rename detection via UUID |
| `volatile.uuid` | `VirtualMachine.serial` | Used for stable tracking |
| Status (Running/Stopped) | `VirtualMachine.status` | |
| `limits.cpu` | `VirtualMachine.vcpus` | |
| `limits.memory` | `VirtualMachine.memory` | Parsed from human-readable (e.g. `2GiB`) |
| Root disk size | `VirtualMachine.disk` | From config, volume, or pool |
| Cluster membership | `VirtualMachine.cluster` | Auto-created `ClusterType` "Incus" |
| Node location | `incus_location` custom field | Cluster mode only |
| Instance type | `incus_type` custom field | `container` or `virtual-machine` |
| Image description | `incus_image` custom field | |
| Creation date | `incus_created` custom field | |
| Profiles | `incus_profiles` custom field | |
| Project | `incus_project` custom field | |
| Host | `incus_host` custom field | |

### Networks → IPAM

| Incus | NetBox |
|-------|--------|
| Managed network (IPv4 subnet) | `Prefix` |
| Managed network (IPv6 subnet) | `Prefix` |
| NIC device with VLAN | `VLAN` |
| Interface → bridge mapping | `VMInterface.untagged_vlan` / `tagged_vlans` |
| IP → subnet membership | `IPAddress` linked to parent `Prefix` |

### Interfaces → VMInterface

| Incus | NetBox |
|-------|--------|
| Network device name | `VMInterface.name` |
| `hwaddr` | `VMInterface.mac_address` |
| Bridge / network | `incus_bridge` custom field |
| Host veth | `incus_host_interface` custom field |
| NIC type | `incus_nic_type` custom field |
| Device name | `incus_device_name` custom field |

### Disks → VirtualDisk

| Incus | NetBox |
|-------|--------|
| Disk name | `VirtualDisk.name` |
| Size | `VirtualDisk.size` (MB) |
| Mount path | `incus_mount_path` custom field |
| Storage pool | `incus_storage_pool` custom field |
| Volume source | `incus_volume_source` custom field |
| Disk type | `incus_disk_type` custom field (root / data) |
| Storage driver | `incus_storage_driver` custom field |
| Used space | `incus_disk_used` custom field (MB) |
| Total space | `incus_disk_total` custom field (MB) |
| Usage % | `incus_disk_usage_percent` custom field |
| Content type | `incus_disk_content_type` custom field (filesystem / block) |

### Cluster nodes → Device

| Incus | NetBox |
|-------|--------|
| Cluster member | `Device` (role: Hypervisor) |
| Server version | `incus_version` custom field on Device |

### Projects → Tenant

Each Incus project is synced as a `Tenant` inside a `TenantGroup` scoped to the host. Feature flags (`features.profiles`, `features.networks`, etc.) are tracked and respected during sync.

### Profiles → ConfigContext

Incus profiles are synced as NetBox `ConfigContext` objects. VMs are assigned profile tags so NetBox's config context inheritance works automatically.

### Events → JournalEntry

Incus operations (instance start/stop, snapshots, etc.) are synced as `JournalEntry` records attached to the corresponding `VirtualMachine`.


## Architecture

```
netbox_incus_sync/
├── models.py                  # IncusHost model
├── views.py                   # UI views (CRUD, sync, screenshots, connection tests)
├── urls.py                    # URL routing
├── tables.py                  # List table
├── forms.py                   # Host form
├── navigation.py              # Plugin menu
├── custom_fields.py           # Auto-created custom fields
├── jobs.py                    # Background sync jobs (SyncIncusJob, SyncEventsJob)
├── incus_client/              # Modular Incus API client
│   ├── base.py                #   Connection & HTTP transport
│   ├── server.py              #   Server info & connection test
│   ├── instances.py           #   Instances, logs, screenshots
│   ├── cluster.py             #   Cluster members & groups
│   ├── storage.py             #   Storage pools & volumes
│   ├── network.py             #   Managed networks
│   ├── profiles.py            #   Profiles
│   ├── projects.py            #   Projects
│   └── operations.py          #   Async operations
├── services/                  # Sync logic (one service per domain)
│   ├── sync_instances.py      #   Instances → VirtualMachine
│   ├── sync_network.py        #   Interfaces & IPs
│   ├── sync_disks.py          #   Disks & storage usage
│   ├── sync_ipam.py           #   Networks → Prefixes, VLANs, VRFs
│   ├── sync_profiles.py       #   Profiles → ConfigContext
│   ├── sync_config_context.py #   Instance config → local_context_data
│   ├── sync_tenants.py        #   Projects → Tenants
│   ├── sync_events.py         #   Operations → JournalEntry
│   └── sync_utils.py          #   Shared helpers (parse_memory, parse_size, etc.)
├── api/
│   ├── views.py               #   DRF ViewSet
│   ├── serializers.py         #   DRF Serializers
│   └── urls.py                #   API routing
└── templates/                 # Django templates
```

## Development

```bash
git clone https://github.com/Adevixxx/netbox-incus-sync.git
cd netbox-incus-sync
pip install -e ".[dev]"

# Run NetBox dev server
cd /opt/netbox/netbox
python manage.py runserver

# Run background worker (separate terminal)
python manage.py rqworker
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.