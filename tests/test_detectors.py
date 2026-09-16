import numpy as np
import pytest

from chopper.detectors import REGISTRY, DetectorSpec, Parameter, SimplePeakCutDetector, register


def detect(values, **parameters):
    return SimplePeakCutDetector().detect(
        np.asarray(values), 1000, {"smoothing_ms": 0, **parameters}
    )


def test_silence_and_short_files():
    assert detect(np.zeros((1000, 2))) == []
    assert detect(np.zeros((2, 1))) == []


def test_minimum_lead_overrides_nearer_quarter_level():
    values = np.zeros(300)
    values[100] = 1
    assert detect(values) == [90]
    assert detect(values, lead_ms=20) == [80]


def test_quarter_level_searches_back_on_attack():
    values = np.zeros(300)
    values[40:101] = np.linspace(0, 1, 61)
    assert detect(values, level_percent=25) == [55]
    assert detect(values, level_percent=50) == [70]


def test_no_quiet_point_uses_lead_and_respects_lookback():
    values = np.full(300, 0.5)
    values[100] = 1
    assert detect(values, lookback_ms=20) == [90]


def test_stronger_peak_wins_within_distance():
    values = np.zeros(500)
    values[100], values[150], values[350] = 0.5, 1, 0.8
    assert detect(values) == [140, 340]


@pytest.mark.parametrize("distance_ms, expected", [(100, [90, 190]), (101, [90])])
def test_equal_peaks_keep_earlier_peak_and_allow_exact_distance(distance_ms, expected):
    values = np.zeros(300)
    values[100] = values[200] = 1
    assert detect(values, distance_ms=distance_ms) == expected


def test_peak_exactly_at_threshold_is_included():
    values = np.zeros(300)
    values[100] = 10 ** (-24 / 20)
    assert detect(values, threshold_db=-24) == [90]
    assert detect(values, threshold_db=-23) == []


@pytest.mark.parametrize("lead_ms, expected", [(0, 99), (1.1, 98)])
def test_lead_is_at_least_one_sample_and_rounded_up(lead_ms, expected):
    values = np.zeros(300)
    values[100] = 1
    assert detect(values, lead_ms=lead_ms) == [expected]


def test_antiphase_stereo_does_not_cancel():
    values = np.zeros(300)
    values[100] = 1
    assert detect(np.column_stack((values, -values))) == [90]


def test_threshold_plateau_and_near_start():
    values = np.zeros(300)
    values[5] = 0.8
    values[100:103] = 1
    values[250] = 0.001
    assert detect(values, distance_ms=20) == [91]


def test_previous_peak_limits_lookback():
    values = np.full(300, 0.5)
    values[100], values[140] = 1, 0.9
    assert detect(values, distance_ms=30) == [90, 130]
    assert detect(values, distance_ms=30, lead_ms=50) == [50]


def test_realistic_smoothing_keeps_stereo_peaks():
    values = np.zeros((48000, 2))
    values[20000:20500, 0] = np.hanning(500)
    values[:, 1] = -values[:, 0]
    result = REGISTRY["peaks"].detector.detect(values, 48000, {})
    assert len(result) == 1
    assert 19000 < result[0] <= 20250 - 480


@pytest.mark.parametrize(
    "parameters",
    [{"lead_ms": 30, "lookback_ms": 20}, {"level_percent": 101}, {"threshold_db": float("nan")}],
)
def test_invalid_settings(parameters):
    with pytest.raises(ValueError):
        detect(np.zeros(300), **parameters)


@pytest.mark.parametrize("samplerate", [0, -1000])
def test_invalid_samplerate_even_for_empty_audio(samplerate):
    with pytest.raises(ValueError, match="sample rate"):
        SimplePeakCutDetector().detect(np.zeros(0), samplerate, {})


def test_algorithm_registration():
    class Dummy:
        def detect(self, samples, samplerate, parameters):
            return [int(parameters["position"])]

    spec = DetectorSpec(
        "test-dummy", "Test", Dummy(), (Parameter("position", "Position", 30, 1, 100, 1),)
    )
    try:
        register(spec)
        assert REGISTRY[spec.id].detector.detect(None, 1000, spec.defaults()) == [30]
        with pytest.raises(ValueError):
            register(spec)
    finally:
        REGISTRY.pop(spec.id, None)


@pytest.mark.parametrize("seconds, expected", [(30, 10), (60, 10), (200, 20)])
def test_guess_threshold_targets_peak_count_for_duration(seconds, expected):
    values = np.zeros(seconds * 1000)
    values[np.arange(100, 29101, 1000)] = np.linspace(0.01, 0.9, 30)
    detector = SimplePeakCutDetector()
    threshold = detector.guess_threshold(values, 1000, {"smoothing_ms": 0})
    assert len(detect(values, threshold_db=threshold)) == expected


def test_guess_counts_separated_peaks_and_handles_quiet_stereo():
    values = np.zeros(20000)
    for i in range(15):
        values[100 + i * 1000] = 0.001 + i * 0.001
        values[120 + i * 1000] = values[100 + i * 1000] * 0.95
    stereo = np.column_stack((values, -values))
    threshold = SimplePeakCutDetector().guess_threshold(stereo, 1000, {"smoothing_ms": 0})
    assert threshold < -24
    assert len(detect(stereo, threshold_db=threshold)) == 10


@pytest.mark.parametrize("count", [3, 20])
def test_guess_keeps_available_equal_peaks(count):
    values = np.zeros(30000)
    values[np.arange(100, count * 1000, 1000)] = 0.02
    threshold = SimplePeakCutDetector().guess_threshold(values, 1000, {"smoothing_ms": 0})
    assert len(detect(values, threshold_db=threshold)) == count


@pytest.mark.parametrize("frames", [0, 2, 1000])
def test_guess_without_peaks_has_safe_default(frames):
    threshold = SimplePeakCutDetector().guess_threshold(np.zeros(frames), 1000, {})
    assert threshold == -24


def test_guess_validates_samplerate():
    with pytest.raises(ValueError, match="sample rate"):
        SimplePeakCutDetector().guess_threshold(np.zeros(0), 0, {})
