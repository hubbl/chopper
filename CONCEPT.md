# Chopper: WAV-Splitter mit modularer Peak-Erkennung

## Zusammenfassung

Eine lokal startbare Python-Desktopanwendung mit PySide6, NumPy, soundfile und
sounddevice. Der vollständige MVP umfasst WAV öffnen, Waveform anzeigen,
Schnittpunkte automatisch vorschlagen, Marker korrigieren, Segmente anhören und
als WAV exportieren. Die vorhandene `.venv` wird verwendet und um die benötigten
Abhängigkeiten ergänzt.

Die Oberfläche ist deutsch. Projektspeicherung, Windows-EXE, Effekte und
Mehrspurbearbeitung bleiben außerhalb der ersten Version.

## Architektur und Audio

- `AudioDocument` hält Audiodaten, Samplerate, ursprüngliches WAV-Sampleformat und
  Marker als zentrale Datenquelle. Marker erhalten stabile IDs, ganzzahlige
  Samplepositionen und ihren automatisch/manuell-Status.
- Segmente werden aus sortierten Markern und den Dateigrenzen abgeleitet; Bereiche
  gelten als `[Start, Ende)`. Doppelte Marker und Marker an den Dateigrenzen werden
  ausgeschlossen.
- Controller, Darstellung, Erkennung, Wiedergabe und Export bleiben getrennte
  Komponenten. Modelländerungen aktualisieren die Oberfläche über Qt-Signale.
- WAV-Dateien mit PCM- oder Float-Samples werden unterstützt; Samplerate, Kanalzahl
  und Sampleformat bleiben beim Export erhalten. Keine Normalisierung oder
  Überblendung. WAV-Metadaten werden nicht übernommen.
- Laden, Analyse und Export laufen außerhalb des GUI-Threads. Ergebnisse einer
  inzwischen abgelösten Aufnahme werden verworfen; Fehler erscheinen verständlich.

## Austauschbare Erkennung

- Ein Qt-unabhängiges Detektor-Protokoll bietet
  `detect(samples, samplerate, parameters)` und liefert Samplepositionen. Eine
  Registrierung mit Algorithmus-ID, Anzeigename und Parameterbeschreibung
  ermöglicht weitere Algorithmen ohne Änderungen am Dokument oder Player.
- Der erste Algorithmus erkennt lokale Maxima einer Pegelhüllkurve: maximaler
  Absolutwert über alle Kanäle, geglättet über zunächst 1 ms. Dadurch löschen sich
  gegenphasige Stereokanäle nicht gegenseitig aus.
- Einstellbare Startwerte: Peak-Schwelle −24 dBFS, Mindestabstand zwischen Peaks
  100 ms, Mindestvorlauf 10 ms, Zielpegel 25 % der Peak-Amplitude und maximale
  Rückwärtssuche 500 ms. Bei konkurrierenden Peaks gewinnt der stärkere.
- Für jeden Peak beginnt die Rückwärtssuche beim Mindestvorlauf. Der erste
  Hüllkurvenpunkt mit höchstens dem eingestellten Anteil der Peak-Amplitude wird
  zum Schnittpunkt. Ohne Treffer gilt der Mindestvorlauf; die Suche endet
  spätestens an der Dateigrenze beziehungsweise am vorherigen akzeptierten Peak.
- 25 % bezeichnet lineare Amplitude. Alle Zeiten werden in Samplepositionen
  umgerechnet. Ungültige oder doppelte Schnittpunkte entfallen; stille Dateien
  ergeben keine Marker.
- Nach dem Öffnen startet die Analyse mit den aktuellen Einstellungen. Bei
  erneuter Analyse bleiben manuelle und manuell verschobene Marker erhalten;
  unveränderte automatische Marker werden ersetzt. Die gesamte Analyse ist ein
  Undo-Schritt.

## Oberfläche und Bedienung

- Hauptfenster mit Dateiaktionen, Algorithmusauswahl und Parametern, Waveform mit
  Zeitachse, Wiedergabesteuerung und Export.
- `QGraphicsView/QGraphicsScene` verwendet Samplepositionen als horizontale
  Koordinaten. Die Darstellung berechnet Minima und Maxima je sichtbarer
  Pixelspalte; bei starkem Zoom zeichnet sie einzelne Samples. Audiokanäle
  erscheinen getrennt untereinander.
- Klick wählt ein Segment, Doppelklick setzt einen Marker, Doppelklick auf einen
  Marker entfernt ihn. Marker sind mit einer zoomunabhängigen Treffertoleranz von
  ±6 Pixeln verschiebbar.
- Manuelles Verschieben macht einen automatischen Marker manuell. Marker bleiben
  zwischen ihren Nachbarn; ein vollständiges Ziehen zählt als ein Undo-Schritt.
- Mausrad scrollt horizontal, Strg+Mausrad zoomt um die Mausposition. Eine
  Schaltfläche zeigt die gesamte Aufnahme.
- Leertaste spielt oder pausiert das ausgewählte Segment; nach dessen Ende startet
  sie es erneut. Ohne Auswahl wird ab dem Playhead bis zum Dateiende gespielt.
  Pfeiltasten springen um 100 ms innerhalb des aktiven Bereichs.
- Stop setzt auf den Bereichsanfang zurück. Änderungen an Markern stoppen die
  Wiedergabe; die Segmentauswahl wird anhand ihrer bisherigen Ankerposition neu
  bestimmt.
- Der Player kennt nur Audio und Samplebereiche und bietet `play_all`,
  `play_range`, `pause`, `stop` und `seek`. Ein Timer aktualisiert den Playhead
  etwa 30-mal pro Sekunde.
- `QUndoStack` unterstützt Hinzufügen, Entfernen, Verschieben und automatische
  Erkennung. Entf löscht den gewählten Marker; Strg+Z und Strg+Umschalt+Z steuern
  Undo/Redo.

## Export und Prüfung

- Export aller Segmente in einen gewählten Ordner als `original_001.wav`,
  `original_002.wav` usw. Vorhandene Dateien werden nicht überschrieben; bei
  Namenskollisionen wird ein anderer Zielordner verlangt.
- Export arbeitet mit einem festen Snapshot der Segmentgrenzen. Unvollständige
  Dateien werden bei Fehlern entfernt; bereits vollständig exportierte Dateien
  werden im Ergebnis genannt.
- Automatisierte Tests prüfen Segmentgrenzen, Markerregeln, Undo/Redo und die
  Beibehaltung manueller Korrekturen.
- Synthetische Audios prüfen Peak-Abstände, Viertelpegel-Suche, Mindestvorlauf,
  fehlende Treffer, Stille und gegenphasiges Stereo.
- Exporttests prüfen Kanalzahl, Sampleformat und Samplewerte: Hintereinander
  zusammengesetzte Segmente müssen die ursprüngliche Samplefolge ergeben.
- Wiedergabeprüfungen mit simuliertem Audiostream prüfen Bereichsende, Pause,
  Fortsetzen und Seek. Ein Windows-Starttest prüft die Oberfläche mit einer
  fünfminütigen Datei; die tatsächliche Audioausgabe benötigt einen Hörtest.
- Einrichtung über `pyproject.toml` mit dokumentiertem Startbefehl und geprüften
  Abhängigkeiten für die vorhandene Python-3.14-Umgebung.

