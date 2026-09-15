import numpy as np
import pytest
import soundfile as sf

from chopper.audio import ExportError, export_segments, load_wav


@pytest.mark.parametrize("subtype", ["PCM_U8", "PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE"])
@pytest.mark.parametrize("channels", [1, 2])
def test_export_roundtrip_exact(tmp_path, subtype, channels):
    rng = np.random.default_rng(3)
    values = rng.uniform(-1, 1, (1003, channels))
    values[:3] = [[-1] * channels, [0] * channels, [0.99999999] * channels]
    source = tmp_path / "recording.wav"
    sf.write(source, values, 44100, subtype=subtype)
    audio = load_wav(source)
    output = tmp_path / "segments"
    output.mkdir()
    paths = export_segments(audio, [(0, 1), (1, 337), (337, 1003)], output)
    arrays = []
    for path in paths:
        info = sf.info(path)
        assert (info.samplerate, info.channels, info.subtype) == (44100, channels, subtype)
        arrays.append(sf.read(path, dtype="float64", always_2d=True)[0])
    np.testing.assert_array_equal(np.concatenate(arrays), audio.samples)
    assert paths[0].name == "recording_001.wav"
    assert not audio.samples.flags.writeable


def test_pcm32_low_bits_survive(tmp_path):
    original = np.array([-(2**31), -123456789, -1, 0, 1, 123456789, 2**31 - 1], dtype=np.int32)
    path = tmp_path / "int32.wav"
    sf.write(path, original, 48000, subtype="PCM_32")
    audio = load_wav(path)
    outputs = export_segments(audio, [(0, 3), (3, 7)], tmp_path)
    recovered = np.concatenate([sf.read(p, dtype="int32")[0] for p in outputs])
    np.testing.assert_array_equal(recovered, original)


def test_collision_does_not_write_anything(tmp_path, audio):
    collision = tmp_path / "test_002.wav"
    collision.write_bytes(b"keep me")
    with pytest.raises(ExportError, match="existieren bereits"):
        export_segments(audio, [(0, 500), (500, 1000)], tmp_path)
    assert not (tmp_path / "test_001.wav").exists()
    assert collision.read_bytes() == b"keep me"


def test_partial_failure_cleans_incomplete_and_reports_completed(tmp_path, audio, monkeypatch):
    write = sf.write
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            args[0].write(b"partial")
            raise OSError("disk full")
        return write(*args, **kwargs)

    monkeypatch.setattr(sf, "write", fail_second)
    with pytest.raises(ExportError) as error:
        export_segments(audio, [(0, 500), (500, 1000)], tmp_path)
    assert error.value.completed == (tmp_path / "test_001.wav",)
    assert (tmp_path / "test_001.wav").exists()
    assert not (tmp_path / "test_002.wav").exists()


def test_empty_and_non_wav_rejected(tmp_path):
    empty = tmp_path / "empty.wav"
    sf.write(empty, np.zeros((0, 1)), 48000)
    with pytest.raises(ValueError, match="keine Samples"):
        load_wav(empty)
    flac = tmp_path / "other.flac"
    sf.write(flac, np.zeros(100), 48000)
    with pytest.raises(ValueError, match="WAV"):
        load_wav(flac)
