"""
Template extensions for the Incus Sync plugin.

Injects an Incus VGA Screenshot panel into the VirtualMachine detail page,
allowing users to capture and view console screenshots directly from the VM page.

Also injects an "Open in Incus UI" link panel when the host has a configured UI base URL.
"""

from netbox.plugins import PluginTemplateExtension
from django.contrib.contenttypes.models import ContentType
from extras.models import ImageAttachment

from .models import IncusHost
from .incus_ui import get_instance_ui_url


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
    Only shows when the IncusHost has incus_ui_base_url configured.
    """

    models = ["virtualization.virtualmachine"]

    def right_page(self):
        vm = self.context["object"]

        # Only show for Incus-managed instances
        incus_host_name = vm.custom_field_data.get("incus_host")
        if not incus_host_name:
            return ""

        # Find the host and check if UI URL is configured
        try:
            host = IncusHost.objects.get(name=incus_host_name, enabled=True)
        except IncusHost.DoesNotExist:
            return ""

        if not host.incus_ui_base_url:
            return ""

        # Build the UI URL
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


template_extensions = [VMIncusScreenshotPanel, VMIncusUIPanel]
