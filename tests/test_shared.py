def test_hubs_live_on_the_application(qgis_app, qgis_plugin_path):
    """Providers of a previous module version (plugin reload/upgrade) emit on
    these hubs, so a reloaded module must find the same objects."""
    from qgis.core import QgsApplication

    from plugin_dir.kumoy import download
    from plugin_dir.kumoy.provider import dataprovider
    from plugin_dir.kumoy.shared import shared

    app = QgsApplication.instance()
    assert app._kumoy_raster_fetcher is download.fetcher
    assert app._kumoy_vector_sync_events is dataprovider.sync_events
    # What the reloaded module's import-time call gets back
    assert shared("raster_fetcher", object) is download.fetcher
