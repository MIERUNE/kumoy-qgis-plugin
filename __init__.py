def classFactory(iface):
    from .plugin import KumoyPlugin

    return KumoyPlugin(iface)
