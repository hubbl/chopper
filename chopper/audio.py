"""Immutable source audio and lossless sample-range export (no Qt dependency)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from .i18n import tr

SUPPORTED_SUBTYPES = {"PCM_U8", "PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE"}


@dataclass(frozen=True)
class AudioData:
    path: Path
    samples: NDArray[np.float64]
    samplerate: int
    subtype: str

    @property
    def frames(self) -> int:
        return len(self.samples)

    @property
    def channels(self) -> int:
        return self.samples.shape[1]


def load_wav(path: str | Path) -> AudioData:
    path = Path(path)
    with sf.SoundFile(path) as source:
        if (
            source.format not in {"WAV", "WAVEX", "RF64"}
            or source.subtype not in SUPPORTED_SUBTYPES
        ):
            raise ValueError(tr("error.wav_format"))
        if source.frames == 0:
            raise ValueError(tr("error.wav_empty"))
        # float64 exactly represents every supported integer PCM sample, including PCM32.
        samples = source.read(dtype="float64", always_2d=True)
        if not np.isfinite(samples).all():
            raise ValueError(tr("error.wav_samples"))
        samples.flags.writeable = False
        return AudioData(path, samples, source.samplerate, source.subtype)


class ExportError(Exception):
    def __init__(self, message: str, completed: Iterable[Path] = ()) -> None:
        self.completed = tuple(completed)
        details = "\n".join(str(p) for p in self.completed)
        super().__init__(message + (tr("export.partial", paths=details) if details else ""))


def export_segments(
    audio: AudioData, segments: Iterable[tuple[int, int]], directory: str | Path
) -> list[Path]:
    directory = Path(directory)
    ranges = tuple(segments)
    if not ranges or any(not 0 <= a < b <= audio.frames for a, b in ranges):
        raise ExportError(tr("error.segment_bounds"))
    if not directory.is_dir():
        raise ExportError(tr("error.export_directory"))
    paths = [directory / f"{audio.path.stem}_{i:03d}.wav" for i in range(1, len(ranges) + 1)]
    collisions = [p.name for p in paths if p.exists()]
    if collisions:
        raise ExportError(tr("error.export_collisions", files="\n".join(collisions)))
    completed = []
    for path, (start, end) in zip(paths, ranges):
        created = False
        try:
            # Exclusive creation also protects files created after the preflight check.
            with path.open("xb") as output:
                created = True
                sf.write(
                    output,
                    audio.samples[start:end],
                    audio.samplerate,
                    subtype=audio.subtype,
                    format="WAV",
                )
            completed.append(path)
        except Exception as exc:
            cleanup = ""
            if created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    cleanup = tr("error.export_cleanup", path=path)
            raise ExportError(tr("error.export", error=exc, cleanup=cleanup), completed) from exc
    return completed
