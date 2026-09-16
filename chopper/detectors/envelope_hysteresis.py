"""Detect starts with separate activation and reset levels."""

from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from ..i18n import tr
from .base import DetectorSpec, Parameter, register
from .common import (
    ONSET_PARAMETERS,
    onset_cuts,
    prepare_envelope,
    rising_crossings,
    validated_parameters,
)


class EnvelopeHysteresisDetector:
    def detect(
        self, samples: NDArray[np.float64], samplerate: int, parameters: Mapping[str, float]
    ) -> list[int]:
        settings = validated_parameters("envelope_hysteresis", parameters)
        if settings["threshold_off_db"] >= settings["threshold_on_db"]:
            # raise ValueError(tr("error.hysteresis_thresholds"))
            # raising stops the updates from working. we just use the maximum value possible
            settings["threshold_off_db"] = settings["threshold_on_db"]
        env = prepare_envelope(samples, samplerate, settings)
        threshold_on = 10 ** (settings["threshold_on_db"] / 20)
        threshold_off = 10 ** (settings["threshold_off_db"] / 20)
        starts = rising_crossings(env, threshold_on)
        # Search reset events, rather than looping over every audio frame.
        resets = np.flatnonzero((env[:-1] >= threshold_off) & (env[1:] < threshold_off)) + 1
        active_since = 0 if len(env) and env[0] >= threshold_on else -1
        onsets = []
        for start in starts:
            reset_index = int(np.searchsorted(resets, start)) - 1
            if active_since < 0 or (reset_index >= 0 and resets[reset_index] > active_since):
                onsets.append(int(start))
                active_since = int(start)
        return onset_cuts(onsets, len(env), samplerate, settings)


register(
    DetectorSpec(
        "envelope_hysteresis",
        "detector.envelope_hysteresis.name",
        EnvelopeHysteresisDetector(),
        (
            Parameter("threshold_on_db", "parameter.threshold_on", -20, -96, 0, 1, "unit.dbfs"),
            Parameter("threshold_off_db", "parameter.threshold_off", -30.5, -96, 0, 1, "unit.dbfs"),
            *ONSET_PARAMETERS,
        ),
    )
)
