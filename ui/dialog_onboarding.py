from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QKeySequence, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from .icons import MAIN_ICON
from ..pyqt_version import (
    Q_SIZE_POLICY,
    QShortcut,
    QT_ALIGN,
    QT_ASPECT_RATIO_MODE,
    QT_TEXT_FORMAT_PLAIN,
    QT_TRANSFORMATION_MODE,
)


class _GuideImageLabel(QLabel):
    """Fit the entire illustration without cropping, including on high-DPI displays."""

    def __init__(self):
        super().__init__()
        self._source = QPixmap()
        self.setAlignment(QT_ALIGN.AlignCenter)
        self.setSizePolicy(Q_SIZE_POLICY.Ignored, Q_SIZE_POLICY.Expanding)
        self.setMinimumHeight(260)

    def load(self, path: Path) -> None:
        self._source = QPixmap(str(path))
        self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._source.isNull():
            return
        ratio = self.devicePixelRatioF()
        scaled = self._source.scaled(
            round(self.width() * ratio),
            round(self.height() * ratio),
            QT_ASPECT_RATIO_MODE.KeepAspectRatio,
            QT_TRANSFORMATION_MODE.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.setPixmap(scaled)


class OnboardingDialog(QDialog):
    """A read-only introduction; navigation never changes the user's project."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("Getting Started with Kumoy"))
        self.resize(820, 720)
        self.setMinimumSize(640, 560)
        locale = QgsApplication.instance().locale().split("_")[0]
        self._image_dir = (
            Path(__file__).parent / "onboarding" / ("ja" if locale == "ja" else "en")
        )
        self._steps = [
            (
                i18n.tr("Login"),
                i18n.tr(
                    "Start sign-in in QGIS, sign in and authorize the connection in your web browser, then return to QGIS. QGIS receives the authentication result and connects to your Kumoy account."
                ),
                "login.svg",
            ),
            (
                i18n.tr("Select Project"),
                i18n.tr(
                    "In the Kumoy QGIS plugin, you work in one selected project at a time. Organizations contain teams, teams contain projects, and each project holds its own maps, vectors and rasters."
                ),
                "project.svg",
            ),
            (
                i18n.tr("Upload Your Data"),
                i18n.tr(
                    "Upload your GIS data to the Kumoy cloud. Vectors and rasters are stored in the selected project, ready for you and your team to use."
                ),
                "upload.svg",
            ),
            (
                i18n.tr("Read Data"),
                i18n.tr(
                    "The Browser panel is your gateway to the selected project's cloud data. Load maps, vectors and rasters into QGIS to explore and work with them."
                ),
                "read.svg",
            ),
            (
                i18n.tr("Edit Data"),
                i18n.tr(
                    "Work with Kumoy vector data using QGIS editing tools. When you save your layer edits, the changes are reflected in the Kumoy cloud and shared with your team. Editing requires an Owner or Admin role."
                ),
                "edit.svg",
            ),
            (
                i18n.tr("Publish Map"),
                i18n.tr(
                    "Share your map with the world. Make a saved Kumoy map public so anyone can view it in a web browser using its public URL."
                ),
                "publish.svg",
            ),
        ]
        self._introductory = True
        self._step = 0

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(24, 24, 24, 24)
        self.pages = QStackedWidget()
        outer_layout.addWidget(self.pages)

        self.start_tour_button = QPushButton(i18n.tr("Start Tour"))
        self.start_tour_button.clicked.connect(self._start_tour)
        self.skip_tour_button = QPushButton(i18n.tr("Start Using Kumoy"))
        self.skip_tour_button.clicked.connect(self.accept)
        self.welcome_page = self._create_message_page(
            i18n.tr("Welcome to Kumoy!"),
            i18n.tr("Take a quick tour of Kumoy, or start using it right away."),
            [self.skip_tour_button, self.start_tour_button],
        )
        self.pages.addWidget(self.welcome_page)

        self.tour_page = QWidget()
        self.pages.addWidget(self.tour_page)
        layout = QVBoxLayout(self.tour_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.progress_label = QLabel()
        layout.addWidget(self.progress_label)
        self.title_label = QLabel()
        font = self.title_label.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label)
        self.image_label = _GuideImageLabel()
        layout.addWidget(self.image_label, 1)
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        layout.addWidget(self.description_label)
        reminder = QLabel(
            i18n.tr("You can reopen this guide from Plugins > Kumoy > Getting Started.")
        )
        reminder.setWordWrap(True)
        layout.addWidget(reminder)

        buttons = QHBoxLayout()
        close_button = QPushButton(i18n.tr("Close"))
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        buttons.addStretch()
        self.back_button = QPushButton(i18n.tr("Back"))
        self.back_button.clicked.connect(self._back)
        buttons.addWidget(self.back_button)
        self.next_button = QPushButton()
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.finish_back_button = QPushButton(i18n.tr("Back"))
        self.finish_back_button.clicked.connect(self._return_to_tour)
        self.finish_button = QPushButton(i18n.tr("Start Using Kumoy"))
        self.finish_button.clicked.connect(self.accept)
        self.finish_page = self._create_message_page(
            i18n.tr("Let's get started!"),
            i18n.tr(
                "You're ready to explore Kumoy. You can reopen this tour from Plugins > Kumoy > Getting Started."
            ),
            [self.finish_back_button, self.finish_button],
        )
        self.pages.addWidget(self.finish_page)
        self._update_step()
        self._previous_shortcut = QShortcut(QKeySequence("Left"), self)
        self._previous_shortcut.activated.connect(self._navigate_back)
        self._next_shortcut = QShortcut(QKeySequence("Right"), self)
        self._next_shortcut.activated.connect(self._navigate_forward)

    def _create_message_page(
        self, title: str, description: str, buttons: list[QPushButton]
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        layout.addStretch()
        logo = QLabel()
        ratio = self.devicePixelRatioF()
        pixmap = MAIN_ICON.pixmap(round(220 * ratio), round(220 * ratio))
        pixmap.setDevicePixelRatio(ratio)
        logo.setPixmap(pixmap)
        logo.setAccessibleName("Kumoy")
        logo.setAlignment(QT_ALIGN.AlignCenter)
        layout.addWidget(logo)
        heading = QLabel(title)
        heading.setAlignment(QT_ALIGN.AlignCenter)
        heading.setWordWrap(True)
        heading.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        font = heading.font()
        font.setPointSize(font.pointSize() + 12)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        caption = QLabel(description)
        caption.setAlignment(QT_ALIGN.AlignCenter)
        caption.setWordWrap(True)
        caption.setTextFormat(QT_TEXT_FORMAT_PLAIN)
        layout.addWidget(caption)
        actions = QHBoxLayout()
        actions.addStretch()
        for button in buttons:
            button.setMinimumHeight(40)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def showEvent(self, event) -> None:
        self._reset_guide()
        super().showEvent(event)

    def _reset_guide(self) -> None:
        self._step = 0
        self._update_step()
        if self._introductory:
            self._show_welcome()
        else:
            self._return_to_tour()

    def show_guide(self, *, introductory: bool) -> None:
        """First use includes the introduction; menu access opens only the reference pages."""
        self._introductory = introductory
        if self.isVisible():
            self._reset_guide()
        self.show()

    def _navigate_back(self) -> None:
        current = self.pages.currentWidget()
        if current is self.finish_page:
            self._return_to_tour()
        elif current is self.tour_page:
            self._back()

    def _navigate_forward(self) -> None:
        current = self.pages.currentWidget()
        if current is self.welcome_page:
            self._start_tour()
        elif current is self.tour_page and (
            self._introductory or self._step < len(self._steps) - 1
        ):
            self._next()

    def _show_welcome(self) -> None:
        self.pages.setCurrentWidget(self.welcome_page)
        self.start_tour_button.setDefault(True)
        self.start_tour_button.setFocus()

    def _start_tour(self) -> None:
        self._step = 0
        self._update_step()
        self._return_to_tour()

    def _return_to_tour(self) -> None:
        self.pages.setCurrentWidget(self.tour_page)
        self.next_button.setDefault(True)
        self.next_button.setFocus()

    def _update_step(self) -> None:
        title, description, image_name = self._steps[self._step]
        self.progress_label.setText(
            i18n.tr("Step {} of {}").format(self._step + 1, len(self._steps))
        )
        self.title_label.setText(title)
        self.description_label.setText(description)
        self.image_label.setAccessibleName(title)
        self.image_label.setAccessibleDescription(description)
        self.image_label.load(self._image_dir / image_name)
        self.back_button.setEnabled(self._step > 0 or self._introductory)
        self.next_button.setText(
            i18n.tr("Close")
            if not self._introductory and self._step == len(self._steps) - 1
            else i18n.tr("Next")
        )

    def _back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._update_step()
        elif self._introductory:
            self._show_welcome()

    def _next(self) -> None:
        if self._step == len(self._steps) - 1:
            if not self._introductory:
                self.accept()
                return
            self.pages.setCurrentWidget(self.finish_page)
            self.finish_button.setDefault(True)
            self.finish_button.setFocus()
        else:
            self._step += 1
            self._update_step()
