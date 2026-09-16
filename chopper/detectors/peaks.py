"""Original peak-based cut detector."""

from bisect import bisect_left, insort
from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray

from ..i18n import tr
from .base import REGISTRY, DetectorSpec, Parameter, register
from .common import envelope, validated_parameters


class SimplePeakCutDetector:
    """Erkenne einfache Amplitudenpeaks und liefere Schnittpositionen davor."""

    def guess_threshold(
        self, samples: NDArray[np.float64], samplerate: int, parameters: Mapping[str, float]
    ) -> float:
        """Schätze die Schwelle für etwa 10 Peaks oder 6 Peaks je Minute.

        Gezählt werden getrennte Peaks, vor der Umwandlung in Schnittmarker.
        Die Auflösung von 0,1 dB entspricht dem Eingabefeld.
        """
        settings = self._validated_parameters(parameters)
        if samplerate <= 0:
            raise ValueError(tr("error.samplerate"))
        if len(samples) < 3:
            return REGISTRY["peaks"].defaults()["threshold_db"]

        env = self._envelope(samples, samplerate, settings["smoothing_ms"])

        parameter = next(p for p in REGISTRY["peaks"].parameters if p.key == "threshold_db")
        candidates = self._find_peak_candidates(env, parameter.minimum)
        distance = max(1, int(round(settings["distance_ms"] * samplerate / 1000)))
        peaks = self._select_separated_peaks(env, candidates, distance)
        if not peaks:
            return parameter.default

        target = max(10, int(len(samples) / samplerate / 60 * 6 + 0.5))
        thresholds = (
            np.arange(round(parameter.minimum * 10), round(parameter.maximum * 10) + 1) / 10
        )
        # Schwächere Kandidaten verdrängen nie stärkere Peaks. Deshalb reicht
        # eine Abstandsauswahl für alle anschließend geprüften Schwellen.
        heights = np.sort(env[peaks])
        counts = len(peaks) - np.searchsorted(heights, 10 ** (thresholds / 20), side="left")
        best = min(
            range(len(thresholds)),
            key=lambda i: (abs(int(counts[i]) - target), counts[i] == 0, -thresholds[i]),
        )
        return float(thresholds[best])

    def detect(
        self, samples: NDArray[np.float64], samplerate: int, parameters: Mapping[str, float]
    ) -> list[int]:
        settings = self._validated_parameters(parameters)
        if samplerate <= 0:
            raise ValueError(tr("error.samplerate"))
        if len(samples) < 3:
            return []
        env = self._envelope(samples, samplerate, settings["smoothing_ms"])
        candidates = self._find_peak_candidates(env, settings["threshold_db"])

        distance = max(1, int(round(settings["distance_ms"] * samplerate / 1000)))
        peaks = self._select_separated_peaks(env, candidates, distance)

        # Den Mindestvorlauf aufrunden, damit er nie unterschritten wird.
        # Auch bei 0 ms liegt der Schnitt mindestens ein Sample vor dem Peak.
        lead = max(1, int(np.ceil(settings["lead_ms"] * samplerate / 1000)))
        lookback = max(lead, int(round(settings["lookback_ms"] * samplerate / 1000)))
        return self._cuts_before_peaks(env, peaks, lead, lookback, settings["level_percent"])

    def _envelope(
        self, samples: NDArray[np.float64], samplerate: int, smoothing_ms: float
    ) -> NDArray[np.float64]:
        """Bilde eine zentriert geglättete Amplitudenhüllkurve."""
        return envelope(samples, samplerate, smoothing_ms)

    def _validated_parameters(self, parameters: Mapping[str, float]) -> dict[str, float]:
        """Ergänze Standardwerte und prüfe die Einstellungen des Peak-Schnittdetektors."""
        settings = validated_parameters("peaks", parameters)
        if settings["lookback_ms"] < settings["lead_ms"]:
            raise ValueError(tr("error.lookback"))
        return settings

    def _find_peak_candidates(
        self, env: NDArray[np.float64], threshold_db: float
    ) -> NDArray[np.intp]:
        """Finde lokale Maxima ab der absoluten Pegelschwelle in dBFS."""
        # Gleich hohe Nachbarsamples bilden ein Plateau. Ein Peak liegt nur vor,
        # wenn beide Nachbarplateaus niedriger sind; Dateiränder zählen nicht.
        changes = np.flatnonzero(np.diff(env) != 0) + 1
        starts = np.r_[0, changes]
        ends = np.r_[changes, len(env)]
        heights = env[starts]
        previous = np.r_[heights[0], heights[:-1]]
        following = np.r_[heights[1:], heights[-1]]
        threshold = 10 ** (threshold_db / 20)
        is_peak = (heights > previous) & (heights > following) & (heights >= threshold)
        # Ein flacher Gipfel ergibt genau einen Kandidaten in seiner Mitte.
        return ((starts[is_peak] + ends[is_peak] - 1) // 2).astype(int)

    def _select_separated_peaks(
        self, env: NDArray[np.float64], candidates: NDArray[np.intp], minimum_distance: int
    ) -> list[int]:
        """Wähle Peaks nach Stärke aus und liefere sie zeitlich sortiert zurück."""
        peaks: list[int] = []
        # Stärkere Peaks belegen ihren Abstand zuerst. Bei Gleichstand gewinnt
        # der frühere Kandidat, da die Sortierung stabil ist.
        for index in np.argsort(-env[candidates], kind="stable"):
            peak = int(candidates[index])
            insertion = bisect_left(peaks, peak)
            if insertion and peak - peaks[insertion - 1] < minimum_distance:
                continue
            if insertion < len(peaks) and peaks[insertion] - peak < minimum_distance:
                continue
            insort(peaks, peak)
        return peaks

    def _find_cut_before_peak(
        self,
        env: NDArray[np.float64],
        peak: int,
        previous_peak: int,
        lead: int,
        lookback: int,
        level_percent: float,
    ) -> int | None:
        """Suche vor einem Peak die nächste ausreichend leise Schnittstelle.

        Alle Positionen und Abstände sind in Samples angegeben.
        """
        latest = peak - lead
        earliest = max(0, previous_peak, peak - lookback)
        if latest < earliest:
            return None

        # Der Zielpegel ist relativ zu diesem Peak, nicht zur Vollaussteuerung.
        target_level = env[peak] * level_percent / 100
        quiet = np.flatnonzero(env[earliest : latest + 1] <= target_level)
        # Die letzte passende Stelle entspricht dem ersten Treffer rückwärts.
        # Ohne Treffer bleibt der Schnitt beim Mindestvorlauf.
        return int(earliest + quiet[-1]) if len(quiet) else latest

    def _cuts_before_peaks(
        self,
        env: NDArray[np.float64],
        peaks: list[int],
        lead: int,
        lookback: int,
        level_percent: float,
    ) -> list[int]:
        """Setze innere Schnittmarker, ohne über den vorherigen Peak zurückzusuchen."""
        cuts = []
        previous_peak = 0
        for peak in peaks:
            cut = self._find_cut_before_peak(
                env, peak, previous_peak, lead, lookback, level_percent
            )
            if cut is not None and 0 < cut < len(env):
                cuts.append(cut)
            # Auch ein Peak ohne gültigen Schnitt begrenzt die nächste Suche.
            previous_peak = peak
        return sorted(set(cuts))


register(
    DetectorSpec(
        "peaks",
        "detector.peaks.name",
        SimplePeakCutDetector(),
        (
            Parameter("threshold_db", "parameter.threshold", -24, -96, 0, 1, "unit.dbfs"),
            Parameter("distance_ms", "parameter.distance", 100, 1, 10000, 10, "unit.ms"),
            Parameter("lead_ms", "parameter.lead", 10, 0, 1000, 1, "unit.ms"),
            Parameter("level_percent", "parameter.level", 1, 0, 100, 1, "unit.percent"),
            Parameter("lookback_ms", "parameter.lookback", 500, 1, 10000, 10, "unit.ms"),
            Parameter("smoothing_ms", "parameter.smoothing", 1, 0, 100, 0.1, "unit.ms"),
        ),
    )
)
