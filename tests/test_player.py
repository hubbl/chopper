from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import sounddevice as sd

from chopper.audio import AudioData
from chopper.player import AudioPlayer, PlayerState


class FakeStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.finished = kwargs["finished_callback"]
        self.channels = kwargs["channels"]
        self.time = 10.0
        self.closed = False

    def start(self):
        pass

    def abort(self):
        pass

    def close(self):
        self.closed = True

    def pull(self, frames):
        output = np.full((frames, self.channels), np.nan, dtype=np.float32)
        try:
            self.callback(output, frames, SimpleNamespace(outputBufferDacTime=self.time), False)
        except sd.CallbackStop:
            self.finished()
        return output


def make_player():
    player = AudioPlayer(FakeStream)
    player.set_audio(
        AudioData(Path("test.wav"), np.arange(1000, dtype=float)[:, None] / 1000, 1000, "FLOAT")
    )
    return player


def test_exact_range_end_zero_padded_tail_and_restart():
    player = make_player()
    player.play_range(100, 105)
    output = player._stream.pull(8)
    np.testing.assert_allclose(output[:5, 0], np.arange(100, 105) / 1000)
    np.testing.assert_array_equal(output[5:], 0)
    assert player.position == 105
    assert player.state is PlayerState.ENDED
    player.resume()
    assert player.position == 100
    player.close()


def test_pause_tracks_audible_samples_and_resumes_without_skipping():
    player = make_player()
    player.play_range(100, 500)
    stream = player._stream
    stream.pull(100)
    stream.time = 10.05
    player.pause()
    assert stream.closed
    assert 149 <= player.position <= 150
    position = player.position
    player.resume()
    output = player._stream.pull(10)
    assert output[0, 0] == pytest.approx(position / 1000)
    player.close()


def test_seek_clamps_to_active_range_and_stop_resets():
    player = make_player()
    player.play_range(100, 500)
    player.seek(-100)
    assert player.position == 100
    player.seek(9999)
    assert player.position == 500
    player.stop()
    assert player.position == 100
    assert player.state is PlayerState.STOPPED


def test_open_device_failure_can_retry(audio):
    def fail(**kwargs):
        raise sd.PortAudioError("No device")

    player = AudioPlayer(fail)
    player.set_audio(audio)
    with pytest.raises(sd.PortAudioError):
        player.play_all()
    assert player.state is PlayerState.STOPPED
    player._factory = FakeStream
    player.play_all()
    assert player.state is PlayerState.PLAYING
    player.close()
