from netbox.plugins import PluginMenuButton, PluginMenuItem

# Menu action buttons
incushost_buttons = (
    PluginMenuButton(
        link="plugins:netbox_incus_sync:incushost_add",
        title="Add",
        icon_class="mdi mdi-plus-thick",
        color="green",
    ),
    PluginMenuButton(
        link="plugins:netbox_incus_sync:sync",
        title="Sync",
        icon_class="mdi mdi-sync",
        color="blue",
    ),
    PluginMenuButton(
        link="plugins:netbox_incus_sync:sync_logs",
        title="Sync logs",
        icon_class="mdi mdi-file-document-outline",
        color="cyan",
    ),
)

# Menu items
menu_items = (
    PluginMenuItem(
        link="plugins:netbox_incus_sync:incushost_list",
        link_text="Incus Hosts",
        buttons=incushost_buttons,
    ),
)
