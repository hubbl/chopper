"""Audio-range playback. The callback never accesses Qt or document markers."""

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

import numpy as np
import sounddevice as sd
from numpy.typing import NDArray

from .audio import AudioData
from .i18n import tr


class OutputStream(Protocol):
    @property
    def time(self) -> float: ...
    def start(self) -> None: ...
    def abort(self) -> None: ...
    def close(self) -> None: ...


class CallbackTime(Protocol):
    @property
    def outputBufferDacTime(self) -> float: ...


class PlayerState(StrEnum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"


class AudioPlayer:
    def __init__(self, stream_factory: Callable[..., OutputStream] | None = None) -> None:
        self._factory = stream_factory or sd.OutputStream
        self.audio: AudioData | None = None
        self._stream: OutputStream | None = None
        self.start = self.end = self._cursor = self._position = 0
        self._dac_origin: float | None = None
        self._finished = False
        self.state: PlayerState = PlayerState.STOPPED
        self.warning = ""

    def set_audio(self, audio: AudioData) -> None:
        self.close()
        self.audio = audio
        self.start, self.end = 0, audio.frames
        self._position = self._cursor = 0

    @property
    def position(self) -> int:
        if self._finished and self.state == PlayerState.PLAYING:
            self._position = self.end
            self.state = PlayerState.ENDED
        elif (
            self.state == PlayerState.PLAYING
            and self._stream is not None
            and self._dac_origin is not None
        ):
            assert self.audio is not None
            elapsed = self._stream.time - self._dac_origin
            self._position = max(
                self._position,
                min(
                    self.end,
                    self._cursor,
                    self._origin_sample + int(max(0, elapsed) * self.audio.samplerate),
                ),
            )
        return self._position

    def _dispose(self) -> None:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                stream.abort()
            finally:
                stream.close()

    def _begin(self) -> None:
        assert self.audio is not None
        self._dispose()
        self._cursor = self._position
        self._origin_sample = self._position
        self._dac_origin = None
        self._finished = False
        self.warning = ""
        self.state = PlayerState.PLAYING
        try:
            self._stream = self._factory(
                samplerate=self.audio.samplerate,
                channels=self.audio.channels,
                dtype="float32",
                callback=self._callback,
                finished_callback=self._on_finished,
            )
            self._stream.start()
        except Exception:
            self.state = PlayerState.STOPPED
            self._dispose()
            raise

    def _callback(
        self, outdata: NDArray[np.float32], frames: int, time: CallbackTime, status: object
    ) -> None:
        assert self.audio is not None
        outdata.fill(0)
        if status:
            self.warning = tr("error.audio_dropout")
        if self._dac_origin is None:
            self._dac_origin = time.outputBufferDacTime
        count = min(frames, self.end - self._cursor)
        if count > 0:
            outdata[:count] = self.audio.samples[self._cursor : self._cursor + count]
            self._cursor += count
        if self._cursor >= self.end:
            raise sd.CallbackStop

    def _on_finished(self) -> None:
        self._finished = True

    def play_range(self, start: int, end: int) -> None:
        if self.audio is None or not 0 <= start < end <= self.audio.frames:
            raise ValueError(tr("error.playback_range"))
        self._dispose()
        self.start, self.end = int(start), int(end)
        self._position = self.start
        self._begin()

    def play_all(self) -> None:
        if self.audio is not None:
            self.play_range(0, self.audio.frames)

    def resume(self) -> None:
        if self.audio is None:
            return
        if self.position >= self.end:
            self._position = self.start
        self._begin()

    def pause(self) -> None:
        if self.state == PlayerState.PLAYING:
            position = self.position
            self._dispose()
            self._position = position
            self.state = PlayerState.PAUSED

    def stop(self) -> None:
        self._dispose()
        self._finished = False
        self._position = self._cursor = self.start
        self.state = PlayerState.STOPPED

    def seek(self, sample: int) -> None:
        if self.audio is None:
            return
        playing = self.state == PlayerState.PLAYING
        self._dispose()
        self._finished = False
        self._position = max(self.start, min(int(sample), self.end))
        self.state = PlayerState.PAUSED
        if playing and self._position < self.end:
            self._begin()

    def close(self) -> None:
        self.stop()
