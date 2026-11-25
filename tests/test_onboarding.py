from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qgis.core import QgsApplication
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMainWindow, QMenu

from plugin_dir import i18n
from plugin_dir.pyqt_version import QDIALOG_CODE, QT_KEY
from plugin_dir.ui.dialog_onboarding import OnboardingDialog


@pytest.fixture
def guide(qgis_app):
    dialog = OnboardingDialog()
    yield dialog
    dialog.close()
    dialog.deleteLater()


def test_navigate_all_steps_and_finish(guide):
    titles = [
        "Login",
        "Select Project",
        "Upload Your Data",
        "Read Data",
        "Edit Data",
        "Publish Map",
    ]
    guide.show()
    assert guide.pages.currentWidget() is guide.welcome_page
    guide.start_tour_button.click()
    guide.back_button.click()
    assert guide.pages.currentWidget() is guide.welcome_page
    guide.start_tour_button.click()
    for step, title in enumerate(titles, start=1):
        assert guide.title_label.text() == i18n.tr(title)
        assert not guide.image_label.pixmap().isNull()
        assert guide.progress_label.text() == i18n.tr("Step {} of {}").format(step, 6)
        if step == 2:
            guide.back_button.click()
            assert guide.title_label.text() == i18n.tr("Login")
            guide.next_button.click()
        guide.next_button.click()
    assert guide.pages.currentWidget() is guide.finish_page
    assert guide.isVisible()
    guide.finish_back_button.click()
    assert guide.pages.currentWidget() is guide.tour_page
    assert guide.title_label.text() == i18n.tr("Publish Map")
    guide.next_button.click()
    guide.finish_button.click()
    assert guide.result() == QDIALOG_CODE.Accepted


def test_start_using_kumoy_skips_tour(guide):
    guide.show()
    guide.skip_tour_button.click()
    assert guide.result() == QDIALOG_CODE.Accepted
    assert not guide.isVisible()


def test_menu_guide_omits_welcome_and_finish(guide):
    guide.show_guide(introductory=False)
    assert guide.pages.currentWidget() is guide.tour_page
    assert not guide.back_button.isEnabled()
    for _ in range(5):
        guide.next_button.click()
    assert guide.title_label.text() == i18n.tr("Publish Map")
    assert guide.next_button.text() == i18n.tr("Close")
    guide.next_button.click()
    assert not guide.isVisible()


@pytest.mark.parametrize("introductory", [True, False])
def test_arrow_keys_move_between_pages_with_button_focus(guide, qgis_app, introductory):
    guide.show_guide(introductory=introductory)
    guide.activateWindow()
    qgis_app.processEvents()
    if introductory:
        QTest.keyClick(guide.start_tour_button, QT_KEY.Key_Right)
        assert guide.pages.currentWidget() is guide.tour_page
        QTest.keyClick(guide.next_button, QT_KEY.Key_Left)
        assert guide.pages.currentWidget() is guide.welcome_page
        QTest.keyClick(guide.start_tour_button, QT_KEY.Key_Right)
    else:
        QTest.keyClick(guide.next_button, QT_KEY.Key_Left)
        assert guide.pages.currentWidget() is guide.tour_page
    for _ in range(5):
        QTest.keyClick(guide.next_button, QT_KEY.Key_Right)
    assert guide.title_label.text() == i18n.tr("Publish Map")
    QTest.keyClick(guide.next_button, QT_KEY.Key_Right)
    if introductory:
        assert guide.pages.currentWidget() is guide.finish_page
        QTest.keyClick(guide.finish_button, QT_KEY.Key_Right)
        assert guide.isVisible()
        QTest.keyClick(guide.finish_button, QT_KEY.Key_Left)
    assert guide.pages.currentWidget() is guide.tour_page
    assert guide.title_label.text() == i18n.tr("Publish Map")
    assert guide.isVisible()


def test_close_early_and_reopen_starts_at_welcome(guide):
    guide.show()
    guide.start_tour_button.click()
    guide.next_button.click()
    guide.close()
    assert guide.result() == QDIALOG_CODE.Rejected
    guide.show()
    assert guide.pages.currentWidget() is guide.welcome_page
    assert guide.title_label.text() == i18n.tr("Login")


@pytest.mark.parametrize("locale", ["en_US", "ja_JP", "fr_FR"])
def test_illustrations_render_for_all_steps(qgis_app, monkeypatch, locale):
    monkeypatch.setattr(QgsApplication, "locale", staticmethod(lambda: locale))
    dialog = OnboardingDialog()
    try:
        dialog.show()
        dialog.start_tour_button.click()
        for _ in range(6):
            qgis_app.processEvents()
            screenshot = dialog.image_label.pixmap()
            assert not screenshot.isNull()
            assert (
                screenshot.width()
                <= dialog.image_label.width() * screenshot.devicePixelRatioF()
            )
            assert (
                screenshot.height()
                <= dialog.image_label.height() * screenshot.devicePixelRatioF()
            )
            # Source illustrations are 1060 x 700; scaling must preserve their aspect ratio.
            assert abs(screenshot.width() / screenshot.height() - 1060 / 700) < 0.01
            dialog.next_button.click()
    finally:
        dialog.close()
        dialog.deleteLater()


@pytest.mark.usefixtures("qgis_plugin_path")
@pytest.mark.parametrize("seen", ["false", "true"])
def test_plugin_activation_does_not_open_guide(qgis_app, monkeypatch, seen):
    from plugin_dir import plugin

    settings = SimpleNamespace(onboarding_seen=seen)
    monkeypatch.setattr(plugin, "get_settings", lambda: settings)
    stored = Mock()
    monkeypatch.setattr(plugin, "store_setting", stored)
    monkeypatch.setattr(plugin, "DataItemProvider", Mock())
    monkeypatch.setattr(plugin, "KumoyDataItemGuiProvider", Mock())
    monkeypatch.setattr(plugin, "KumoyProcessingProvider", Mock())
    monkeypatch.setattr(plugin, "KumoyProviderMetadata", Mock())
    monkeypatch.setattr(plugin, "KumoyRasterProviderMetadata", Mock())
    monkeypatch.setattr(plugin, "QgsProviderRegistry", Mock())
    monkeypatch.setattr(plugin.QgsApplication, "dataItemProviderRegistry", Mock())
    monkeypatch.setattr(plugin.QgsApplication, "processingRegistry", Mock())
    monkeypatch.setattr(plugin.QgsGui, "dataItemGuiProviderRegistry", Mock())
    window = QMainWindow()
    menu = QMenu(window)
    iface = Mock()
    iface.mainWindow.return_value = window
    iface.pluginMenu.return_value = menu
    instance = plugin.KumoyPlugin(iface)
    monkeypatch.setattr(instance, "check_plugin_version", Mock())
    monkeypatch.setattr(instance, "update_logout_action_visibility", Mock())
    dialog = None
    try:
        instance.initGui()
        qgis_app.processEvents()
        assert instance.onboarding_dialog is None
        stored.assert_not_called()
        instance.onboarding_action.trigger()
        assert instance.onboarding_dialog.isVisible()
        dialog = instance.onboarding_dialog
        assert dialog.pages.currentWidget() is dialog.tour_page
        assert not dialog.back_button.isEnabled()
        instance.onboarding_action.trigger()
        assert instance.onboarding_dialog is dialog
        stored.assert_not_called()
    finally:
        instance.unload()
        if dialog is not None:
            assert not dialog.isVisible()
        window.deleteLater()


@pytest.mark.usefixtures("qgis_plugin_path")
@pytest.mark.parametrize("entry", ["double_click", "context_menu"])
@pytest.mark.parametrize("guide_result", [QDIALOG_CODE.Accepted, QDIALOG_CODE.Rejected])
def test_first_login_shows_intro_before_login_once(
    qgis_app, monkeypatch, entry, guide_result
):
    from plugin_dir.kumoy.settings_manager import UserSettings
    from plugin_dir.ui.browser import root

    settings = UserSettings()
    monkeypatch.setattr(root, "get_settings", lambda: settings)
    stored = Mock(side_effect=lambda key, value: setattr(settings, key, value))
    monkeypatch.setattr(root, "store_setting", stored)
    events = []
    login_dialog = object()

    def create_login():
        events.append("create_login")
        return login_dialog

    monkeypatch.setattr(root, "DialogLogin", create_login)

    def execute(dialog):
        if isinstance(dialog, OnboardingDialog):
            assert dialog.pages.currentWidget() is dialog.welcome_page
            assert settings.onboarding_seen == "true"
            events.append("intro")
            return guide_result
        assert dialog is login_dialog
        events.append("login")
        return QDIALOG_CODE.Rejected

    monkeypatch.setattr(root, "exec_dialog", execute)
    collection = root.RootCollection()
    if entry == "double_click":
        trigger = collection.handleDoubleClick
    else:
        action = collection.actions(None)[0]
        trigger = action.trigger
    trigger()
    assert events == ["intro", "create_login", "login"]
    stored.assert_called_once_with("onboarding_seen", "true")
    events.clear()
    trigger()
    assert events == ["create_login", "login"]
    stored.assert_called_once()


@pytest.mark.usefixtures("qgis_plugin_path")
@pytest.mark.parametrize("login_result", [QDIALOG_CODE.Accepted, QDIALOG_CODE.Rejected])
def test_returning_user_goes_directly_to_login(qgis_app, monkeypatch, login_result):
    from plugin_dir.kumoy.settings_manager import UserSettings
    from plugin_dir.ui.browser import root

    monkeypatch.setattr(
        root, "get_settings", lambda: UserSettings(onboarding_seen="true")
    )
    guide = Mock()
    monkeypatch.setattr(root, "OnboardingDialog", guide)
    monkeypatch.setattr(root, "DialogLogin", Mock())
    execute = Mock(return_value=login_result)
    monkeypatch.setattr(root, "exec_dialog", execute)
    collection = root.RootCollection()
    select_project = Mock()
    monkeypatch.setattr(collection, "select_project", select_project)
    collection.login()
    guide.assert_not_called()
    execute.assert_called_once()
    assert select_project.call_count == (
        1 if login_result == QDIALOG_CODE.Accepted else 0
    )
