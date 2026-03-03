"""
Simulated Incus API responses (recursion=2 style).

Used by test_services.py to feed realistic data into the real sync services.
"""

# =====================================================================
# Containers
# =====================================================================

CONTAINER_BASIC = {
    "name": "test-container-01",
    "status": "Running",
    "type": "container",
    "location": "",
    "created_at": "2025-01-15T10:30:00.123456789Z",
    "profiles": ["default", "web"],
    "config": {
        "volatile.uuid": "abc12345-1234-5678-9abc-def012345678",
        "volatile.base_image": "ubuntu:22.04",
        "volatile.eth0.hwaddr": "00:16:3e:aa:bb:cc",
        "image.os": "Ubuntu",
        "image.release": "22.04",
        "limits.cpu": "2",
        "limits.memory": "1GiB",
        "security.nesting": "true",
    },
    "expanded_config": {
        "volatile.uuid": "abc12345-1234-5678-9abc-def012345678",
        "limits.cpu": "2",
        "limits.memory": "1GiB",
    },
    "devices": {
        "root": {"type": "disk", "path": "/", "pool": "default", "size": "10GiB"},
        "eth0": {
            "type": "nic",
            "nictype": "bridged",
            "parent": "incusbr0",
            "name": "eth0",
            "hwaddr": "00:16:3e:aa:bb:cc",
        },
    },
    "expanded_devices": {
        "root": {"type": "disk", "path": "/", "pool": "default", "size": "10GiB"},
        "eth0": {
            "type": "nic",
            "nictype": "bridged",
            "parent": "incusbr0",
            "name": "eth0",
            "hwaddr": "00:16:3e:aa:bb:cc",
            "host_name": "veth1234abcd",
        },
    },
    "state": {
        "status": "Running",
        "status_code": 103,
        "network": {
            "eth0": {
                "addresses": [
                    {
                        "family": "inet",
                        "address": "10.0.0.100",
                        "netmask": "24",
                        "scope": "global",
                    },
                    {
                        "family": "inet6",
                        "address": "fd42::100",
                        "netmask": "64",
                        "scope": "global",
                    },
                    {
                        "family": "inet6",
                        "address": "fe80::1",
                        "netmask": "64",
                        "scope": "link",
                    },
                ],
                "hwaddr": "00:16:3e:aa:bb:cc",
                "state": "up",
                "type": "broadcast",
                "mtu": 1500,
            },
            "lo": {
                "addresses": [
                    {"family": "inet", "address": "127.0.0.1", "netmask": "8"}
                ],
                "state": "up",
                "type": "loopback",
            },
        },
    },
}

# Same UUID, different name → rename detection
CONTAINER_RENAMED = {
    **CONTAINER_BASIC,
    "name": "test-container-renamed",
}

CONTAINER_STOPPED = {
    "name": "test-container-stopped",
    "status": "Stopped",
    "type": "container",
    "location": "",
    "profiles": ["default"],
    "config": {
        "volatile.uuid": "stopped-uuid-1234-5678-9abc-000000000001",
        "limits.cpu": "1",
        "limits.memory": "512MiB",
    },
    "expanded_config": {
        "volatile.uuid": "stopped-uuid-1234-5678-9abc-000000000001",
        "limits.cpu": "1",
        "limits.memory": "512MiB",
    },
    "devices": {
        "root": {"type": "disk", "path": "/", "pool": "default", "size": "5GiB"},
    },
    "expanded_devices": {
        "root": {"type": "disk", "path": "/", "pool": "default", "size": "5GiB"},
    },
    "state": {"status": "Stopped", "status_code": 102, "network": {}},
}

CONTAINER_MULTI_NIC = {
    **CONTAINER_BASIC,
    "name": "test-multi-nic",
    "config": {
        **CONTAINER_BASIC["config"],
        "volatile.uuid": "multinic-uuid-0000-0000-000000000001",
    },
    "expanded_config": {
        **CONTAINER_BASIC["expanded_config"],
        "volatile.uuid": "multinic-uuid-0000-0000-000000000001",
    },
    "expanded_devices": {
        **CONTAINER_BASIC["expanded_devices"],
        "eth1": {
            "type": "nic",
            "nictype": "bridged",
            "parent": "br-mgmt",
            "name": "eth1",
            "host_name": "veth5678efgh",
        },
    },
    "state": {
        **CONTAINER_BASIC["state"],
        "network": {
            **CONTAINER_BASIC["state"]["network"],
            "eth1": {
                "addresses": [
                    {
                        "family": "inet",
                        "address": "192.168.1.50",
                        "netmask": "24",
                        "scope": "global",
                    }
                ],
                "hwaddr": "00:16:3e:dd:ee:ff",
                "state": "up",
                "type": "broadcast",
                "mtu": 1500,
            },
        },
    },
}

CONTAINER_NO_LIMITS = {
    "name": "test-bare",
    "status": "Stopped",
    "type": "container",
    "location": "",
    "profiles": ["default"],
    "config": {"volatile.uuid": "bare-uuid-0000-0000-000000000000"},
    "expanded_config": {},
    "devices": {"root": {"type": "disk", "path": "/", "pool": "default"}},
    "expanded_devices": {"root": {"type": "disk", "path": "/", "pool": "default"}},
    "state": None,
}


# =====================================================================
# Virtual Machines
# =====================================================================

VM_BASIC = {
    "name": "test-vm-01",
    "status": "Running",
    "type": "virtual-machine",
    "location": "node-01",
    "created_at": "2025-06-01T14:00:00Z",
    "profiles": ["default", "database"],
    "config": {
        "volatile.uuid": "vm-uuid-aaaa-bbbb-cccc-ddddeeee0001",
        "limits.cpu": "4",
        "limits.memory": "8GiB",
        "security.secureboot": "false",
    },
    "expanded_config": {
        "volatile.uuid": "vm-uuid-aaaa-bbbb-cccc-ddddeeee0001",
        "limits.cpu": "4",
        "limits.memory": "8GiB",
    },
    "devices": {
        "root": {"type": "disk", "path": "/", "pool": "ssd-pool", "size": "100GiB"},
        "data": {
            "type": "disk",
            "source": "db-data",
            "path": "/var/lib/postgresql",
            "pool": "nvme-pool",
        },
    },
    "expanded_devices": {
        "root": {"type": "disk", "path": "/", "pool": "ssd-pool", "size": "100GiB"},
        "data": {
            "type": "disk",
            "source": "db-data",
            "path": "/var/lib/postgresql",
            "pool": "nvme-pool",
        },
        "eth0": {"type": "nic", "network": "incusbr0", "name": "eth0"},
    },
    "state": {
        "status": "Running",
        "status_code": 103,
        "network": {
            "enp5s0": {
                "addresses": [
                    {
                        "family": "inet",
                        "address": "10.0.0.200",
                        "netmask": "24",
                        "scope": "global",
                    }
                ],
                "hwaddr": "00:16:3e:11:22:33",
                "state": "up",
                "type": "broadcast",
                "mtu": 1500,
            },
        },
    },
}

VM_CPU_RANGE = {
    **VM_BASIC,
    "name": "test-vm-cpurange",
    "config": {
        **VM_BASIC["config"],
        "volatile.uuid": "vm-cpurange-0000-0000-000000000001",
        "limits.cpu": "0-3",
    },
    "expanded_config": {
        **VM_BASIC["expanded_config"],
        "volatile.uuid": "vm-cpurange-0000-0000-000000000001",
        "limits.cpu": "0-3",
    },
}


# =====================================================================
# Profiles
# =====================================================================

PROFILE_DEFAULT = {
    "name": "default",
    "description": "Default Incus profile",
    "config": {},
    "devices": {
        "eth0": {"type": "nic", "network": "incusbr0", "name": "eth0"},
        "root": {"type": "disk", "path": "/", "pool": "default"},
    },
}

PROFILE_WEB = {
    "name": "web",
    "description": "Web server profile",
    "config": {"limits.cpu": "2", "limits.memory": "2GiB", "security.nesting": "true"},
    "devices": {
        "eth1": {
            "type": "nic",
            "nictype": "bridged",
            "parent": "br-public",
            "name": "eth1",
        },
    },
}
