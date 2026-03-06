"""
Template extensions for the Incus Sync plugin.

Injects an Incus VGA Screenshot panel into the VirtualMachine detail page,
allowing users to capture and view console screenshots directly from the VM page.

Also injects "Open in Incus UI" link panels when the host has a resolvable UI URL.
"""

from netbox.plugins import PluginTemplateExtension
from django.contrib.contenttypes.models import ContentType
from extras.models import ImageAttachment

from .models import IncusHost
from .incus_ui import build_incus_ui_url, get_instance_ui_url


class VMIncusScreenshotPanel(PluginTemplateExtension):
    """
    Adds an Incus VGA Screenshot panel to the VirtualMachine detail page.

    Shows:
    - The latest screenshot (if any) with timestamp
    - A "Capture Screenshot" / "Update Screenshot" button (for VMs only)
    - Appropriate messages for containers or non-Incus VMs
    """

    models = ["virtualization.virtualmachine"]

    def right_page(self):
        vm = self.context["object"]

        # Only show for Incus-managed VMs
        incus_host = vm.custom_field_data.get("incus_host")
        if not incus_host:
            return ""

        instance_type = vm.custom_field_data.get("incus_type", "")
        is_vm = instance_type != "container"

        # Get latest screenshot
        screenshot = None
        if is_vm:
            vm_ct = ContentType.objects.get_for_model(vm)
            screenshot = (
                ImageAttachment.objects.filter(
                    object_type=vm_ct,
                    object_id=vm.pk,
                    name__startswith="incus-screenshot-",
                )
                .order_by("-created")
                .first()
            )

        extra_context = {
            "vm": vm,
            "is_vm": is_vm,
            "screenshot": screenshot,
            "incus_host": incus_host,
        }

        return self.render(
            "netbox_incus_sync/vm_screenshot_panel.html",
            extra_context=extra_context,
        )


class VMIncusUIPanel(PluginTemplateExtension):
    """
    Adds an "Open in Incus UI" link panel to the VirtualMachine detail page.

    Completely independent from the screenshot panel.
    Shows for ALL Incus-managed instances (VMs and containers).
    Only shows when the IncusHost has a resolvable UI host URL.
    """

    models = ["virtualization.virtualmachine"]

    def right_page(self):
        vm = self.context["object"]

        incus_host_name = vm.custom_field_data.get("incus_host")
        if not incus_host_name:
            return ""

        try:
            host = IncusHost.objects.get(name=incus_host_name, enabled=True)
        except IncusHost.DoesNotExist:
            return ""

        incus_project = vm.custom_field_data.get("incus_project", "default")
        incus_ui_url = get_instance_ui_url(host, vm.name, project=incus_project)

        if not incus_ui_url:
            return ""

        return self.render(
            "netbox_incus_sync/vm_incus_ui_panel.html",
            extra_context={
                "vm": vm,
                "incus_ui_url": incus_ui_url,
            },
        )


class DiskIncusUIPanel(PluginTemplateExtension):
    """Adds an "Open in Incus UI" link to the VirtualDisk detail page (storage pool)."""

    models = ["virtualization.virtualdisk"]

    def right_page(self):
        disk = self.context["object"]
        pool_name = disk.custom_field_data.get("incus_storage_pool")
        if not pool_name:
            return ""

        vm = disk.virtual_machine
        if not vm:
            return ""

        incus_host_name = vm.custom_field_data.get("incus_host")
        if not incus_host_name:
            return ""

        try:
            host = IncusHost.objects.get(name=incus_host_name, enabled=True)
        except IncusHost.DoesNotExist:
            return ""

        project = vm.custom_field_data.get("incus_project", "default")
        url = build_incus_ui_url(host, "storage_pool", pool_name, project=project)
        if not url:
            return ""

        return self.render(
            "netbox_incus_sync/incus_ui_link_panel.html",
            extra_context={
                "incus_ui_url": url,
                "object_name": pool_name,
                "object_type_label": "Storage Pool",
            },
        )


class InterfaceIncusUIPanel(PluginTemplateExtension):
    """Adds an "Open in Incus UI" link to the VMInterface detail page (network)."""

    models = ["virtualization.vminterface"]

    def right_page(self):
        iface = self.context["object"]
        bridge_name = iface.custom_field_data.get("incus_bridge")
        if not bridge_name:
            return ""

        vm = iface.virtual_machine
        if not vm:
            return ""

        incus_host_name = vm.custom_field_data.get("incus_host")
        if not incus_host_name:
            return ""

        try:
            host = IncusHost.objects.get(name=incus_host_name, enabled=True)
        except IncusHost.DoesNotExist:
            return ""

        project = vm.custom_field_data.get("incus_project", "default")
        url = build_incus_ui_url(host, "network", bridge_name, project=project)
        if not url:
            return ""

        return self.render(
            "netbox_incus_sync/incus_ui_link_panel.html",
            extra_context={
                "incus_ui_url": url,
                "object_name": bridge_name,
                "object_type_label": "Network",
            },
        )


class ProfileIncusUIPanel(PluginTemplateExtension):
    """Adds an "Open in Incus UI" link to the ConfigContext detail page (profile)."""

    models = ["extras.configcontext"]

    def right_page(self):
        config_context = self.context["object"]
        profile_name = config_context.name

        host = None
        for tg in config_context.tenant_groups.all():
            if tg.slug.startswith("incus-projects-"):
                host_name = tg.slug.removeprefix("incus-projects-")
                try:
                    host = IncusHost.objects.get(name=host_name, enabled=True)
                except IncusHost.DoesNotExist:
                    continue
                break

        if not host:
            return ""

        url = build_incus_ui_url(host, "profile", profile_name, project="default")
        if not url:
            return ""

        return self.render(
            "netbox_incus_sync/incus_ui_link_panel.html",
            extra_context={
                "incus_ui_url": url,
                "object_name": profile_name,
                "object_type_label": "Profile",
            },
        )


class TenantIncusUIPanel(PluginTemplateExtension):
    """Adds an "Open in Incus UI" link to the Tenant detail page (project)."""

    models = ["tenancy.tenant"]

    def right_page(self):
        tenant = self.context["object"]
        project_name = tenant.custom_field_data.get("incus_project_name")
        if not project_name:
            return ""

        host = None
        if tenant.group and tenant.group.slug.startswith("incus-projects-"):
            host_name = tenant.group.slug.removeprefix("incus-projects-")
            try:
                host = IncusHost.objects.get(name=host_name, enabled=True)
            except IncusHost.DoesNotExist:
                pass

        if not host:
            return ""

        url = build_incus_ui_url(host, "project", project_name)
        if not url:
            return ""

        return self.render(
            "netbox_incus_sync/incus_ui_link_panel.html",
            extra_context={
                "incus_ui_url": url,
                "object_name": project_name,
                "object_type_label": "Project",
            },
        )


template_extensions = [
    VMIncusScreenshotPanel,
    VMIncusUIPanel,
    DiskIncusUIPanel,
    InterfaceIncusUIPanel,
    ProfileIncusUIPanel,
    TenantIncusUIPanel,
]
