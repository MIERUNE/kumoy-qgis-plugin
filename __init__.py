import os
import sys

# to import modules as non-relative
sys.path.append(os.path.dirname(__file__))


def classFactory(iface):
    from .qgishub_plugin import QgishubPlugin

    return QgishubPlugin(iface)
