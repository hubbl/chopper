import numpy as np
import pytest

from chopper.detectors import REGISTRY

NEW_IDS = ("envelope_threshold", "envelope_hysteresis", "envelope_attack")


def detect(detector_id, values, samplerate=1000, **parameters):
    return REGISTRY[detector_id].detector.detect(
        np.asarray(values, dtype=np.float64),
        samplerate,
        {"smoothing_ms": 0, "lead_ms": 0, **parameters},
    )


@pytest.mark.parametrize("detector_id", NEW_IDS)
def test_separated_sounds_and_antiphase_stereo(detector_id):
    values = np.zeros(800)
    values[200:300] = 0.5
    values[500:600] = 0.8
    for samples in (values, np.column_stack((values, -values))):
        original = samples.copy()
        assert detect(detector_id, samples) == [200, 500]
        assert detect(detector_id, samples, lead_ms=40) == [160, 460]
        np.testing.assert_array_equal(samples, original)


@pytest.mark.parametrize("detector_id", NEW_IDS)
@pytest.mark.parametrize("frames", [0, 1, 2, 1000])
def test_silence_and_initial_active_signal(detector_id, frames):
    assert detect(detector_id, np.zeros((frames, 2))) == []
    assert detect(detector_id, np.full((frames, 2), 0.8)) == []


def test_hysteresis_suppresses_wobbles_until_reset():
    values = np.zeros(1000)
    values[100:200] = 0.2
    values[200:300] = 0.05
    values[300:400] = 0.2
    values[400:500] = 0.01
    values[500:600] = 0.2
    assert detect("envelope_threshold", values, threshold_db=-20) == [100, 300, 500]
    assert detect("envelope_hysteresis", values) == [100, 500]
    values[:100] = 0.2
    assert detect("envelope_hysteresis", values) == [500]


def test_hysteresis_reset_is_strict_and_start_is_inclusive():
    low = 10 ** (-30.5 / 20)
    values = np.zeros(1000)
    values[100:200] = 0.1
    values[200:300] = low
    values[300:400] = 0.1
    values[400:500] = low / 2
    values[500:600] = 0.1
    assert detect("envelope_hysteresis", values) == [100, 500]
    assert detect("envelope_threshold", values, threshold_db=-20) == [100, 300, 500]


def test_attack_detects_second_sound_without_silence():
    values = np.full(1000, 0.2)
    values[200:500] = 0.4
    values[500:] = 0.8
    assert detect("envelope_attack", values) == [200, 500]
    assert detect("envelope_threshold", values) == []
    assert detect("envelope_hysteresis", values) == []


@pytest.mark.parametrize("samplerate", [1000, 44100, 48000, 96000])
def test_attack_timing_across_sample_rates(samplerate):
    times = np.arange(samplerate) / samplerate
    values = 0.2 + np.clip((times - 0.2) * 10, 0, 0.5)
    cuts = detect("envelope_attack", values, samplerate, rise_db=-30, smoothing_ms=5)
    assert len(cuts) == 1
    assert abs(cuts[0] / samplerate - 0.2032) < 0.002


@pytest.mark.parametrize("detector_id", NEW_IDS)
def test_distance_keeps_first_and_lead_rounds_up(detector_id):
    values = np.zeros(500)
    values[50:60] = 0.2
    values[100:110] = 0.8
    values[150:160] = 0.5
    assert detect(detector_id, values) == [50, 150]
    assert detect(detector_id, values, lead_ms=1.1) == [48, 148]
    assert detect(detector_id, values, lead_ms=50) == [100]
    assert detect(detector_id, values, lead_ms=500) == []


@pytest.mark.parametrize("detector_id", NEW_IDS)
@pytest.mark.parametrize("samplerate", [0, -1])
def test_invalid_sample_rate_even_with_empty_input(detector_id, samplerate):
    with pytest.raises(ValueError, match="sample rate"):
        detect(detector_id, [], samplerate)


@pytest.mark.parametrize("detector_id", NEW_IDS)
def test_all_parameter_bounds_and_nonfinite_values(detector_id):
    spec = REGISTRY[detector_id]
    for parameter in spec.parameters:
        for value in (float("nan"), float("inf"), parameter.minimum - 1, parameter.maximum + 1):
            with pytest.raises(ValueError):
                spec.detector.detect(np.zeros(0), 1000, {parameter.key: value})


@pytest.mark.parametrize("off", [-20, -10])
def test_hysteresis_rejects_invalid_threshold_order(off):
    with pytest.raises(ValueError, match="reset threshold"):
        detect("envelope_hysteresis", [], threshold_off_db=off)


@pytest.mark.parametrize("detector_id", NEW_IDS)
def test_smoothing_with_defaults_finds_two_bursts(detector_id):
    values = np.zeros((48000, 2))
    values[12000:16000, 0] = 0.8
    values[30000:34000, 1] = -0.8
    cuts = REGISTRY[detector_id].detector.detect(values, 48000, {})
    assert len(cuts) == 2
    np.testing.assert_allclose(np.asarray(cuts) / 48000, [0.21, 0.585], atol=0.003)
