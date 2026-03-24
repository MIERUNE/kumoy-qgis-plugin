import configparser
import os


def test_read_init():
    """Test that the plugin __init__ will validate on plugins.qgis.org."""

    # You should update this list according to the latest in
    # https://github.com/qgis/qgis-django/blob/master/qgis-app/
    #        plugins/validator.py

    required_metadata = [
        "name",
        "description",
        "version",
        "qgisMinimumVersion",
        "email",
        "author",
    ]

    file_path = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt")
    )
    metadata = []
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(file_path)
    assert parser.has_section("general"), (
        'Cannot find a section named "general" in %s' % file_path
    )
    metadata.extend(parser.items("general"))
    for expectation in required_metadata:
        assert expectation in dict(metadata), (
            'Cannot find metadata "%s" in metadata source (%s).'
            % (expectation, file_path)
        )
