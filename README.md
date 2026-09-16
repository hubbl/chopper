# Chopper

Kleiner WAV-Splitter für Musik und Geräusche: Klanganfänge erkennen, Schnittmarker
korrigieren, Segmente anhören und samplegenau exportieren.

![Preview of how the chopper-application looks like](./images/initial.jpg)


## Start unter Windows

Die vorhandene Python-Umgebung `.venv` wird verwendet. Doppelklick auf `start.bat`
öffnet die Anwendung. Alternativ in PowerShell im Projektordner:

```powershell
.venv\Scripts\python.exe -m chopper
# Optional direkt eine Datei öffnen:
.venv\Scripts\python.exe -m chopper "C:\Audio\aufnahme.wav"
```

Abhängigkeiten bei einer neuen Einrichtung:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Python 3.14 oder neuer ist erforderlich. Getestete direkte Abhängigkeiten stehen
in `requirements.txt`.

## Workflow

1. Eine WAV-Datei ins Fenster ziehen oder **WAV öffnen** wählen: Die automatische
   Erkennung mit dem ausgewählten Verfahren startet nach dem Laden. Drag-and-drop unterstützt jeweils eine
   Datei mit der Endung `.wav` oder `.wave`.
2. Rechts eines der vier Erkennungsverfahren wählen, bei Bedarf seine Parameter
   anpassen und **Neu analysieren** wählen. Vorausgewählt ist **Envelope + Hysterese**.
3. Ein Segment anklicken und mit **Leertaste** abspielen/pausieren.
4. Per Doppelklick Marker setzen oder entfernen; Marker zum Korrigieren ziehen.
5. **Segmente exportieren** schreibt alle Segmente in einen gewählten Ordner.

Orange Marker sind automatisch, violette manuell. Verschobene automatische Marker
werden manuell. Eine neue Analyse ersetzt nur automatische Marker. Manuell
gelöschte automatische Vorschläge können bei einer neuen Analyse wiederkehren.
Marker werden nur während der Sitzung gehalten; es gibt keine Projektdatei.

| Bedienung | Wirkung |
| --- | --- |
| Klick in Waveform | Segment auswählen |
| Doppelklick | Marker hinzufügen / getroffenen Marker entfernen |
| Marker ziehen | Sampleposition verändern, ohne Nachbarmarker zu überholen |
| Mausrad | Horizontal scrollen |
| Strg + Mausrad | Um Mausposition zoomen |
| Alles anzeigen | Gesamte Waveform einpassen |
| Leertaste | Ausgewählten Bereich abspielen / pausieren |
| Stop | Auf Bereichsanfang zurücksetzen |
| Gesamte Aufnahme | Segmentauswahl aufheben, zum Dateianfang |
| Links / Rechts in der Waveform | 100 ms zurück / vor |
| Entf | Gewählten Marker entfernen |
| Strg+Z / Strg+Umschalt+Z | Rückgängig / Wiederholen |
| Strg+O / Strg+E | Öffnen / Exportieren |

## Die vier Erkennungsverfahren

Die Verfahren schlagen Stellen vor, an denen ein neuer Klang beginnt. Stell dir
zum Beispiel eine Aufnahme mit mehreren einzeln angeschlagenen Trommelschlägen
vor: Jeder Schlag soll später ein eigenes Klangstück werden. Je nach Aufnahme
ist ein anderes Verfahren hilfreich. Alle vier verändern nur die Schnittmarker,
nicht die Audiodaten. Du kannst die Vorschläge anschließend verschieben.

| Verfahren | Wann ist es hilfreich? | Grundidee |
| --- | --- | --- |
| **Envelope + Hysterese** (Startauswahl) | Einzelne Sounds mit kurzen Pausen | Ein höherer Pegel startet einen Sound; erst ein niedrigerer Pegel macht die Erkennung wieder bereit. |
| **Envelope + Threshold** | Deutlich getrennte Sounds mit gleichmäßigem Pegel | Ein Sound startet, sobald die Lautstärkekurve eine Schwelle von unten erreicht. |
| **Envelope / Attack Detection** | Ein neuer Sound beginnt, während der vorige noch ausklingt | Ein ausreichend schneller Lautstärkeanstieg markiert den nächsten Einsatz. |
| **Simple Peak Cut** | Suche nach Lautstärkespitzen und einer passenden Schnittstelle davor | Erst den Gipfel suchen, dann davor eine leisere Stelle finden. |

Die drei Envelope-Verfahren betrachten eine geglättete Lautstärkekurve. Dazu
werden negative Ausschläge nach oben gespiegelt und benachbarte Werte gemittelt.
Bei mehreren Kanälen zählt an jeder Stelle der stärkste Ausschlag. Auch Stereo
mit entgegengesetzten Ausschlägen funktioniert so zuverlässig. Die Aufnahme wird
nicht automatisch lauter oder leiser gemacht: Schwellen sind absolute Werte.

### 1. Simple Peak Cut: vom Gipfel zurück zum Schnitt

Beispiel: Ein Schlag wird zunächst lauter, erreicht seinen höchsten Punkt und
klingt danach ab. Dieses Verfahren findet den höchsten Punkt und sucht davor
nach einer leiseren Schnittstelle. Der höchste Punkt selbst ist also **nicht**
der Schnitt. Das ist das bisherige Verfahren mit unverändertem Verhalten.

| Einstellung | Standard | Bedeutung |
| --- | --- | --- |
| Peak-Schwelle | −24 dBFS, beim Öffnen geschätzt | Wie hoch eine Spitze mindestens sein muss. |
| Peak-Mindestabstand | 100 ms | Wie dicht zwei ausgewählte Spitzen beieinanderliegen dürfen; die stärkere gewinnt. |
| Mindestvorlauf | 10 ms | Mindestabstand des Schnitts vor der Spitze. |
| Zielpegel relativ zum Peak | 1 % | Wie leise die gesuchte Stelle im Verhältnis zur jeweiligen Spitze sein soll. |
| Max. Rückwärtssuche | 500 ms | Wie weit vor der Spitze gesucht werden darf. |
| Hüllkurven-Glättung | 1 ms | Wie stark kleine Schwankungen geglättet werden. |

Die Suche beginnt beim Mindestvorlauf und läuft rückwärts bis zur nächsten
passenden leisen Stelle. Ohne Treffer gilt der Mindestvorlauf. Die Suche reicht
nicht hinter die vorherige ausgewählte Spitze zurück; die Rückwärtssuche muss
mindestens so lang wie der Vorlauf sein. Ein flacher Gipfel ergibt genau eine
Spitze in seiner Mitte. Dateiränder gelten nicht als Spitzen. Selbst bei 0 ms
Vorlauf liegt der Schnitt mindestens einen Messwert vor der Spitze.

Nur bei diesem Verfahren wird beim Öffnen einer Datei die Peak-Schwelle geschätzt:
Ziel sind etwa 10 Spitzen oder 6 pro Minute, je nachdem, welche Zahl größer ist.
Glättung und Mindestabstand werden berücksichtigt. Die Schätzung prüft Schritte
von 0,1 dB und nimmt die nächstmögliche Anzahl; bei Stille bleibt es bei −24 dBFS.
Der geschätzte Wert erscheint im Feld. **Neu analysieren** verwendet deine Werte.
Die Anzahl der Schnittmarker kann kleiner als die Zahl der Spitzen sein.

Grenze: Ein Klang kann mehrere Spitzen enthalten; bei einem langsam anschwellenden
Klang kann sein Beginn weit vor dem Gipfel liegen. Dann sind Vorlauf und
Rückwärtssuche besonders wichtig.

### 2. Envelope + Threshold: eine Lautstärkeschwelle

Beispiel: Zwischen zwei gesprochenen Wörtern ist eine deutliche Pause. Steigt die
Lautstärkekurve von unterhalb auf oder über die Schwelle, wird ein Klanganfang
erkannt. Solange die Kurve darüber bleibt, entsteht kein weiterer Vorschlag.

**Hüllkurven-Schwelle: −26 dBFS** ist der Standard, ungefähr entsprechend 0,05
linearer Amplitude. Eine stärker negative Schwelle erkennt auch leisere Sounds,
kann aber mehr Nebengeräusche erfassen. Eine Schwelle näher an 0 erkennt nur
lautere Stellen. Glättung, Mindestabstand und Vorlauf sind unten erklärt.

Grenze: Schwankt ein einzelner Sound mehrfach um die Schwelle, können mehrere
Anfänge entstehen. Hysterese hilft genau bei diesem Problem.

### 3. Envelope + Hysterese: getrennte Start- und Rücksetzschwelle

Beispiel: Ein angeschlagener Klang schwankt während des Ausklingens mehrfach in
der Lautstärke. Die **Startschwelle** erkennt seinen Beginn. Danach wartet das
Verfahren, bis die Kurve unter die niedrigere **Rücksetzschwelle** fällt. Erst dann
kann ein weiterer Klang beginnen. Dadurch wird ein schwankender Sound seltener
versehentlich in mehrere Stücke zerlegt.

- **Startschwelle: −20 dBFS**, entsprechend 0,10 linearer Amplitude.
- **Rücksetzschwelle: −30,5 dBFS**, ungefähr entsprechend 0,03.
- Die Rücksetzschwelle muss niedriger, also stärker negativ als die Startschwelle sein.

Die Rücksetzschwelle erzeugt **keinen Endmarker** und entfernt keine Pause. Sie
macht die Erkennung lediglich wieder bereit. Die Segmente reichen weiterhin von
einem Schnittmarker bis zum nächsten.

Grenze: Bleibt das Hintergrundgeräusch oberhalb der Rücksetzschwelle, wird kein
weiterer Start freigegeben. Dann die Schwellen passend einstellen oder Attack
verwenden. Für getrennte Sounds mit kurzen Pausen ist Hysterese ein guter Einstieg.

### 4. Envelope / Attack Detection: einen neuen Anstieg erkennen

Beispiel: Ein Ton klingt noch aus, während der nächste angeschlagen wird. Die
Aufnahme ist dazwischen nicht still, aber die Lautstärke steigt erneut deutlich.
Dieses Verfahren vergleicht die Kurve mit ihrem Wert etwas früher und erkennt
den Übergang dieser Zunahme über eine Schwelle.

- **Schwelle der Amplitudenzunahme: −26 dBFS**, etwa 0,05 absolute Amplitude.
- **Vergleichszeit für Anstieg: 5 ms**. Der aktuelle Wert wird mit dem Wert 5 ms
  zuvor verglichen. Die Vergleichszeit ist unabhängig von der Samplerate.

Die Schwelle meint hier ausdrücklich die **Differenz der linearen Amplituden**,
keinen relativen Lautstärkesprung in dB. Beispielsweise ergibt ein Anstieg von
0,20 auf 0,26 eine Differenz von 0,06 und liegt damit über der Standardschwelle.
Ein konstant lauter Ton löst dagegen keinen neuen Vorschlag aus.

Eine kleinere Schwelle erkennt schwächere Anstiege. Eine längere Vergleichszeit
kann auch langsamere Anstiege erfassen. Grenze: Sehr weich einsetzende Sounds
werden möglicherweise übersehen; starke Schwankungen innerhalb eines Sounds
können zusätzliche Vorschläge auslösen.

### Gemeinsame Einstellungen der drei neuen Verfahren

| Einstellung | Standard | Einstellbereich und Wirkung |
| --- | --- | --- |
| Hüllkurven-Glättung | 5 ms | 0–100 ms; größere Werte beruhigen kurze Schwankungen, können aber nahe Einsätze verwischen. |
| Mindestabstand der Klanganfänge | 100 ms | 1–10.000 ms; innerhalb dieses Abstands gewinnt der erste erkannte Anfang. |
| Vorlauf vor Klanganfang | 40 ms | 0–1.000 ms; setzt den Schnitt früher, damit der Anfang nicht abgeschnitten wird. |

Alle neuen Schwellen reichen von −96 bis 0 dBFS; die Attack-Vergleichszeit von
0,1 bis 100 ms. Als Einstieg sind 30–50 ms Vorlauf oft sinnvoll; bei sehr dicht
aufeinanderfolgenden Sounds kann ein kürzerer Vorlauf besser passen.

Glättung kann den erkannten Zeitpunkt etwas verschieben. Der Vorlauf wird auf
ganze digitale Messwerte aufgerundet. Vorschläge an oder vor dem Dateianfang
sowie doppelte Schnittpunkte entfallen. Ein schon am Dateianfang aktiver Klang
braucht dort keinen weiteren Marker. Bei Hysterese muss dieser Klang erst unter
die Rücksetzschwelle fallen, bevor ein neuer Start möglich wird.

Jede Variante behält ihre Einstellungen beim Wechsel innerhalb der Sitzung.
Beim nächsten Programmstart gelten wieder die Standardwerte. Änderungen und
Verfahrenswechsel wirken erst mit **Neu analysieren**; das Öffnen einer Datei
startet automatisch mit der ausgewählten Variante. Die drei neuen Verfahren
verwenden dabei ihre eingestellten Schwellen ohne automatische Schätzung.
Manuelle Marker bleiben erhalten. Änderungen an Markern während einer Analyse
führen zum Verwerfen ihres Ergebnisses.

### Glossar

| Begriff | Einfach erklärt |
| --- | --- |
| Waveform | Die gezeichneten positiven und negativen Ausschläge der Aufnahme über die Zeit. |
| Amplitude | Die Größe eines Ausschlags; größere Ausschläge bedeuten meist einen lauteren Klang. |
| Hüllkurve / Envelope | Eine geglättete Kurve der Ausschlagsstärke, an der man den Lautstärkeverlauf leichter erkennt. |
| Schwellenwert / Threshold | Eine festgelegte Grenze, deren Erreichen eine Erkennung auslösen kann. |
| Hysterese | Zwei verschiedene Grenzen: eine zum Starten und eine niedrigere zum erneuten Bereitwerden. |
| Onset | Der Beginn eines Klangs, etwa der erste Moment eines Trommelschlags. |
| Attack | Die Anstiegsphase zu Beginn eines Klangs: bei einem Schlag schnell, bei einem anschwellenden Ton langsam. |
| Peak | Ein örtlicher Gipfel der Ausschlagsstärke; er liegt häufig erst nach dem Klangbeginn. |
| Glättung | Benachbarte Werte werden gemittelt, damit kleine Schwankungen weniger ins Gewicht fallen. |
| dBFS | Pegelangabe bezogen auf die digitale Vollaussteuerung: 0 dBFS entspricht linearer Amplitude 1; −20 dBFS entspricht 0,1. Stärker negative Werte sind leiser. |
| Samplerate | Wie viele digitale Messwerte pro Sekunde und Kanal vorliegen, etwa 48.000 bei 48 kHz. |
| Sample | Kann einen einzelnen digitalen Messwert oder umgangssprachlich ein ganzes ausgeschnittenes Klangstück meinen. Samplepositionen im Programm beziehen sich auf Messwerte, nicht auf die Nummer eines Klangstücks. |
| Vorlauf | Zusätzliche Zeit vor dem erkannten Anfang, die im ausgeschnittenen Klangstück enthalten bleibt. |
| ms | Millisekunden: 1.000 ms sind eine Sekunde. |

### Andere Algorithmen ergänzen

Im Paket `chopper/detectors/` implementiert jeder Algorithmus in einer eigenen Datei das Qt-unabhängige
`Detector`-Protokoll:

```python
def detect(self, samples, samplerate, parameters) -> list[int]:
    # samples: [Frames, Kanäle], float64; Rückgabe: ganzzahlige Samplepositionen
    ...
```

Ein `DetectorSpec` mit eindeutiger ID, Anzeigename, Algorithmusinstanz und einer
Liste numerischer `Parameter` wird über `register(spec)` registriert. Die GUI
erzeugt Auswahl und Parameterfelder daraus. Neue Module werden in `chopper/detectors/__init__.py` importiert und dadurch vor
Erstellung des Hauptfensters registriert. Gemeinsame Schnittstellen und die Registry
liegen in `base.py`, gemeinsame Signalverarbeitung in `common.py`. Bestehende Imports
über `chopper.detectors` bleiben verfügbar. Detektoren verändern keine Audiodaten.

## Audio und Export

Unterstützt werden PCM-WAV (8/16/24/32 Bit) und Float-WAV (32/64 Bit), auch WAVEX
und RF64 als Eingang. Exportiert wird WAV mit gleicher Samplerate, Kanalzahl und
Sampleformat. Die Samplefolge bleibt erhalten; es gibt weder Fades noch
Normalisierung. Zusätzliche WAV-Metadaten werden nicht übernommen.

Die Namen lauten `aufnahme_001.wav`, `aufnahme_002.wav`, … . Vorhandene Dateien
werden niemals überschrieben. Bei einem Fehler werden abgeschlossene Dateien
gemeldet und unvollständige Dateien nach Möglichkeit entfernt.

Audio läuft über das Standardausgabegerät. Kanalzahl und Samplerate müssen vom
Gerät unterstützt werden; es gibt kein automatisches Downmixing oder Resampling.
Ausgabeprobleme verhindern weder Markerbearbeitung noch Export. Der Player nutzt
Float32 für die Geräteausgabe, der Export die unveränderten Float64-Quelldaten.

## Codequalität und Tests

mypy und Ruff werden mit den Entwicklungsabhängigkeiten (`.[dev]`) installiert.
Die gemeinsame Prüfung startet mit:

```powershell
.\check.bat
```

Sie prüft Ruff-Regeln, Formatierung, Typen und anschließend alle Tests und bricht
beim ersten Fehler ab. Die Einstellungen stehen zentral in `pyproject.toml`:

- Ruff vereinheitlicht Imports und Formatierung auf 100 Zeichen Zeilenlänge.
- Alle Funktionen und Methoden in `chopper/` benötigen Parameter- und
  Rückgabetypen, einschließlich `-> None` bei Methoden ohne Ergebnis.
- mypy prüft den gesamten Anwendungscode mit der aktiven Python-Version.
  Fehlende externe Typinformationen werden nur für `soundfile` und
  `sounddevice` toleriert. Die Audio-Callback-Schnittstellen sind über eigene
  Protokolle beschrieben.
- Testdateien werden formatiert und auf Ruff-Regelverstöße geprüft; vollständige
  Typannotationen sind dort nicht vorgeschrieben. mypy prüft `chopper/`.

Formatierung und automatisch korrigierbare Regelverstöße beheben:

```powershell
.venv\Scripts\python.exe -m ruff check . --fix
.venv\Scripts\python.exe -m ruff format .
```

Prüfungen einzeln ausführen:

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m mypy
.venv\Scripts\python.exe -m pytest
```

Die Tests prüfen Detektor, Dokument/Undo, Export-Roundtrips, simulierte
Audiowiedergabe sowie Qt-Interaktionen ohne sichtbares Fenster. Die tatsächliche
Tonwiedergabe muss zusätzlich mit dem eigenen Ausgabegerät angehört werden.

Temporäre Testdateien liegen pro Prüflauf in einem eigenen Ordner unter
`.artifacts/pytest/` und werden anschließend entfernt. Das gilt auch bei direktem
pytest-Aufruf und in PyCharm und vermeidet Zugriffsprobleme mit dem gemeinsamen
Windows-Temp-Ordner. Ein explizites `--basetemp` überschreibt diese Vorgabe.

Der persistente pytest-Cache ist deaktiviert, damit Prüfläufe nicht auf einen
unter einem anderen Windows-Benutzer angelegten Cache zugreifen. Alle Tests
laufen weiterhin; Cache-Funktionen wie `--last-failed` stehen nicht zur Verfügung.

## Sprache und Übersetzungen

Das Programm startet standardmäßig auf Englisch, unabhängig von der Systemsprache.
Alle Anwendungstexte stehen in `chopper/locales/en.json`; die deutsche Übersetzung
steht in `chopper/locales/de.json`. Der Code verwendet stabile Schlüssel wie
`tr("action.open")`. Dynamische Werte werden über benannte Platzhalter wie
`{count}` eingesetzt. Dateinamen und technische Kennungen bleiben unverändert.

Zum Start auf Deutsch in PowerShell:

```powershell
$env:CHOPPER_LANGUAGE = "de"
.venv\Scripts\python.exe -m chopper
```

Mit `CHOPPER_LANGUAGE=en` wird wieder Englisch verwendet. Die Sprache wird beim
Start gewählt; ein Wechsel erfordert einen Neustart. Regionale Codes wie `de-DE`
werden auf die Basissprache abgebildet. Unbekannte Sprachen und fehlende Einträge
fallen auf Englisch zurück.

Für weitere Sprachen `en.json` als `<sprachcode>.json` kopieren und die Werte
übersetzen. Schlüssel und benannte Platzhalter müssen erhalten bleiben.
Die Sprachdateien werden im installierten Paket mitgeliefert. Auch Detektornamen,
Parameterbeschriftungen und Einheiten können Übersetzungsschlüssel verwenden.
Die Tests prüfen die bestehenden Sprachdateien und die Oberfläche in Englisch
und Deutsch. Qt-Standardtexte verwenden, sofern verfügbar, die mit Qt gelieferten
Übersetzungen; Betriebssystem- und Bibliotheksfehler können eigene Texte liefern.

Das vollständige Konzept steht in [CONCEPT.md](CONCEPT.md).
