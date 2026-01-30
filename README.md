# NetBox Incus Sync

A NetBox plugin to synchronize Incus instances (containers and VMs) into NetBox.

## Features

- ✅ Sync Incus instances to NetBox VirtualMachine objects
- ✅ Automatic NetBox Cluster creation when Incus is in cluster mode
- ✅ Support for Unix socket (local) and HTTPS (remote) connections
- ✅ Secure TLS certificate storage (file paths only, no secrets in database)
- ✅ Sync network interfaces and IP addresses
- ✅ Sync virtual disks
- ✅ Sync events to NetBox Journal Entries
- ✅ Multi-host support (sync from multiple Incus servers)

## Requirements

- NetBox >= 4.2.0
- Incus >= 6.0
- Python 3.10+

## Installation

### Via pip
```bash
pip install git+https://github.com/YOUR_USERNAME/netbox-incus-sync.git
```

### Manual installation
```bash
cd /opt/netbox/netbox
source /opt/netbox/venv/bin/activate
git clone https://github.com/YOUR_USERNAME/netbox-incus-sync.git
pip install -e netbox-incus-sync/
```

### Enable the plugin

Add to your `configuration.py`:
```python
PLUGINS = ['netbox_incus_sync']
```

Apply database migrations:
```bash
cd /opt/netbox/netbox
python manage.py migrate
```

Restart NetBox:
```bash
systemctl restart netbox netbox-rq
```

## Configuration

### Unix Socket (Local)

For local Incus servers, use the default Unix socket connection:

1. Go to **Plugins > Incus Sync > Incus Hosts**
2. Click **+ Add**
3. Set connection type to **Unix Socket**
4. Use default path: `http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket`

### HTTPS (Remote)

For remote Incus servers:

1. Generate TLS client certificates
2. Add certificate to Incus trust store
3. Store certificates on NetBox server with proper permissions
4. Configure host with file paths in NetBox

## How Clusters Work

The plugin uses **native NetBox Clusters** for organization:

| Incus Mode | NetBox Behavior |
|------------|-----------------|
| **Standalone** | VMs created without cluster (or with default cluster if configured) |
| **Cluster** | A NetBox Cluster of type "Incus" is automatically created; all VMs assigned to it |

When Incus is in cluster mode:
- A `ClusterType` named "Incus" is created automatically
- A `Cluster` is created with the Incus cluster name
- All synchronized VMs are assigned to this cluster
- The `incus_location` custom field shows which node each VM runs on

## Usage

### Manual Sync

1. Go to **Plugins > Incus Sync > Incus Hosts**
2. Click the **Sync** button

### View Results

- Synced instances: **Virtualization > Virtual Machines**
- Clusters (if applicable): **Virtualization > Clusters**

## What Gets Synced

| Incus Data | NetBox Field | Notes |
|------------|--------------|-------|
| Instance name | `VirtualMachine.name` | |
| Status (Running/Stopped) | `VirtualMachine.status` | |
| CPU limits | `VirtualMachine.vcpus` | |
| Memory limits | `VirtualMachine.memory` | |
| Root disk size | `VirtualMachine.disk` | |
| Cluster membership | `VirtualMachine.cluster` | Native NetBox Cluster |
| Cluster node location | `incus_location` custom field | Only if Incus cluster |
| Instance type | `incus_type` custom field | container or virtual-machine |
| Image | `incus_image` custom field | |
| Profiles | `incus_profiles` custom field | |
| Network interfaces | `VMInterface` | With MAC addresses (NetBox 4.2+) |
| IP addresses | `IPAddress` | Assigned to interfaces |
| Disks | `VirtualDisk` | |

## Custom Fields

The plugin creates these custom fields automatically:

### On VirtualMachine
| Field | Description |
|-------|-------------|
| `incus_type` | Instance type (container/virtual-machine) |
| `incus_image` | Source image |
| `incus_created` | Creation date in Incus |
| `incus_last_sync` | Last synchronization date |
| `incus_profiles` | Applied profiles |
| `incus_location` | Cluster node (if cluster mode) |

### On VMInterface
| Field | Description |
|-------|-------------|
| `incus_bridge` | Connected bridge/network |
| `incus_host_interface` | Host-side veth interface |
| `incus_nic_type` | NIC type (bridged, macvlan, etc.) |

### On VirtualDisk
| Field | Description |
|-------|-------------|
| `incus_mount_path` | Mount point |
| `incus_storage_pool` | Storage pool name |
| `incus_volume_source` | Volume source (for additional volumes) |
| `incus_disk_type` | Disk type (root, data) |

## Roadmap

- [ ] Sync snapshots
- [ ] Sync Incus profiles as ConfigTemplates
- [ ] Bidirectional sync (create in NetBox → provision in Incus)
- [ ] Webhook support for real-time sync
- [ ] Sync Incus networks to NetBox VLANs
- [ ] Sync storage pools

## Development

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/netbox-incus-sync.git
cd netbox-incus-sync

# Install in development mode
pip install -e .

# Run NetBox development server
cd /opt/netbox/netbox
python manage.py runserver

# Run background worker (in another terminal)
python manage.py rqworker
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

Apache 2.0