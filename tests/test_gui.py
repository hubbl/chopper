import time

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QWheelEvent
from PySide6.QtTest import QTest

from chopper.app import MainWindow
from chopper.document import AudioDocument, Marker


def wait_jobs(app, window):
    deadline = time.monotonic() + 10
    while window.controller.jobs and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert not window.controller.jobs


@pytest.mark.parametrize("target", ["window", "waveform", "header"])
def test_drop_wav_loads_and_analyzes(app, tmp_path, monkeypatch, target):
    window = MainWindow()
    window.show()
    app.processEvents()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    path = tmp_path / "Aufnahme ä.WAV"
    values = np.zeros(1000)
    values[300:350] = np.hanning(50)
    sf.write(path, values, 1000)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    receiver = {
        "window": window,
        "waveform": window.waveform.viewport(),
        "header": window.file_label,
    }[target]
    enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(receiver, enter)
    assert enter.isAccepted()
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(receiver, drop)
    assert drop.isAccepted()
    wait_jobs(app, window)
    assert not errors
    assert window.controller.document.audio.path == path
    assert len(window.controller.document.markers) == 1
    window.close()


@pytest.mark.parametrize("kind", ["other", "remote", "multiple", "directory", "busy"])
def test_invalid_or_busy_drop_is_ignored(app, tmp_path, monkeypatch, kind):
    window = MainWindow()
    opened = []
    monkeypatch.setattr(window.controller, "open_path", opened.append)
    path = tmp_path / ("audio.mp3" if kind == "other" else "audio.wave")
    if kind == "directory":
        path.mkdir()
    else:
        path.touch()
    urls = [QUrl.fromLocalFile(str(path))]
    if kind == "remote":
        urls = [QUrl("https://example.com/audio.wav")]
    elif kind == "multiple":
        urls *= 2
    elif kind == "busy":
        window.open_action.setEnabled(False)
    mime = QMimeData()
    mime.setUrls(urls)
    enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(enter)
    assert not enter.isAccepted()
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop)
    assert not drop.isAccepted()
    assert not opened
    window.close()


def test_background_open_analysis_and_export(app, tmp_path, monkeypatch):
    window = MainWindow()
    window.show()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    monkeypatch.setattr("chopper.app.QMessageBox.information", lambda *args: None)
    values = np.zeros((1000, 2))
    values[300:350, 0] = np.hanning(50)
    values[:, 1] = -values[:, 0]
    path = tmp_path / "source.wav"
    sf.write(path, values, 1000, subtype="PCM_24")
    window.controller.open_path(path)
    wait_jobs(app, window)
    assert not errors
    assert window.controller.document is not None
    assert len(window.controller.document.markers) == 1
    assert window.export_button.isEnabled()
    destination = tmp_path / "output"
    destination.mkdir()
    window.controller.export_to(destination)
    wait_jobs(app, window)
    assert not errors
    assert len(list(destination.glob("*.wav"))) == 2
    window.close()


def test_mouse_add_remove_drag_and_undo(app, audio):
    window = MainWindow()
    window.show()
    controller = window.controller
    controller.document = AudioDocument(audio)
    controller.player.set_audio(audio)
    view = window.waveform
    view.set_document(controller.document)
    controller.document.markers_changed.connect(controller.markers_changed)
    window.update_actions()
    app.processEvents()
    viewport = view.viewport()

    def point(sample):
        return view.mapFromScene(QPointF(sample, 0.5))

    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=point(300))
    app.processEvents()
    assert len(controller.document.markers) == 1
    marker = controller.document.markers[0]
    before = marker.sample
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point(before))
    QTest.mouseMove(viewport, point(400))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point(400))
    app.processEvents()
    assert abs(controller.document.markers[0].sample - 400) <= 2
    assert controller.undo.count() == 2
    controller.undo.undo()
    assert controller.document.markers[0].sample == before
    controller.undo.redo()
    QTest.mouseDClick(
        viewport, Qt.MouseButton.LeftButton, pos=point(controller.document.markers[0].sample)
    )
    assert not controller.document.markers
    controller.undo.undo()
    assert len(controller.document.markers) == 1
    window.close()


def test_open_guesses_threshold_but_reanalysis_preserves_manual_value(app, tmp_path, monkeypatch):
    window = MainWindow()
    window.algorithm.setCurrentIndex(window.algorithm.findData("peaks"))
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    values = np.zeros(30000)
    values[np.arange(100, 19101, 1000)] = np.linspace(0.001, 0.03, 20)
    path = tmp_path / "quiet.wav"
    sf.write(path, values, 1000, subtype="FLOAT")
    window.controller.open_path(path)
    wait_jobs(app, window)
    assert not errors
    assert len(window.controller.document.markers) == 10
    threshold = window.parameter_widgets["threshold_db"]
    assert threshold.value() < -24
    threshold.setValue(-24)
    window.analyze_button.click()
    wait_jobs(app, window)
    assert threshold.value() == -24
    assert not window.controller.document.markers
    window.controller.open_path(path)
    wait_jobs(app, window)
    assert not errors
    assert threshold.value() < -24
    assert len(window.controller.document.markers) == 10
    window.close()


def test_failed_open_keeps_previous_document(app, audio, tmp_path, monkeypatch):
    window = MainWindow()
    controller = window.controller
    controller.document = AudioDocument(audio)
    original = controller.document
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    controller.open_path(tmp_path / "missing.wav")
    wait_jobs(app, window)
    assert errors
    assert controller.document is original
    window.close()


def test_detection_does_not_overwrite_concurrent_edits(app, audio):
    window = MainWindow()
    controller = window.controller
    controller.document = AudioDocument(audio)
    controller.player.set_audio(audio)
    window.waveform.set_document(controller.document)
    controller.analyze()
    controller.document.set_markers([Marker(100)])
    wait_jobs(app, window)
    assert [m.sample for m in controller.document.markers] == [100]
    assert "during analysis" in window.statusBar().currentMessage()
    window.close()


def test_zoom_preserves_marker_sample_and_pixel_hit_tolerance(app, audio):
    window = MainWindow()
    window.show()
    doc = AudioDocument(audio)
    marker = Marker(500)
    doc.set_markers([marker])
    view = window.waveform
    view.set_document(doc)
    app.processEvents()
    point = view.mapFromScene(QPointF(500, 0.5))
    scale_before = view.transform().m11()
    event = QWheelEvent(
        QPointF(point),
        QPointF(view.viewport().mapToGlobal(point)),
        QPoint(),
        QPoint(0, 240),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(view.viewport(), event)
    assert view.transform().m11() > scale_before
    assert doc.markers == (marker,)
    zoomed_point = view.mapFromScene(QPointF(500, 0.5))
    assert abs(zoomed_point.x() - point.x()) <= 2
    assert view.marker_at(zoomed_point + QPoint(6, 0)) == marker
    assert view.marker_at(zoomed_point + QPoint(8, 0)) is None
    view.fit_all()
    assert doc.markers == (marker,)
    window.close()


def test_latest_open_wins(app, tmp_path, monkeypatch):
    window = MainWindow()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    for name in ("first.wav", "second.wav"):
        sf.write(tmp_path / name, np.zeros(1000), 1000)
    window.controller.open_path(tmp_path / "first.wav")
    window.controller.open_path(tmp_path / "second.wav")
    wait_jobs(app, window)
    assert not errors
    assert window.controller.document.audio.path.name == "second.wav"
    window.close()


def test_registry_drives_algorithm_fields(app):
    from chopper.detectors import REGISTRY, DetectorSpec, Parameter, register

    class AnotherDetector:
        def detect(self, samples, samplerate, parameters):
            return []

    register(
        DetectorSpec(
            "gui-test",
            "Anderer Algorithmus",
            AnotherDetector(),
            (Parameter("sensitivity", "Empfindlichkeit", 7, 0, 10, 1),),
        )
    )
    try:
        window = MainWindow()
        window.algorithm.setCurrentIndex(window.algorithm.findData("gui-test"))
        assert list(window.parameter_widgets) == ["sensitivity"]
        assert window.parameter_widgets["sensitivity"].value() == 7
        window.close()
    finally:
        REGISTRY.pop("gui-test")


def test_four_algorithms_keep_independent_values_without_analysis(app):
    from chopper.detectors import REGISTRY

    window = MainWindow()
    try:
        assert window.algorithm.count() == 4
        assert window.algorithm.currentData() == "envelope_hysteresis"
        for spec in REGISTRY.values():
            window.algorithm.setCurrentIndex(window.algorithm.findData(spec.id))
            assert set(window.parameter_widgets) == {p.key for p in spec.parameters}
            window.parameter_widgets["lead_ms"].setValue(23)
        for spec in REGISTRY.values():
            window.algorithm.setCurrentIndex(window.algorithm.findData(spec.id))
            assert window.parameter_widgets["lead_ms"].value() == 23
        window.parameter_widgets["lead_ms"].setValue(77)
        window.algorithm.setCurrentIndex(window.algorithm.findData("envelope_hysteresis"))
        assert window.parameter_widgets["lead_ms"].value() == 23
        assert not window.controller.jobs
    finally:
        window.close()


@pytest.mark.parametrize(
    "detector_id", ["envelope_threshold", "envelope_hysteresis", "envelope_attack"]
)
def test_new_analysis_preserves_manual_markers_and_supports_undo(
    app, tmp_path, monkeypatch, detector_id
):
    window = MainWindow()
    errors = []
    monkeypatch.setattr(window, "show_error", errors.append)
    window.algorithm.setCurrentIndex(window.algorithm.findData(detector_id))
    values = np.zeros(1000)
    values[200:300] = 0.5
    values[600:700] = 0.8
    path = tmp_path / "bursts.wav"
    sf.write(path, values, 1000, subtype="FLOAT")
    before_parameters = {key: widget.value() for key, widget in window.parameter_widgets.items()}
    window.controller.open_path(path)
    wait_jobs(app, window)
    assert not errors
    assert before_parameters == {
        key: widget.value() for key, widget in window.parameter_widgets.items()
    }
    doc = window.controller.document
    assert len(doc.markers) == 2
    window.controller.add_marker(400)
    before = doc.markers
    window.parameter_widgets["lead_ms"].setValue(60)
    window.analyze_button.click()
    wait_jobs(app, window)
    assert not errors
    assert len(doc.markers) == 3
    assert [m for m in doc.markers if not m.automatic] == [m for m in before if not m.automatic]
    assert [m.sample for m in doc.markers if m.automatic] != [
        m.sample for m in before if m.automatic
    ]
    after = doc.markers
    window.controller.undo.undo()
    assert doc.markers == before
    window.controller.undo.redo()
    assert doc.markers == after
    window.close()


def test_parameter_buttons_match_wheel_steps(app):
    from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox

    from chopper.detectors import REGISTRY

    window = MainWindow()
    window.show()
    for spec in REGISTRY.values():
        window.algorithm.setCurrentIndex(window.algorithm.findData(spec.id))
        app.processEvents()
        for parameter in spec.parameters:
            spin = window.parameter_widgets[parameter.key]
            spin.setValue(parameter.minimum)
            option = QStyleOptionSpinBox()
            spin.initStyleOption(option)
            up = spin.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, spin
            )
            down = spin.style().subControlRect(
                QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, spin
            )
            QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=up.center())
            stepped = spin.value()
            assert stepped == pytest.approx(parameter.minimum + parameter.step)
            QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=down.center())
            assert spin.value() == parameter.minimum
            event = QWheelEvent(
                QPointF(spin.rect().center()),
                QPointF(spin.mapToGlobal(spin.rect().center())),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            app.sendEvent(spin, event)
            assert spin.value() == stepped
    window.close()


def test_automatic_updates_and_manual_mode(app, audio, monkeypatch):
    window = MainWindow()
    controller = window.controller
    controller.document = AudioDocument(audio)
    controller.player.set_audio(audio)
    window.waveform.set_document(controller.document)
    calls = []

    def detect(spec, audio, parameters, guess_threshold):
        calls.append((spec.id, parameters["lead_ms"]))
        return [100 + round(parameters["lead_ms"])], None

    monkeypatch.setattr("chopper.app.detect_audio", detect)
    window.update_actions()
    assert window.auto_update.isChecked()
    assert not window.analyze_button.isEnabled()
    window.parameter_widgets["lead_ms"].setValue(23)
    wait_jobs(app, window)
    assert [m.sample for m in controller.document.markers] == [123]
    window.auto_update.setChecked(False)
    assert window.analyze_button.isEnabled()
    window.parameter_widgets["lead_ms"].setValue(31)
    assert len(calls) == 1
    window.analyze_button.click()
    wait_jobs(app, window)
    assert [m.sample for m in controller.document.markers] == [131]
    window.parameter_widgets["lead_ms"].setValue(41)
    window.auto_update.setChecked(True)
    wait_jobs(app, window)
    assert [m.sample for m in controller.document.markers] == [141]
    window.algorithm.setCurrentIndex(window.algorithm.findData("peaks"))
    wait_jobs(app, window)
    assert calls[-1][0] == "peaks"
    window.close()


def test_rapid_parameter_changes_only_apply_latest_result(app, audio, monkeypatch):
    from threading import Event

    window = MainWindow()
    controller = window.controller
    controller.document = AudioDocument(audio)
    controller.player.set_audio(audio)
    window.waveform.set_document(controller.document)
    release = Event()
    calls = []
    applied = []
    controller.document.markers_changed.connect(
        lambda: applied.append([m.sample for m in controller.document.markers])
    )

    def detect(spec, audio, parameters, guess_threshold):
        calls.append(parameters["lead_ms"])
        assert release.wait(5)
        return [100 + round(parameters["lead_ms"])], None

    monkeypatch.setattr("chopper.app.detect_audio", detect)
    window.parameter_widgets["lead_ms"].setValue(21)
    window.parameter_widgets["lead_ms"].setValue(31)
    window.parameter_widgets["lead_ms"].setValue(41)
    release.set()
    wait_jobs(app, window)
    assert calls == [21, 41]
    assert applied == [[141]]
    window.close()
