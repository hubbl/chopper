"""Detect absolute envelope rises over a sample-rate-independent time span."""

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


class EnvelopeAttackDetector:
    def detect(
        self, samples: NDArray[np.float64], samplerate: int, parameters: Mapping[str, float]
    ) -> list[int]:
        settings = validated_parameters("envelope_attack", parameters)
        env = prepare_envelope(samples, samplerate, settings)
        if not len(env):
            return []
        lag = max(1, int(round(settings["comparison_ms"] * samplerate / 1000)))
        # Extend the first value backwards: audio already active at the start
        # must not create a fictitious attack from zero.
        earlier = env[np.maximum(np.arange(len(env)) - lag, 0)]
        rise = env - earlier
        onsets = rising_crossings(rise, 10 ** (settings["rise_db"] / 20))
        return onset_cuts(onsets, len(env), samplerate, settings)


register(
    DetectorSpec(
        "envelope_attack",
        "detector.envelope_attack.name",
        EnvelopeAttackDetector(),
        (
            Parameter("rise_db", "parameter.rise", -26, -96, 0, 1, "unit.dbfs"),
            Parameter("comparison_ms", "parameter.comparison", 5, 0.1, 100, 0.1, "unit.ms"),
            *ONSET_PARAMETERS,
        ),
    )
)
