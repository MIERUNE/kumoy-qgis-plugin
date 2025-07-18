import os
import sys

# to import modules as non-relative
sys.path.append(os.path.dirname(__file__))


def classFactory(iface):
    from .plugin import StratoPlugin

    return StratoPlugin(iface)
