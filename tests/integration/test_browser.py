"""The Browser tree built from real responses."""


def test_browser_tree(project):
    from plugin_dir.kumoy import api, map_project
    from plugin_dir.ui.browser.root import RootCollection, current_project
    from plugin_dir.ui.browser.utils import ErrorItem

    vector_id = api.vector.create_vector(project.id, "e2e-browser-v", "LINESTRING")
    styled_map = api.styledmap.create_styled_map(
        project.id, "e2e-browser-m", map_project.empty_project_xml()
    )
    try:
        root = RootCollection()
        children = root.createChildren()
        assert current_project().id == project.id
        names = {}
        for child in children:
            items = child.createChildren()
            names[child.path().rsplit("/", 1)[-1]] = [i.name() for i in items]
            # Empty roots show a placeholder; failures show "Error loading ..."
            errors = [i.name() for i in items if isinstance(i, ErrorItem)]
            assert not any(n.startswith("Error") for n in errors), errors
        assert "e2e-browser-v" in names["vectors"]
        assert "e2e-browser-m" in names["styledmaps"]
    finally:
        api.vector.delete_vector(vector_id)
        api.styledmap.delete_styled_map(styled_map.id)
