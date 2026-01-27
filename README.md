# NetBox Incus Sync

A NetBox plugin to synchronize Incus instances (containers and VMs) into NetBox.

## Features

- ✅ Sync Incus instances to NetBox VirtualMachine objects
- ✅ Support for Unix socket (local) and HTTPS (remote) connections
- ✅ Secure TLS certificate storage (file paths only, no secrets in database)
- ✅ Manual or scheduled background sync jobs
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

For remote Incus servers, see [SECURITY.md](SECURITY.md) for detailed setup instructions.

Quick overview:

1. Generate TLS client certificates
2. Add certificate to Incus trust store
3. Store certificates on NetBox server with proper permissions
4. Configure host with file paths in NetBox

## Usage

### Manual Sync

1. Go to **Plugins > Incus Sync > Incus Hosts**
2. Click the blue **Sync** button in the menu

### View Results

Synced instances appear in **Virtualization > Virtual Machines**

## What Gets Synced

| Incus Data | NetBox Field | Status |
|------------|--------------|--------|
| Instance name | `VirtualMachine.name` | ✅ |
| Status (Running/Stopped) | `VirtualMachine.status` | ✅ |
| CPU limits | `VirtualMachine.vcpus` | ✅ |
| Memory limits | `VirtualMachine.memory` | ✅ |
| Root disk size | `VirtualMachine.disk` | ✅ |

## Roadmap

- [ ] Sync network interfaces and IP addresses
- [ ] Sync instance type (container vs VM) as tags
- [ ] Support for Incus clustering
- [ ] Bidirectional sync (create in NetBox → provision in Incus)
- [ ] Webhook support for real-time sync

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