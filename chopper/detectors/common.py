"""Shared envelope, validation and onset-to-cut conversion."""

from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from ..i18n import tr
from .base import REGISTRY, Parameter

ONSET_PARAMETERS = (
    Parameter("smoothing_ms", "parameter.smoothing", 5, 0, 100, 0.1, "unit.ms"),
    Parameter("distance_ms", "parameter.onset_distance", 100, 1, 10000, 10, "unit.ms"),
    Parameter("lead_ms", "parameter.onset_lead", 40, 0, 1000, 1, "unit.ms"),
)


def validated_parameters(detector_id: str, parameters: Mapping[str, float]) -> dict[str, float]:
    spec = REGISTRY[detector_id]
    settings = spec.defaults() | dict(parameters)
    for parameter in spec.parameters:
        value = settings[parameter.key]
        if not np.isfinite(value) or not parameter.minimum <= value <= parameter.maximum:
            raise ValueError(tr("error.parameter", label=tr(parameter.label)))
    return settings


def envelope(
    samples: NDArray[np.float64], samplerate: int, smoothing_ms: float
) -> NDArray[np.float64]:
    # Bei Stereo zählt der stärkere Kanal; Gegenphase kann sich so nicht auslöschen.
    values = np.max(np.abs(samples), axis=1) if samples.ndim == 2 else np.abs(samples)
    width = max(1, min(len(values), int(round(smoothing_ms * samplerate / 1000))))
    if width <= 1 or not len(values):
        return values
    # Am Rand wird der Randwert fortgesetzt. Kumulative Summen berechnen den
    # gleitenden Mittelwert effizient, auch bei großen Glättungsfenstern.
    left = (width - 1) // 2
    padded = np.pad(values, (left, width - 1 - left), mode="edge")
    sums = np.concatenate(([0.0], np.cumsum(padded, dtype=np.float64)))
    return (sums[width:] - sums[:-width]) / width


def prepare_envelope(
    samples: NDArray[np.float64], samplerate: int, settings: Mapping[str, float]
) -> NDArray[np.float64]:
    if samplerate <= 0:
        raise ValueError(tr("error.samplerate"))
    return envelope(samples, samplerate, settings["smoothing_ms"])


def rising_crossings(values: NDArray[np.float64], threshold: float) -> NDArray[np.intp]:
    return np.flatnonzero((values[:-1] < threshold) & (values[1:] >= threshold)) + 1


def onset_cuts(
    onsets: NDArray[np.intp] | list[int],
    frames: int,
    samplerate: int,
    settings: Mapping[str, float],
) -> list[int]:
    distance = max(1, int(round(settings["distance_ms"] * samplerate / 1000)))
    lead = int(np.ceil(settings["lead_ms"] * samplerate / 1000))
    previous = -distance
    cuts = []
    for onset in onsets:
        position = int(onset)
        if position - previous < distance:
            continue
        previous = position
        cut = position - lead
        if 0 < cut < frames:
            cuts.append(cut)
    return sorted(set(cuts))
