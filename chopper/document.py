"""The document owns marker state; Qt commands own reversible snapshots."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from uuid import uuid4

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand

from .audio import AudioData
from .i18n import tr


@dataclass(frozen=True)
class Marker:
    sample: int
    automatic: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)


class AudioDocument(QObject):
    markers_changed = Signal()

    def __init__(self, audio: AudioData) -> None:
        super().__init__()
        self.audio = audio
        self._markers: tuple[Marker, ...] = ()
        self.revision = 0

    @property
    def markers(self) -> tuple[Marker, ...]:
        return self._markers

    def set_markers(self, markers: Iterable[Marker]) -> None:
        ordered = tuple(sorted(markers, key=lambda m: m.sample))
        if any(type(m.sample) is not int or not 0 < m.sample < self.audio.frames for m in ordered):
            raise ValueError(tr("error.marker_bounds"))
        if len({m.sample for m in ordered}) != len(ordered) or len({m.id for m in ordered}) != len(
            ordered
        ):
            raise ValueError(tr("error.duplicate_markers"))
        if ordered != self._markers:
            self._markers = ordered
            self.revision += 1
            self.markers_changed.emit()

    def segments(self) -> list[tuple[int, int]]:
        boundaries = [0, *(m.sample for m in self.markers), self.audio.frames]
        return list(zip(boundaries, boundaries[1:]))

    def segment_at(self, sample: int) -> tuple[int, int]:
        sample = max(0, min(int(sample), self.audio.frames - 1))
        return self.segments()[bisect_right([m.sample for m in self.markers], sample)]

    def marker(self, marker_id: str) -> Marker | None:
        return next((m for m in self.markers if m.id == marker_id), None)

    def clamp_move(self, marker_id: str, sample: int) -> int:
        i = next(i for i, m in enumerate(self.markers) if m.id == marker_id)
        left = self.markers[i - 1].sample + 1 if i else 1
        right = (
            self.markers[i + 1].sample - 1 if i + 1 < len(self.markers) else self.audio.frames - 1
        )
        return max(left, min(int(sample), right))

    def automatic_proposal(self, positions: Iterable[int]) -> tuple[Marker, ...]:
        manual = [m for m in self.markers if not m.automatic]
        occupied = {m.sample for m in manual}
        auto = [
            Marker(p, True)
            for p in sorted(set(map(int, positions)))
            if 0 < p < self.audio.frames and p not in occupied
        ]
        return (*manual, *auto)


class MarkerCommand(QUndoCommand):
    def __init__(
        self,
        document: AudioDocument,
        after: Iterable[Marker],
        text: str,
        before: Iterable[Marker] | None = None,
    ) -> None:
        super().__init__(text)
        self.document = document
        self.before = tuple(document.markers if before is None else before)
        self.after = tuple(after)

    def redo(self) -> None:
        self.document.set_markers(self.after)

    def undo(self) -> None:
        self.document.set_markers(self.before)


def moved_markers(document: AudioDocument, marker_id: str, sample: int) -> tuple[Marker, ...]:
    sample = document.clamp_move(marker_id, sample)
    return tuple(
        replace(m, sample=sample, automatic=False) if m.id == marker_id else m
        for m in document.markers
    )
