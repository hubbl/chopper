"""Qt-independent detector contracts and registry."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from ..i18n import tr


class Detector(Protocol):
    def detect(
        self, samples: NDArray[np.float64], samplerate: int, parameters: Mapping[str, float]
    ) -> list[int]: ...


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    step: float
    suffix: str = ""


@dataclass(frozen=True)
class DetectorSpec:
    id: str
    name: str
    detector: Detector
    parameters: tuple[Parameter, ...]

    def defaults(self) -> dict[str, float]:
        return {p.key: p.default for p in self.parameters}


REGISTRY: dict[str, DetectorSpec] = {}


def register(spec: DetectorSpec) -> None:
    if spec.id in REGISTRY:
        raise ValueError(tr("error.detector_registered", id=spec.id))
    REGISTRY[spec.id] = spec
