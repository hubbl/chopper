"""Registered detectors; preserve the original public import surface."""

from .base import REGISTRY, Detector, DetectorSpec, Parameter, register
from .envelope_attack import EnvelopeAttackDetector
from .envelope_hysteresis import EnvelopeHysteresisDetector
from .envelope_threshold import EnvelopeThresholdDetector
from .peaks import SimplePeakCutDetector

DEFAULT_DETECTOR_ID = "envelope_hysteresis"

__all__ = [
    "DEFAULT_DETECTOR_ID",
    "REGISTRY",
    "Detector",
    "DetectorSpec",
    "Parameter",
    "register",
    "SimplePeakCutDetector",
    "EnvelopeThresholdDetector",
    "EnvelopeHysteresisDetector",
    "EnvelopeAttackDetector",
]
