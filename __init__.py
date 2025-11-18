def classFactory(iface):
    from .plugin import StratoPlugin

    return StratoPlugin(iface)
