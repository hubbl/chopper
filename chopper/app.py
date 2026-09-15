"""Main window and orchestration; long-running operations use the Qt thread pool."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import QMimeData, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioData, export_segments, load_wav
from .detectors import REGISTRY, DetectorSpec, SimplePeakCutDetector
from .document import AudioDocument, Marker, MarkerCommand, moved_markers
from .player import AudioPlayer, PlayerState
from .waveform import WaveformView, format_time

T = TypeVar("T")


def detect_audio(
    spec: DetectorSpec, audio: AudioData, parameters: dict[str, float], guess_threshold: bool
) -> tuple[list[int], float | None]:
    settings = parameters.copy()
    threshold = None
    if guess_threshold and isinstance(spec.detector, SimplePeakCutDetector):
        threshold = spec.detector.guess_threshold(audio.samples, audio.samplerate, settings)
        settings["threshold_db"] = threshold
    return spec.detector.detect(audio.samples, audio.samplerate, settings), threshold


class WorkerSignals(QObject):
    finished = Signal(int, object, object)


class Worker(QRunnable):
    def __init__(self, job_id: int, function: Callable[[], Any]) -> None:
        super().__init__()
        self.job_id = job_id
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:
            self.signals.finished.emit(self.job_id, None, exc)
        else:
            self.signals.finished.emit(self.job_id, result, None)


@dataclass
class Job:
    worker: Worker
    success: Callable[[Any], None]
    failure: Callable[[str], None]
    kind: str


class ApplicationController(QObject):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.document: AudioDocument | None = None
        self.player = AudioPlayer()
        self.undo = QUndoStack(self)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs: dict[int, Job] = {}
        self._next_job = 0
        self._generation = 0
        self._drag_before: tuple[Marker, ...] | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def submit(
        self,
        kind: str,
        function: Callable[[], T],
        success: Callable[[T], None],
        failure: Callable[[str], None] | None = None,
    ) -> None:
        self._next_job += 1
        worker = Worker(self._next_job, function)
        worker.signals.finished.connect(self._finish)
        self.jobs[self._next_job] = Job(worker, success, failure or self.window.show_error, kind)
        self.window.update_actions()
        self.pool.start(worker)

    @Slot(int, object, object)
    def _finish(self, job_id: int, result: Any, error: Exception | None) -> None:
        job = self.jobs.pop(job_id)
        try:
            if error is not None:
                job.failure(str(error))
            else:
                job.success(result)
        except Exception as exc:
            self.window.show_error(str(exc))
        finally:
            self.window.update_actions()

    def open_path(self, path: str | Path) -> None:
        self._generation += 1
        generation = self._generation
        self.player.stop()
        self.window.statusBar().showMessage("WAV wird geladen …")

        def loaded(audio: AudioData) -> None:
            if generation != self._generation:
                return
            if self.document is not None:
                self.document.markers_changed.disconnect(self.markers_changed)
            self.undo.clear()
            self.document = AudioDocument(audio)
            self.player.set_audio(audio)
            self.window.waveform.set_document(self.document)
            self.document.markers_changed.connect(self.markers_changed)
            self.window.file_label.setText(audio.path.name)
            self.window.file_label.setToolTip(str(audio.path))
            self.window.metadata.setText(
                f"{format_time(audio.frames, audio.samplerate)}  ·  {audio.samplerate:,} Hz  ·  "
                f"{audio.channels} Kanal/Kanäle  ·  {audio.subtype}"
            )
            self.window.setWindowTitle(f"{audio.path.name} — Chopper")
            self.markers_changed()
            self.analyze(guess_threshold=True)

        def failed(message: str) -> None:
            if generation == self._generation:
                self.window.show_error(message)

        self.submit("load", lambda: load_wav(path), loaded, failed)

    def analyze(self, *, guess_threshold: bool = False) -> None:
        if self.document is None:
            return
        self.player.stop()
        document = self.document
        revision = document.revision
        generation = self._generation
        spec = REGISTRY[self.window.algorithm.currentData()]
        parameters = {key: widget.value() for key, widget in self.window.parameter_widgets.items()}
        self.window.statusBar().showMessage("Schnittpunkte werden erkannt …")

        def detected(result: tuple[list[int], float | None]) -> None:
            if document is not self.document or generation != self._generation:
                return
            positions, threshold = result
            self.show_guessed_threshold(spec.id, parameters, threshold)
            if revision != document.revision:
                self.window.statusBar().showMessage(
                    "Marker wurden während der Analyse geändert. Bitte erneut analysieren."
                )
                return
            after = document.automatic_proposal(positions)
            if tuple(sorted(after, key=lambda m: m.sample)) != document.markers:
                self.undo.push(MarkerCommand(document, after, "Automatische Erkennung"))
            self.window.statusBar().showMessage(
                f"Analyse abgeschlossen: {len(positions)} Schnittvorschläge."
            )

        def failed(message: str) -> None:
            if document is self.document and generation == self._generation:
                self.window.show_error(message)

        self.submit(
            "detect",
            lambda: detect_audio(spec, document.audio, parameters, guess_threshold),
            detected,
            failed,
        )

    def show_guessed_threshold(
        self, spec_id: str, parameters: dict[str, float], threshold: float | None
    ) -> None:
        if threshold is not None and self.window.algorithm.currentData() == spec_id:
            widget = self.window.parameter_widgets["threshold_db"]
            if widget.value() == parameters["threshold_db"]:
                widget.setValue(threshold)

    def add_marker(self, sample: int) -> None:
        if self.document and 0 < sample < self.document.audio.frames:
            if sample not in {m.sample for m in self.document.markers}:
                marker = Marker(sample)
                self.undo.push(
                    MarkerCommand(
                        self.document, (*self.document.markers, marker), "Marker hinzufügen"
                    )
                )
                self.window.waveform.selected_marker = marker.id
                self.window.waveform.refresh()

    def remove_marker(self, marker_id: str | None) -> None:
        if self.document and marker_id is not None and self.document.marker(marker_id):
            self.undo.push(
                MarkerCommand(
                    self.document,
                    [m for m in self.document.markers if m.id != marker_id],
                    "Marker entfernen",
                )
            )

    def begin_move(self, marker_id: str) -> None:
        if self.document is None:
            return
        self.player.stop()
        self._drag_before = self.document.markers
        self.window.update_actions()

    def preview_move(self, marker_id: str, sample: int) -> None:
        if self._drag_before is not None and self.document is not None:
            self.document.set_markers(moved_markers(self.document, marker_id, sample))

    def finish_move(self, marker_id: str) -> None:
        if self._drag_before is not None and self.document is not None:
            before, self._drag_before = self._drag_before, None
            after = self.document.markers
            if [(m.id, m.sample) for m in before] == [(m.id, m.sample) for m in after]:
                self.document.set_markers(before)
            else:
                self.undo.push(MarkerCommand(self.document, after, "Marker verschieben", before))
            self.window.update_actions()

    def markers_changed(self) -> None:
        if not self.document:
            return
        self.player.stop()
        self.select_segment(self.window.waveform.anchor)
        self.window.segment_count.setText(
            f"{len(self.document.markers)} Marker  ·  {len(self.document.segments())} Segmente"
        )

    def select_segment(self, sample: int | None) -> None:
        if self.document is None:
            return
        self.player.stop()
        audio = self.document.audio
        if sample is None:
            self.player.start, self.player.end = 0, audio.frames
            self.window.selection_label.setText("Gesamte Aufnahme")
        else:
            self.player.start, self.player.end = self.document.segment_at(sample)
            i = self.document.segments().index((self.player.start, self.player.end)) + 1
            self.window.selection_label.setText(
                f"Segment {i}  ·  {format_time(self.player.start, audio.samplerate)} – "
                f"{format_time(self.player.end, audio.samplerate)}"
            )
        self.player.seek(self.player.start)
        self.tick()

    def select_all(self) -> None:
        self.window.waveform.anchor = None
        self.select_segment(None)
        self.window.waveform.refresh()

    def toggle_play(self) -> None:
        if self.document is None:
            return
        try:
            _ = self.player.position
            if self.player.state == PlayerState.PLAYING:
                self.player.pause()
            else:
                self.player.resume()
        except Exception as exc:
            self.window.show_error(
                f"Wiedergabe nicht möglich. Bitte Audioausgabegerät prüfen.\n\n{exc}"
            )
        self.tick()

    def seek(self, direction: int) -> None:
        if self.document is not None:
            try:
                self.player.seek(
                    self.player.position + round(direction * self.document.audio.samplerate / 10)
                )
            except Exception as exc:
                self.window.show_error(f"Wiedergabe nicht möglich:\n{exc}")
            self.tick()

    def tick(self) -> None:
        if self.document is None:
            return
        position = self.player.position
        waveform = self.window.waveform
        if waveform.playhead != position:
            waveform.playhead = position
            waveform.viewport().update()
        self.window.time_label.setText(format_time(position, self.document.audio.samplerate))
        self.window.play_button.setText(
            "Pause" if self.player.state == PlayerState.PLAYING else "Abspielen"
        )
        if self.player.warning:
            self.window.statusBar().showMessage(self.player.warning, 5000)
            self.player.warning = ""

    def export_to(self, directory: str | Path) -> None:
        if self.document is None:
            return
        audio = self.document.audio
        segments = tuple(self.document.segments())
        self.window.statusBar().showMessage(f"{len(segments)} Segmente werden exportiert …")

        def exported(paths: list[Path]) -> None:
            self.window.statusBar().showMessage(
                f"{len(paths)} Segmente exportiert nach {directory}"
            )
            QMessageBox.information(
                self.window,
                "Export abgeschlossen",
                f"{len(paths)} WAV-Dateien wurden exportiert.\n\n{directory}",
            )

        self.submit("export", lambda: export_segments(audio, segments, directory), exported)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chopper — WAV-Splitter")
        self.resize(1250, 760)
        self.setMinimumSize(850, 560)
        self.setAcceptDrops(True)
        self.parameter_widgets: dict[str, QDoubleSpinBox] = {}
        self.controller = ApplicationController(self)
        self._build_ui()
        self._build_actions()
        self.update_actions()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(14)
        layout.addLayout(self._build_header())
        self._add_file_info(layout)
        layout.addLayout(self._build_body(), 1)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        layout.addLayout(self._build_transport())
        layout.addLayout(self._build_summary())
        help_label = QLabel(
            "Doppelklick: Marker setzen/entfernen  ·  Ziehen: verschieben  ·  Strg+Mausrad: Zoom  ·  Leertaste: Play/Pause"
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("muted")
        layout.addWidget(help_label)

        self._build_status_bar()
        self._apply_style()

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel("CHOPPER")
        title.setObjectName("brand")
        header.addWidget(title)
        header.addStretch()
        self.open_button = QPushButton("WAV öffnen …")
        self.open_button.clicked.connect(self.choose_file)
        self.export_button = QPushButton("Segmente exportieren …")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.choose_export)
        header.addWidget(self.open_button)
        header.addWidget(self.export_button)
        return header

    def _add_file_info(self, layout: QVBoxLayout) -> None:
        self.file_label = QLabel("Eine Aufnahme. Präzise Schnitte.")
        self.file_label.setObjectName("fileTitle")
        self.metadata = QLabel(
            "WAV ins Fenster ziehen oder öffnen → Peaks erkennen → Marker korrigieren → Exportieren"
        )
        self.metadata.setObjectName("muted")
        layout.addWidget(self.file_label)
        layout.addWidget(self.metadata)

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(self._build_waveform_column(), 1)
        body.addWidget(self._build_detector_group())
        return body

    def _build_waveform_column(self) -> QVBoxLayout:
        wave_column = QVBoxLayout()
        self.waveform = WaveformView()
        # Let file drops reach the main window instead of the graphics scene.
        self.waveform.setAcceptDrops(False)
        self.waveform.add_requested.connect(self.controller.add_marker)
        self.waveform.remove_requested.connect(self.controller.remove_marker)
        self.waveform.move_started.connect(self.controller.begin_move)
        self.waveform.move_preview.connect(self.controller.preview_move)
        self.waveform.move_finished.connect(self.controller.finish_move)
        self.waveform.segment_selected.connect(self.controller.select_segment)
        wave_column.addWidget(self.waveform, 1)
        legend = QHBoxLayout()
        legend.addWidget(
            QLabel(
                "<font color='#ffbd69'>● Automatisch</font>   <font color='#c3a3ff'>● Manuell</font>"
            )
        )
        legend.addStretch()
        self.zoom_out = QPushButton("Zoom -")
        self.zoom_in = QPushButton("Zoom +")
        self.fit_button = QPushButton("Alles anzeigen")
        self.zoom_out.clicked.connect(self.waveform.zoom_out)
        self.zoom_in.clicked.connect(self.waveform.zoom_in)
        self.fit_button.clicked.connect(self.waveform.fit_all)
        legend.addWidget(self.zoom_out)
        legend.addWidget(self.zoom_in)
        legend.addWidget(self.fit_button)
        wave_column.addLayout(legend)
        return wave_column

    def _build_detector_group(self) -> QGroupBox:
        self.detector_group = QGroupBox("Schnittpunkte erkennen")
        self.detector_group.setFixedWidth(285)
        detector_layout = QVBoxLayout(self.detector_group)
        self.algorithm = QComboBox()
        for spec in REGISTRY.values():
            self.algorithm.addItem(spec.name, spec.id)
        detector_layout.addWidget(self.algorithm)
        self.parameter_form = QFormLayout()
        self.parameter_form.setVerticalSpacing(6)
        self.parameter_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        detector_layout.addLayout(self.parameter_form)
        self.algorithm.currentIndexChanged.connect(self.build_parameters)
        self.build_parameters()
        self.analyze_button = QPushButton("Neu analysieren")
        self.analyze_button.clicked.connect(self.controller.analyze)
        detector_layout.addWidget(self.analyze_button)
        hint = QLabel(
            "Manuelle Marker bleiben erhalten.\nJede Analyse lässt sich rückgängig machen."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        detector_layout.addWidget(hint)
        detector_layout.addStretch()
        return self.detector_group

    def _build_transport(self) -> QHBoxLayout:
        transport = QHBoxLayout()
        self.play_button = QPushButton("Abspielen")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self.controller.toggle_play)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.controller.player.stop)
        self.all_button = QPushButton("Gesamte Aufnahme")
        self.all_button.clicked.connect(self.controller.select_all)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.all_button)
        self.time_label = QLabel("00:00.000")
        self.time_label.setObjectName("time")
        transport.addWidget(self.time_label)
        transport.addStretch()
        self.undo_button = QPushButton("Rückgängig")
        self.redo_button = QPushButton("Wiederholen")
        self.undo_button.clicked.connect(self.controller.undo.undo)
        self.redo_button.clicked.connect(self.controller.undo.redo)
        transport.addWidget(self.undo_button)
        transport.addWidget(self.redo_button)
        return transport

    def _build_summary(self) -> QHBoxLayout:
        summary = QHBoxLayout()
        self.selection_label = QLabel("Keine Aufnahme geladen")
        self.segment_count = QLabel("0 Marker  ·  0 Segmente")
        summary.addWidget(self.selection_label)
        summary.addStretch()
        summary.addWidget(self.segment_count)
        return summary

    def _build_status_bar(self) -> None:
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(140)
        self.progress.setFixedHeight(12)
        self.progress.setTextVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Bereit")

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #132232; color: #e1eaf2; font-family: 'Segoe UI'; font-size: 12px; }
            QLabel#brand { color: #53d7bc; font-size: 21px; font-weight: 800; letter-spacing: 3px; }
            QLabel#fileTitle { font-size: 20px; font-weight: 600; }
            QLabel#muted { color: #98afc2; font-size: 11px; }
            QLabel#time { font-family: Consolas; font-size: 20px; padding-left: 12px; }
            QPushButton { background: #243c51; border: 1px solid #36536b; border-radius: 5px; padding: 8px 12px; }
            QPushButton:hover { background: #31526d; }
            QPushButton:pressed { background: #3d6481; }
            QPushButton#primary { background: #53d7bc; color: #102b2b; border-color: #53d7bc; font-weight: 600; }
            QPushButton:disabled { background: #1c2b3a; color: #61768a; border-color: #293d50; }
            QGroupBox { border: 1px solid #345068; border-radius: 6px; margin-top: 9px; padding: 15px 10px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QDoubleSpinBox, QComboBox { background: #0f1d2b; border: 1px solid #3c5870; border-radius: 3px; padding: 5px; min-height: 18px; }
            QStatusBar { color: #98afc2; }
            QProgressBar { border: 0; background: #20374a; }
            QProgressBar::chunk { background: #53d7bc; }
            QMenu { background: #20374a; }
            QMenu::item:selected { background: #36536b; }
            QToolTip { background: #e1eaf2; color: #132232; border: 1px solid #98afc2; }
        """)

    def build_parameters(self) -> None:
        while self.parameter_form.rowCount():
            self.parameter_form.removeRow(0)
        self.parameter_widgets = {}
        spec = REGISTRY[self.algorithm.currentData()]
        for parameter in spec.parameters:
            spin = QDoubleSpinBox()
            spin.setRange(parameter.minimum, parameter.maximum)
            spin.setDecimals(1)
            spin.setSingleStep(parameter.step)
            spin.setSuffix(parameter.suffix)
            spin.setValue(parameter.default)
            spin.setKeyboardTracking(False)
            self.parameter_widgets[parameter.key] = spin
            self.parameter_form.addRow(parameter.label, spin)

    def _action(
        self, text: str, shortcut: str, callback: Callable[[], object], menu: QMenu | None = None
    ) -> QAction:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        self.addAction(action)
        if menu:
            menu.addAction(action)
        return action

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("Datei")
        self.open_action = self._action("WAV öffnen …", "Ctrl+O", self.choose_file, file_menu)
        self.export_action = self._action(
            "Segmente exportieren …", "Ctrl+E", self.choose_export, file_menu
        )
        self._action("Beenden", "Ctrl+Q", self.close, file_menu)
        edit_menu = self.menuBar().addMenu("Bearbeiten")
        self.undo_action = self.controller.undo.createUndoAction(self, "Rückgängig")
        self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.redo_action = self.controller.undo.createRedoAction(self, "Wiederholen")
        self.redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        self.controller.undo.canUndoChanged.connect(self.update_actions)
        self.controller.undo.canRedoChanged.connect(self.update_actions)
        self.delete_action = self._action(
            "Marker entfernen",
            "Delete",
            lambda: self.controller.remove_marker(self.waveform.selected_marker),
            edit_menu,
        )
        self.removeAction(self.delete_action)
        self.waveform.addAction(self.delete_action)
        self.delete_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.play_action = self._action("Abspielen / Pause", "Space", self.controller.toggle_play)
        # Seek belongs to the waveform so arrow keys continue editing numeric controls.
        for shortcut, direction in (("Left", -1), ("Right", 1)):
            action = QAction(self.waveform)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(lambda checked=False, d=direction: self.controller.seek(d))
            self.waveform.addAction(action)

    def update_actions(self, *args: object) -> None:
        if not hasattr(self, "export_action"):
            return
        ready = self.controller.document is not None
        kinds = {job.kind for job in self.controller.jobs.values()}
        dragging = self.controller._drag_before is not None
        for widget in (self.open_button, self.open_action):
            widget.setEnabled(not dragging and "load" not in kinds)
        for widget in (
            self.play_button,
            self.stop_button,
            self.all_button,
            self.play_action,
            self.fit_button,
            self.delete_action,
        ):
            widget.setEnabled(ready and not dragging)
        self.analyze_button.setEnabled(
            ready and not dragging and not kinds.intersection({"load", "detect"})
        )
        for widget in (self.export_button, self.export_action):
            widget.setEnabled(ready and not dragging and not kinds.intersection({"load", "export"}))
        for widget in (self.undo_button, self.undo_action):
            widget.setEnabled(not dragging and self.controller.undo.canUndo())
        for widget in (self.redo_button, self.redo_action):
            widget.setEnabled(not dragging and self.controller.undo.canRedo())
        self.progress.setVisible(bool(kinds))

    def _dropped_wav(self, mime: QMimeData) -> Path | None:
        if not self.open_action.isEnabled():
            return None
        urls = mime.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        if path.suffix.lower() in {".wav", ".wave"} and path.is_file():
            return path
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_wav(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._dropped_wav(event.mimeData())
        if path is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.controller.open_path(path)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "WAV öffnen", "", "WAV-Dateien (*.wav *.wave);;Alle Dateien (*)"
        )
        if path:
            self.controller.open_path(path)

    def choose_export(self) -> None:
        if self.controller.document is None:
            return
        path = QFileDialog.getExistingDirectory(
            self,
            "Zielordner für WAV-Segmente wählen",
            str(self.controller.document.audio.path.parent),
        )
        if path:
            self.controller.export_to(path)

    def show_error(self, message: str) -> None:
        self.statusBar().showMessage("Vorgang fehlgeschlagen")
        QMessageBox.warning(self, "Chopper", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.jobs:
            self.statusBar().showMessage(
                "Bitte den laufenden Vorgang abwarten und anschließend erneut schließen."
            )
            event.ignore()
            return
        self.controller.timer.stop()
        self.controller.player.close()
        event.accept()
