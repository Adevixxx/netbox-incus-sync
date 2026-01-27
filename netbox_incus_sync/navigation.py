from netbox.plugins import PluginMenuButton, PluginMenuItem

# Boutons d'action dans le menu
incushost_buttons = (
    PluginMenuButton(
        link='plugins:netbox_incus_sync:incushost_add',
        title='Ajouter',
        icon_class='mdi mdi-plus-thick',
        color='green'
    ),
    PluginMenuButton(
        link='plugins:netbox_incus_sync:sync',
        title='Synchroniser',
        icon_class='mdi mdi-sync',
        color='blue'
    ),
)

# Éléments du menu
menu_items = (
    PluginMenuItem(
        link='plugins:netbox_incus_sync:incushost_list',
        link_text='Hôtes Incus',
        buttons=incushost_buttons
    ),
)