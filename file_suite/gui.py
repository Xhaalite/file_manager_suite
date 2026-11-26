"""PyQt6 desktop interface for indexing files and finding duplicates."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPalette, QShowEvent
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .pipeline import FileSuitePipeline, ProgressEvent, ScanConfig
from .schema import format_size


class WorkerSignals(QObject):
    progress = pyqtSignal(object)
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()


class TaskWorker(QRunnable):
    """Run a blocking backend action without freezing the Qt event loop."""

    def __init__(self, action: Callable[[WorkerSignals], Any]) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.action = action

    def run(self) -> None:
        try:
            self.signals.result.emit(self.action(self.signals))
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", detail: str = "") -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        title_label = QLabel(title.upper())
        title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("metricDetail")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class FileSuiteWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("File Manager Suite")
        self.resize(1320, 850)
        self.setMinimumSize(640, 480)
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: list[TaskWorker] = []
        self.pipeline: Optional[FileSuitePipeline] = None
        self._file_rows: list[dict[str, Any]] = []
        self._duplicate_rows: list[dict[str, Any]] = []
        self._build_ui()
        self._load_sample_directories()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if sys.platform == "win32":
            self._apply_dark_title_bar()

    def _apply_dark_title_bar(self) -> None:
        import ctypes
        from ctypes import wintypes

        dwmapi = ctypes.WinDLL("dwmapi")
        set_attribute = dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        set_attribute.restype = wintypes.HRESULT
        dark_mode = ctypes.c_int(1)
        hwnd = wintypes.HWND(int(self.winId()))
        for attribute in (20, 19):
            result = set_attribute(
                hwnd,
                attribute,
                ctypes.byref(dark_mode),
                ctypes.sizeof(dark_mode),
            )
            if result == 0:
                break

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 18, 28, 18)
        brand = QVBoxLayout()
        title = QLabel("File Manager Suite")
        title.setObjectName("appTitle")
        subtitle = QLabel("Index, compare, and report on your files")
        subtitle.setObjectName("appSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header_layout.addLayout(brand)
        header_layout.addStretch()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusPill")
        header_layout.addWidget(self.status_label)
        root_layout.addWidget(header)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 14)
        content_layout.setSpacing(16)

        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        page_title = QLabel("Scan workspace")
        page_title.setObjectName("pageTitle")
        page_subtitle = QLabel("Choose folders, configure your scan, and review the results.")
        page_subtitle.setObjectName("muted")
        heading_text.addWidget(page_title)
        heading_text.addWidget(page_subtitle)
        heading.addLayout(heading_text)
        heading.addStretch()
        self.run_button = QPushButton("Run full scan")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self._run_scan)
        heading.addWidget(self.run_button)
        content_layout.addLayout(heading)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        self.files_card = MetricCard("Files indexed")
        self.size_card = MetricCard("Total size")
        self.duplicate_card = MetricCard("Duplicate groups")
        self.reclaim_card = MetricCard("Space reclaimable")
        self.metric_cards = (
            self.files_card,
            self.size_card,
            self.duplicate_card,
            self.reclaim_card,
        )
        self.cards_layout = cards
        self._place_metric_cards(columns=4)
        content_layout.addLayout(cards)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        settings_scroll = self._build_settings_panel()
        settings_scroll.setMinimumWidth(230)
        results_panel = self._build_results_panel()
        results_panel.setMinimumWidth(340)
        splitter.addWidget(settings_scroll)
        splitter.addWidget(results_panel)
        splitter.setSizes([300, 900])
        self.splitter = splitter
        content_layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(260)
        self.progress_label = QLabel("Ready to scan")
        self.progress_label.setObjectName("muted")
        footer.addWidget(self.progress)
        footer.addWidget(self.progress_label, 1)
        self.save_session_button = QPushButton("Save session")
        self.save_session_button.clicked.connect(self._save_session)
        self.load_session_button = QPushButton("Open session")
        self.load_session_button.clicked.connect(self._load_session)
        footer.addWidget(self.save_session_button)
        footer.addWidget(self.load_session_button)
        content_layout.addLayout(footer)

        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)
        self._set_style()

    def _place_metric_cards(self, columns: int) -> None:
        while self.cards_layout.count():
            self.cards_layout.takeAt(0)
        for column in range(4):
            self.cards_layout.setColumnStretch(column, 0)
        for index, card in enumerate(self.metric_cards):
            self.cards_layout.addWidget(card, index // columns, index % columns)
            self.cards_layout.setColumnStretch(index % columns, 1)
        self._card_columns = columns

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "cards_layout"):
            return
        columns = 2 if event.size().width() < 1120 else 4
        if self._card_columns != columns:
            self._place_metric_cards(columns)
        if hasattr(self, "splitter") and event.size().width() < 1000:
            self.splitter.setSizes([230, max(340, event.size().width() - 290)])

    def _build_settings_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("Scan settings")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        label = QLabel("SOURCE FOLDERS")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.directory_list = QListWidget()
        self.directory_list.setMinimumHeight(110)
        self.directory_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.directory_list, 1)
        add_button = QPushButton("Add folder")
        add_button.clicked.connect(self._add_directory)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_directories)
        layout.addWidget(add_button)
        layout.addWidget(remove_button)

        label = QLabel("DIRECTORY DIFF")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.diff_left_edit = QLineEdit()
        self.diff_left_edit.setPlaceholderText("Left folder")
        self.diff_right_edit = QLineEdit()
        self.diff_right_edit.setPlaceholderText("Right folder")
        left_browse = QPushButton("Choose left folder")
        right_browse = QPushButton("Choose right folder")
        left_browse.clicked.connect(lambda: self._choose_diff_folder(self.diff_left_edit))
        right_browse.clicked.connect(lambda: self._choose_diff_folder(self.diff_right_edit))
        layout.addWidget(self.diff_left_edit)
        layout.addWidget(left_browse)
        layout.addWidget(self.diff_right_edit)
        layout.addWidget(right_browse)
        diff_button = QPushButton("Run directory diff")
        diff_button.clicked.connect(self._run_diff)
        layout.addWidget(diff_button)

        label = QLabel("OUTPUT FOLDER")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.output_edit = QLineEdit("suite_output")
        browse_output = QPushButton("Browse")
        browse_output.clicked.connect(self._choose_output)
        layout.addWidget(self.output_edit)
        layout.addWidget(browse_output)

        self.recursive_check = QCheckBox("Include subfolders")
        self.recursive_check.setChecked(True)
        self.hidden_check = QCheckBox("Include hidden files")
        self.hidden_check.setChecked(True)
        layout.addWidget(self.recursive_check)
        layout.addWidget(self.hidden_check)

        label = QLabel("DUPLICATE DETECTION")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.algo_combo = QComboBox()
        self.algo_combo.addItems(["sha256", "blake2b", "md5"])
        layout.addWidget(self.algo_combo)
        min_label = QLabel("Minimum file size")
        min_label.setObjectName("fieldLabel")
        layout.addWidget(min_label)
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 2_147_483_647)
        self.min_size_spin.setValue(1)
        self.min_size_spin.setSuffix(" bytes")
        layout.addWidget(self.min_size_spin)

        label = QLabel("REPORTS")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.xlsx_check = QCheckBox("Excel workbook (.xlsx)")
        self.xlsx_check.setChecked(True)
        self.png_check = QCheckBox("PNG preview")
        self.png_check.setChecked(False)
        layout.addWidget(self.xlsx_check)
        layout.addWidget(self.png_check)
        self.png_check.toggled.connect(self._update_export_state)
        self.xlsx_check.toggled.connect(self._update_export_state)

        self.open_output_button = QPushButton("Open output folder")
        self.open_output_button.clicked.connect(self._open_output)
        layout.addWidget(self.open_output_button)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        return scroll

    def _build_results_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        title = QLabel("Results")
        title.setObjectName("sectionTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter results...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMaximumWidth(260)
        self.search_edit.textChanged.connect(self._filter_tables)
        toolbar.addWidget(self.search_edit)
        layout.addLayout(toolbar)

        self.tabs = QTabWidget()
        self.files_table = self._make_table(
            ["Name", "Type", "Category", "Size", "Modified", "Path"]
        )
        self.files_table.cellDoubleClicked.connect(self._open_file_location)
        self.duplicates_table = self._make_table(
            ["Group", "Name", "Copies", "File size", "Reclaimable", "Path"]
        )
        self.duplicates_table.cellDoubleClicked.connect(self._open_file_location)
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setPlaceholderText("Scan progress and warnings will appear here.")
        self.tabs.addTab(self.files_table, "File index")
        self.tabs.addTab(self.duplicates_table, "Duplicates")
        self.tabs.addTab(self.activity_log, "Activity")
        layout.addWidget(self.tabs, 1)
        return panel

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSortingEnabled(True)
        return table

    def _set_style(self) -> None:
        palette = QApplication.palette()
        colors = {
            QPalette.ColorRole.Window: "#0e1625",
            QPalette.ColorRole.WindowText: "#e5ebf5",
            QPalette.ColorRole.Base: "#111b2b",
            QPalette.ColorRole.AlternateBase: "#172337",
            QPalette.ColorRole.ToolTipBase: "#1c2a40",
            QPalette.ColorRole.ToolTipText: "#f1f5fb",
            QPalette.ColorRole.Text: "#e5ebf5",
            QPalette.ColorRole.Button: "#202d42",
            QPalette.ColorRole.ButtonText: "#e5ebf5",
            QPalette.ColorRole.BrightText: "#ffffff",
            QPalette.ColorRole.Highlight: "#315f9c",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.Link: "#80b8ff",
        }
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        QApplication.setPalette(palette)
        self.setStyleSheet("""
            QWidget {
                background: #0e1625;
                color: #e5ebf5;
                font-family: "Segoe UI";
                font-size: 14px;
            }
            #header { background: #111b2b; border-bottom: 1px solid #26354a; }
            #appTitle { background: transparent; color: #f4f7fc; font-size: 24px; font-weight: 700; }
            #appSubtitle { background: transparent; color: #aab8ce; font-size: 14px; }
            #statusPill {
                background: #18372f; color: #8de0b5; border: 1px solid #285442;
                border-radius: 14px; padding: 8px 15px; font-size: 13px; font-weight: 600;
            }
            #pageTitle { background: transparent; color: #f0f4fb; font-size: 28px; font-weight: 700; }
            #muted { background: transparent; color: #a1afc4; font-size: 14px; }
            #metricCard, #panel { background: #151f30; border: 1px solid #29374c; border-radius: 11px; }
            #metricTitle, #fieldLabel {
                background: transparent; color: #aab8ce; font-size: 12px;
                font-weight: 700; letter-spacing: 1px;
            }
            #metricValue { background: transparent; color: #f2f6fc; font-size: 28px; font-weight: 700; }
            #metricDetail { background: transparent; color: #a1afc4; font-size: 13px; }
            #sectionTitle { background: transparent; color: #edf2fa; font-size: 18px; font-weight: 700; }
            QPushButton {
                background: #202d42; color: #e5ebf5; border: 1px solid #34445c;
                border-radius: 7px; padding: 9px 14px; min-height: 22px; font-size: 14px;
            }
            QPushButton:hover { background: #2a3b55; border-color: #4a6384; }
            QPushButton:pressed { background: #18263a; }
            QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #6ea8f4;
            }
            QPushButton:disabled { background: #192437; color: #77869e; border-color: #29374c; }
            #primaryButton {
                background: #3478d4; color: #ffffff; border: 1px solid #4d8de2;
                font-weight: 700; padding: 10px 20px; min-height: 26px;
            }
            #primaryButton:hover { background: #4389e7; }
            #primaryButton:pressed { background: #2867b8; }
            QLineEdit, QComboBox, QSpinBox, QListWidget, QTextEdit, QTableWidget {
                background: #101a2a; color: #e0e8f3; border: 1px solid #344258;
                border-radius: 6px; padding: 8px; selection-background-color: #315f9c;
                selection-color: #ffffff;
            }
            QLineEdit, QComboBox, QSpinBox { min-height: 25px; }
            QLineEdit::placeholder { color: #8292aa; }
            QComboBox::drop-down { border: 0; width: 26px; }
            QComboBox QAbstractItemView {
                background: #182438; color: #e5ebf5; selection-background-color: #315f9c;
                border: 1px solid #344258;
            }
            QCheckBox { background: transparent; color: #d7e0ed; spacing: 9px; }
            QCheckBox::indicator {
                width: 18px; height: 18px; background: #101a2a;
                border: 1px solid #52627a; border-radius: 4px;
            }
            QCheckBox::indicator:checked { background: #3478d4; border-color: #6ea8f4; }
            QTabWidget::pane { background: #151f30; border: 1px solid #29374c; border-radius: 7px; top: -1px; }
            QTabBar { background: transparent; }
            QTabBar::tab {
                background: transparent; color: #a1afc4; padding: 11px 16px;
                margin-right: 4px; font-size: 14px;
            }
            QTabBar::tab:selected {
                color: #9bc5ff; border-bottom: 2px solid #69a6fa; font-weight: 700;
            }
            QHeaderView { background: #1b273a; }
            QHeaderView::section {
                background: #1b273a; color: #c4d0e0; border: 0;
                border-bottom: 1px solid #344258; padding: 10px 9px; font-weight: 700;
            }
            QTableWidget {
                background: #111b2b; alternate-background-color: #172337;
                gridline-color: #26354a; outline: 0;
            }
            QTableWidget::item { padding: 5px; }
            QTableWidget::item:selected { background: #294b75; color: #ffffff; }
            QProgressBar { background: #202d42; border: 0; border-radius: 4px; height: 9px; }
            QProgressBar::chunk { background: #5da0f2; border-radius: 4px; }
            QSplitter::handle { background: #0e1625; width: 8px; }
            QScrollBar:vertical { background: #111b2b; width: 12px; margin: 2px; }
            QScrollBar::handle:vertical { background: #3b4b62; border-radius: 5px; min-height: 28px; }
            QScrollBar::handle:vertical:hover { background: #536783; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background: #111b2b; height: 12px; margin: 2px; }
            QScrollBar::handle:horizontal { background: #3b4b62; border-radius: 5px; min-width: 28px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QToolTip { background: #1c2a40; color: #f1f5fb; border: 1px solid #40536d; padding: 5px; }
        """)

    def _load_sample_directories(self) -> None:
        sample_root = Path(__file__).resolve().parent.parent / "sample_data"
        for name in ("disk_c", "disk_d"):
            directory = sample_root / name
            if directory.is_dir():
                self._append_directory(directory)

    def _append_directory(self, directory: Path) -> None:
        resolved = str(directory.resolve())
        if not any(self.directory_list.item(i).text() == resolved for i in range(self.directory_list.count())):
            self.directory_list.addItem(QListWidgetItem(resolved))

    def _add_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select a folder")
        if directory:
            self._append_directory(Path(directory))

    def _remove_directories(self) -> None:
        for item in self.directory_list.selectedItems():
            self.directory_list.takeItem(self.directory_list.row(item))

    def _choose_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_edit.text())
        if directory:
            self.output_edit.setText(directory)

    def _choose_diff_folder(self, target: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose folder")
        if directory:
            target.setText(str(Path(directory).resolve()))

    def _update_export_state(self) -> None:
        self.run_button.setEnabled(self.xlsx_check.isChecked() or self.png_check.isChecked())

    def _config(self) -> ScanConfig:
        directories = [self.directory_list.item(i).text() for i in range(self.directory_list.count())]
        if not directories:
            raise ValueError("Add at least one source folder before starting a scan.")
        output_dir = self.output_edit.text().strip()
        if not output_dir:
            raise ValueError("Choose an output folder.")
        return ScanConfig(
            directories=directories,
            output_dir=output_dir,
            recursive=self.recursive_check.isChecked(),
            include_hidden=self.hidden_check.isChecked(),
            hash_algo=self.algo_combo.currentText(),
            min_size_bytes=self.min_size_spin.value(),
        )

    def _run_scan(self) -> None:
        try:
            config = self._config()
        except ValueError as exc:
            QMessageBox.warning(self, "Scan settings", str(exc))
            return
        export_xlsx = self.xlsx_check.isChecked()
        export_png = self.png_check.isChecked()

        def action(signals: WorkerSignals) -> FileSuitePipeline:
            pipeline = FileSuitePipeline(config, on_progress=signals.progress.emit)
            pipeline.run_all(export_xlsx=export_xlsx, export_png=export_png)
            pipeline.save_session()
            return pipeline

        self._start_worker(
            action,
            "Scanning folders…",
            on_result=self._scan_completed,
        )

    def _run_diff(self) -> None:
        left = self.diff_left_edit.text().strip()
        right = self.diff_right_edit.text().strip()
        if not left or not right:
            QMessageBox.warning(self, "Directory diff", "Choose both a left and right folder.")
            return
        output_dir = self.output_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "Directory diff", "Choose an output folder.")
            return

        def action(signals: WorkerSignals) -> tuple[FileSuitePipeline, dict[str, Any]]:
            config = ScanConfig(
                directories=[left, right],
                output_dir=output_dir,
                recursive=self.recursive_check.isChecked(),
                include_hidden=self.hidden_check.isChecked(),
                exclude_patterns=[],
            )
            pipeline = FileSuitePipeline(config, on_progress=signals.progress.emit)
            report = pipeline.run_directory_diff(Path(left), Path(right))
            return pipeline, report

        self._start_worker(
            action,
            "Comparing directories…",
            on_result=self._diff_completed,
        )

    def _start_worker(
        self,
        action: Callable[[WorkerSignals], Any],
        status: str,
        on_result: Optional[Callable[[Any], None]] = None,
    ) -> None:
        self.run_button.setEnabled(False)
        self.save_session_button.setEnabled(False)
        self.load_session_button.setEnabled(False)
        self.status_label.setText("Working")
        self.progress.setRange(0, 0)
        self.progress_label.setText(status)
        worker = TaskWorker(action)
        self._workers.append(worker)
        worker.signals.progress.connect(self._on_progress)
        if on_result is not None:
            worker.signals.result.connect(on_result)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda w=worker: self._worker_finished(w))
        self.thread_pool.start(worker)

    def _worker_finished(self, worker: TaskWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.run_button.setEnabled(self.xlsx_check.isChecked() or self.png_check.isChecked())
        self.save_session_button.setEnabled(True)
        self.load_session_button.setEnabled(True)
        if self.status_label.text() != "Error":
            self.status_label.setText("Ready")

    def _on_progress(self, event: ProgressEvent) -> None:
        self.progress_label.setText(event.message)
        if event.total_steps > 0:
            self.progress.setRange(0, event.total_steps)
            self.progress.setValue(event.step)
        self._log(event.message)

    def _on_worker_error(self, details: str) -> None:
        self.status_label.setText("Error")
        self.progress_label.setText("Operation failed")
        self._log(details)
        QMessageBox.critical(self, "Operation failed", details.splitlines()[-1] if details else "Unknown error")

    def _diff_completed(self, result: tuple[FileSuitePipeline, dict[str, Any]]) -> None:
        pipeline, report = result
        self.pipeline = pipeline
        summary = report["summary"]
        message = (
            f"Directory diff finished: {summary['total_differences']} differences "
            f"({summary['only_left']} left-only, {summary['only_right']} right-only, "
            f"{summary['changed']} changed, {summary['unchanged']} unchanged)."
        )
        self.status_label.setText("Diff complete")
        self._log(message)
        diff_path = Path(pipeline.state.config.output_dir) / "directory_diff.json"
        self._log(f"Created report: {diff_path.resolve()}")

    def _scan_completed(self, pipeline: FileSuitePipeline) -> None:
        self.pipeline = pipeline
        self._refresh_results()
        self._log("Scan finished successfully.")

    def _refresh_results(self) -> None:
        if self.pipeline is None:
            return
        state = self.pipeline.state
        index = state.merged_index or {}
        duplicates = state.duplicates_report or {}
        summary = index.get("summary", {})
        dup_summary = duplicates.get("summary", {})
        self.files_card.set_value(
            f"{summary.get('total_files', 0):,}",
            f"{summary.get('warning_count', 0):,} scan warnings",
        )
        self.size_card.set_value(summary.get("total_human", "0 B"), "Across all source folders")
        self.duplicate_card.set_value(
            f"{dup_summary.get('duplicate_groups', 0):,}",
            f"{dup_summary.get('total_duplicate_files', 0):,} duplicate files",
        )
        self.reclaim_card.set_value(
            dup_summary.get("reclaimable_human", "0 B"),
            "Potentially recoverable space",
        )
        self._file_rows = list(index.get("files", []))
        self._duplicate_rows = []
        for group in duplicates.get("duplicate_groups", []):
            for entry in group.get("files", []):
                self._duplicate_rows.append({
                    "group": group,
                    "file": entry,
                })
        self._populate_file_table()
        self._populate_duplicate_table()
        for warning in state.warnings:
            self._log(f"Warning: {warning}")
        for report in state.exported_reports:
            self._log(f"Created report: {report}")

    def _populate_file_table(self) -> None:
        self.files_table.setSortingEnabled(False)
        self.files_table.setRowCount(0)
        for entry in self._file_rows:
            row = self.files_table.rowCount()
            self.files_table.insertRow(row)
            values = (
                entry.get("name", ""),
                entry.get("extension", ""),
                entry.get("category", ""),
                entry.get("size_human", format_size(entry.get("size_bytes", 0))),
                entry.get("modified_at", ""),
                entry.get("full_path", ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 5:
                    item.setData(Qt.ItemDataRole.UserRole, entry.get("full_path", ""))
                self.files_table.setItem(row, column, item)
        self.files_table.setSortingEnabled(True)
        self._filter_tables()

    def _populate_duplicate_table(self) -> None:
        self.duplicates_table.setSortingEnabled(False)
        self.duplicates_table.setRowCount(0)
        for item in self._duplicate_rows:
            group, entry = item["group"], item["file"]
            row = self.duplicates_table.rowCount()
            self.duplicates_table.insertRow(row)
            values = (
                str(group.get("group_id", "")),
                entry.get("name", ""),
                str(group.get("copy_count", "")),
                group.get("size_human", ""),
                group.get("wasted_human", ""),
                entry.get("full_path", ""),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 5:
                    cell.setData(Qt.ItemDataRole.UserRole, entry.get("full_path", ""))
                self.duplicates_table.setItem(row, column, cell)
        self.duplicates_table.setSortingEnabled(True)
        self._filter_tables()

    def _filter_tables(self) -> None:
        query = self.search_edit.text().casefold()
        for table in (self.files_table, self.duplicates_table):
            for row in range(table.rowCount()):
                visible = not query or any(
                    query in (table.item(row, column).text().casefold() if table.item(row, column) else "")
                    for column in range(table.columnCount())
                )
                table.setRowHidden(row, not visible)

    def _open_file_location(self, row: int, _column: int) -> None:
        table = self.sender()
        if not isinstance(table, QTableWidget):
            return
        path_column = table.columnCount() - 1
        item = table.item(row, path_column)
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _save_session(self) -> None:
        if self.pipeline is None:
            QMessageBox.information(self, "Save session", "Run a scan or open a session first.")
            return
        suggested = str(Path(self.pipeline.state.config.output_dir) / "session.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save session", suggested, "File Suite session (*.json)"
        )
        if path:
            try:
                saved = self.pipeline.save_session(Path(path))
            except OSError as exc:
                QMessageBox.critical(self, "Could not save session", str(exc))
                return
            self._log(f"Session saved: {saved}")

    def _load_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open session", "", "File Suite session (*.json)"
        )
        if not path:
            return

        def action(_signals: WorkerSignals) -> FileSuitePipeline:
            return FileSuitePipeline.load_session(Path(path))

        self._start_worker(action, "Loading saved session…", on_result=self._session_loaded)

    def _session_loaded(self, pipeline: FileSuitePipeline) -> None:
        self.pipeline = pipeline
        config = pipeline.state.config
        self.directory_list.clear()
        for directory in config.directories:
            self._append_directory(Path(directory))
        self.output_edit.setText(config.output_dir)
        self.recursive_check.setChecked(config.recursive)
        self.hidden_check.setChecked(config.include_hidden)
        self.algo_combo.setCurrentText(config.hash_algo)
        self.min_size_spin.setValue(config.min_size_bytes)
        self._refresh_results()
        self._log("Session loaded.")

    def _open_output(self) -> None:
        output = Path(self.output_edit.text().strip() or ".")
        output.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.resolve())))

    def _log(self, message: str) -> None:
        self.activity_log.append(message)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("File Manager Suite")
    window = FileSuiteWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
