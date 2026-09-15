import pytest
from PySide6.QtGui import QUndoStack

from chopper.document import AudioDocument, Marker, MarkerCommand, moved_markers


def test_segments_are_contiguous_and_boundary_belongs_to_right_segment(audio):
    doc = AudioDocument(audio)
    doc.set_markers([Marker(700), Marker(200)])
    assert doc.segments() == [(0, 200), (200, 700), (700, 1000)]
    assert doc.segment_at(200) == (200, 700)
    assert doc.segment_at(-1) == (0, 200)
    assert doc.segment_at(1000) == (700, 1000)
    assert sum(b - a for a, b in doc.segments()) == 1000


@pytest.mark.parametrize("positions", [[0], [1000], [-1], [1.5], [200, 200]])
def test_invalid_marker_state_rejected_without_mutation(audio, positions):
    doc = AudioDocument(audio)
    with pytest.raises(ValueError):
        doc.set_markers([Marker(p) for p in positions])
    assert doc.markers == ()


def test_drag_undo_restores_identity_position_and_automatic_flag(audio, app):
    doc = AudioDocument(audio)
    first, second = Marker(200, True), Marker(400)
    doc.set_markers([first, second])
    stack = QUndoStack()
    before = doc.markers
    doc.set_markers(moved_markers(doc, first.id, 999))
    assert doc.marker(first.id).sample == 399
    doc.set_markers(moved_markers(doc, first.id, 300))
    stack.push(MarkerCommand(doc, doc.markers, "Drag", before))
    assert stack.count() == 1
    assert doc.marker(first.id).automatic is False
    stack.undo()
    assert doc.markers == before
    stack.redo()
    assert doc.marker(first.id).sample == 300
    assert doc.marker(first.id).automatic is False


def test_detection_preserves_manual_and_moved_markers_and_is_undoable(audio, app):
    doc = AudioDocument(audio)
    manual, automatic = Marker(200), Marker(400, True)
    doc.set_markers([manual, automatic])
    doc.set_markers(moved_markers(doc, automatic.id, 450))
    before = doc.markers
    stack = QUndoStack()
    stack.push(MarkerCommand(doc, doc.automatic_proposal([0, 200, 600, 600, 1000]), "Detect"))
    assert [(m.sample, m.automatic) for m in doc.markers] == [
        (200, False),
        (450, False),
        (600, True),
    ]
    stack.undo()
    assert doc.markers == before
    stack.redo()
    assert len(doc.markers) == 3
