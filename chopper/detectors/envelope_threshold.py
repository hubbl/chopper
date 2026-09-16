"""Detect upward envelope threshold crossings."""

from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from .base import DetectorSpec, Parameter, register
from .common import (
    ONSET_PARAMETERS,
    onset_cuts,
    prepare_envelope,
    rising_crossings,
    validated_parameters,
)


class EnvelopeThresholdDetector:
    def detect(
        self, samples: NDArray[np.float64], samplerate: int, parameters: Mapping[str, float]
    ) -> list[int]:
        settings = validated_parameters("envelope_threshold", parameters)
        env = prepare_envelope(samples, samplerate, settings)
        onsets = rising_crossings(env, 10 ** (settings["threshold_db"] / 20))
        return onset_cuts(onsets, len(env), samplerate, settings)


register(
    DetectorSpec(
        "envelope_threshold",
        "detector.envelope_threshold.name",
        EnvelopeThresholdDetector(),
        (
            Parameter("threshold_db", "parameter.envelope_threshold", -26, -96, 0, 1, "unit.dbfs"),
            *ONSET_PARAMETERS,
        ),
    )
)
