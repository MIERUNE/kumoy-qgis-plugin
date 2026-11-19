"""ui.icons.progress_icon: a ring that fills clockwise with the progress."""

import pytest


@pytest.fixture
def icons(qgis_app, qgis_plugin_path):
    from plugin_dir.ui import icons

    return icons


def _alpha_at(icon, x, y, size=48):
    return icon.pixmap(size, size).toImage().pixelColor(x, y).alpha()


# Points on the ring of a 48 px icon, clockwise from 12 o'clock
TOP, RIGHT, BOTTOM, LEFT = (24, 6), (42, 24), (24, 42), (6, 24)


def _filled(icons, percent):
    """Which ring points are drawn in the accent (opaque) colour."""
    icon = icons.progress_icon(percent)
    return [_alpha_at(icon, *p) > 200 for p in (RIGHT, BOTTOM, LEFT)]


def test_ring_fills_clockwise(icons):
    assert _filled(icons, 0) == [False, False, False]
    assert _filled(icons, 30) == [True, False, False]
    assert _filled(icons, 55) == [True, True, False]
    assert _filled(icons, 80) == [True, True, True]


def test_empty_part_still_shows_the_track(icons):
    # The unfilled part is drawn faintly, so 0 % still reads as a gauge
    assert 0 < _alpha_at(icons.progress_icon(0), *LEFT) < 200


def test_icons_are_cached_per_step(icons):
    assert icons.progress_icon(41) is icons.progress_icon(39)  # same 5 % step
    assert icons.progress_icon(41) is not icons.progress_icon(46)
    assert icons.progress_icon(-5) is icons.progress_icon(0)
    assert icons.progress_icon(250) is icons.progress_icon(100)
