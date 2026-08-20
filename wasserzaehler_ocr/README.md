# Wasserzähler OCR – Home-Assistant-Add-on

> **Version 5.1.0.** Liest einen Wasserzähler automatisch aus einem
> Kamerabild aus: Bild holen → zuschneiden → Ziffern per OCR erkennen →
> Plausibilität prüfen → Zählerstand und Durchflussrate liefern.
>
> **Alle Einstellungen macht man in der eingebauten Weboberfläche** – nicht
> mehr in der Home-Assistant-Add-on-Konfiguration. Die ist bewusst leer.

## Schnellstart

1. Add-on installieren und starten (siehe unten für den Installationsweg).
2. Auf der Add-on-Seite den Button **„Benutzeroberfläche öffnen"** klicken
   (oder den Eintrag „Wasserzähler" in der Seitenleiste).
3. Auf der Übersichtsseite oben auf **„Konfiguration"** klicken und ausfüllen:
   - **Kamera & Lampe** – welche Home-Assistant-Entitäten das Foto machen.
   - **OCR-Anbieter** – wer die Ziffern liest (siehe unten, „Welchen Anbieter
     wählen?").
   - **Ziffern des Zählwerks** – wie viele schwarze/rote Ziffern dein Zähler hat.
   - **Plausibilitätsprüfung** – Schutz gegen Fehlablesungen (siehe unten).
   - „Speichern" – wirkt sofort, **kein Add-on-Neustart nötig**.
4. Auf „Übersicht" → **„Bild optimieren (Tuner)"**: Drehwinkel und Zuschnitt
   live einstellen, bis nur noch die Ziffernreihe im Vorschaubild zu sehen
   ist, dann speichern.
5. Zurück zur Übersicht → **„Jetzt auswerten"** klicken. Ergebnis, Bilder und
   eventuelle Fehlermeldungen erscheinen direkt auf der Seite.

Das war's – ab jetzt liest das Add-on regelmäßig automatisch aus (Intervall
stellt man in Home Assistant über den REST-Sensor oder die Integration ein,
siehe unten).

## Wie es aufgebaut ist

```
Home-Assistant-Kamera
        │
        ▼
  Bild holen (+ Lampe kurz an)
        │
        ▼
  Rotieren & Zuschneiden  ←──  im Tuner eingestellt
        │
        ▼
  OCR (Ziffern lesen)     ←──  Anbieter in der Konfiguration gewählt
        │
        ▼
  Plausibilität prüfen    ←──  Schutz gegen Ausreißer
        │
        ▼
  Zählerstand + Durchflussrate + Status
```

Jeder Schritt ist über die Weboberfläche einstellbar, nichts muss in einer
Konfigurationsdatei bearbeitet werden.

## Welchen OCR-Anbieter wählen?

| Anbieter | Kosten | Läuft wo | Erkennungsqualität* |
|---|---|---|---|
| **Tesseract** | kostenlos | im Add-on (lokal) | schwach bei gewölbten Rollenzählwerken, ok bei flachen/gedruckten Anzeigen |
| **Ollama – im Add-on** | kostenlos | im Add-on (lokal, braucht RAM) | je nach Modell – siehe RAM-Empfehlung in der Konfiguration |
| **Ollama – eigener Server** | kostenlos | dein eigener Rechner/Server | wie oben, aber ohne den HA-Host zu belasten |
| **OpenAI / Gemini / Claude** | pro Anfrage (Cent-Bereich) | Cloud des Anbieters | am zuverlässigsten in unseren Tests |

*\* Erfahrungswerte aus diesem Projekt mit einem gewölbten NeoVac-Rollenzählwerk.
Bei anderen Zählertypen (flache Digitalanzeige) kann Tesseract deutlich besser
abschneiden.*

**Praktischer Rat:** Starte mit Tesseract oder einem kleinen lokalen Modell
zum Testen. Wenn die Erkennung zu oft danebenliegt, wechsle auf Ollama mit
einem stärkeren Modell (die Konfigurationsseite zeigt eine RAM-basierte
Empfehlung) oder auf einen Cloud-Anbieter.

**Bei Cloud-Anbietern:** Es entstehen Kosten pro Anfrage, und das Zählerbild
wird an den jeweiligen Dienst übertragen. Der API-Schlüssel wird lokal auf
diesem Host gespeichert.

**Bei „Ollama – im Add-on":** Ollama wird beim ersten Start mit diesem
Anbieter automatisch heruntergeladen (braucht einmalig Internet) und
persistent in `/data` abgelegt. Die Rechenlast liegt dann auf diesem Host.

## Installation

### Über den Add-on-Store (empfohlenes Repository)
Siehe die Repository-README, falls du dieses Add-on aus einem Git-Repository
installierst.

### Manuell
1. Diesen Ordner nach `/addons/wasserzaehler_ocr/` auf dem HA-Host kopieren.
2. App-Store neu laden (Einstellungen → Apps → App-Store → drei Punkte →
   neu laden, oder per SSH `ha addons reload`).
3. Unter „Lokale Apps" erscheint „Wasserzähler OCR" → installieren, starten.
4. Weiter mit „Schnellstart" oben.

## Update von einer älteren Version (4.x)

Falls du eine ältere Version mit Optionen in der Add-on-Konfiguration
(Kamera-Entität, OCR-Anbieter, API-Schlüssel usw.) genutzt hast: Diese Werte
werden **automatisch beim ersten Start** in die neuen Web-UI-Einstellungen
übernommen – nichts geht verloren. Öffne danach trotzdem einmal
„Konfiguration", um zu prüfen, dass alles korrekt übernommen wurde.

Die alte Konfigurationsseite in Home Assistant zeigt nach dem Update keine
Felder mehr an (das ist beabsichtigt) – falls sie eine Warnung zu nicht mehr
vorhandenen Optionen anzeigt, ist das harmlos; die alten Werte werden trotzdem
gelesen und übernommen.

## Endpunkte (für Fortgeschrittene / die Integration)

| Endpunkt | Zweck |
|---|---|
| `GET /process` | löst eine komplette Ablesung aus, liefert JSON |
| `GET /health` | `{"status": "ok"}` |
| `GET /status` | Live-Prozessstatus + letztes Ergebnis (für die Übersichtsseite) |
| `GET/POST /settings` | aktuelle Einstellungen lesen/schreiben |
| `GET /system_info` | RAM-Info + Modellempfehlung |
| `GET/POST /set_value` | Zählerstand manuell überschreiben |
| `GET /tuner`, `/config`, `/` | die drei Webseiten |

`/process` liefert bei Erfolg zum Beispiel:

```json
{"raw_digits": "01260624", "value": 1260.624, "plausible": true,
 "last_value": 1260.123, "flow_rate_l_min": 0.5, "status": "ok",
 "error_count": 0, "held": false}
```

Felder:
- `value` – Zählerstand in m³. Bleibt bei einer fehlgeschlagenen/unplausiblen
  Ablesung auf dem letzten guten Wert stehen (`held: true`), damit der
  Home-Assistant-Sensor nicht auf „unbekannt" springt.
- `flow_rate_l_min` – Durchflussrate in L/min seit der letzten Messung; `0`
  bei einer fehlgeschlagenen Ablesung, `null` nur beim allerersten Lauf.
- `status` – „ok" oder der Fehlergrund als Text.
- `error_count` – Anzahl aufeinanderfolgender Fehler, `0` nach Erfolg.

## Zählerstand manuell überschreiben

Auf der Übersichtsseite gibt es ein Eingabefeld, vorbefüllt mit dem letzten
ermittelten Wert – nützlich, wenn ein legitimer großer Sprung von der
Plausibilitätsprüfung blockiert wurde. Alternativ per HTTP:
`GET/POST /set_value?value=1265.500`. Der Zeitstempel wird dabei auf jetzt
gesetzt (Durchflussberechnung startet frisch) und der Fehlerzähler
zurückgesetzt.

## Einbindung in Home Assistant

### Über die Custom-Integration (empfohlen)
Siehe das separate Integration-Repository „Wasserzähler OCR" – bindet
Zählerstand, Durchfluss, Tagesverbrauch, Status usw. als native Entitäten ein,
inklusive Eingabefeld zur Korrektur direkt auf der Geräteseite.

### Über REST-Sensoren (Alternative)
```yaml
rest:
  - resource: "http://<HA-HOST-IP>:5000/process"
    scan_interval: 120
    timeout: 130
    sensor:
      - name: "Wasserzähler Stand"
        value_template: "{{ value_json.value }}"
        unit_of_measurement: "m³"
        device_class: water
        state_class: total_increasing
      - name: "Wasserzähler Durchfluss"
        value_template: "{{ value_json.flow_rate_l_min }}"
        unit_of_measurement: "L/min"
        state_class: measurement
    binary_sensor:
      - name: "Wasserzähler Status"
        value_template: "{{ value_json.status != 'ok' }}"
        device_class: problem
```

## Speicherort der Daten

Alle Bilder, Einstellungen und Zustandsdateien liegen im privaten
Add-on-Speicher `/data` – nicht im `/config`-Ordner. Sie überstehen
Neustarts und Updates. Die Bilder sind nicht per Samba/File-Editor
erreichbar; ansehen kannst du sie auf der Übersichtsseite.

## Fehlersuche

- Add-on-Log: Einstellungen → Apps → Wasserzähler OCR → Protokoll (zeigt
  auch die letzten Zeilen direkt auf der Übersichtsseite).
- Health-Check: `curl http://<HA-HOST-IP>:5000/health` → `{"status": "ok"}`.
- OCR-Anbieter-Status: Konfigurationsseite oder `GET /ollama_status`.
- Ollama erreichbar? `curl http://<OLLAMA-IP>:11434/api/tags`.

## Version 4.x → 5.x: was sich geändert hat

- Rotation/Zuschnitt: nur noch über den Tuner (`/tuner`), nicht mehr in der
  Add-on-Konfiguration.
- Alle übrigen Einstellungen: nur noch über die Konfigurationsseite (`/config`),
  nicht mehr in der Add-on-Konfiguration. Änderungen wirken sofort.
- Neuer OCR-Anbieter „Tesseract" (klassische, lokale OCR ohne KI-Modell).
- RAM-basierte Modellempfehlung auf der Konfigurationsseite.
- Alte Konfigurationswerte werden beim Update automatisch übernommen.

## Verbrauchsgrafik (ab 5.2.0)

Die Übersichtsseite zeigt jetzt ein Balkendiagramm mit vier Zeiträumen (Tag,
Woche, Monat, Jahr), umschaltbar per Tab. Die Daten sammeln sich mit jeder
erfolgreichen Ablesung – bei einer frischen Installation ist die Grafik also
zunächst leer und füllt sich über Tage/Wochen. Es gibt keine rückwirkende
Befüllung aus der Zeit vor diesem Update.

Gespeichert werden nur kompakte Stunden- und Tages-Schnappschüsse (kein
unbegrenzt wachsendes Rohdaten-Log), begrenzt auf 48 Stunden bzw. 400 Tage -
das reicht für alle vier Ansichten und bleibt im Kilobyte-Bereich.

## CPU-Auslastung von Ollama begrenzen (ab 5.3.0)

Home Assistant bietet für Add-ons keine Möglichkeit, CPU-Kerne oder
-Leistung in der Konfiguration zu begrenzen (das ist eine seit Jahren offene
Anfrage an das Supervisor-Projekt). Das Add-on löst es stattdessen selbst,
über zwei unabhängige Regler in der Konfigurationsseite:

- **CPU-Threads pro Anfrage** (`ollama_num_thread`) – begrenzt, wie viele
  CPU-Threads Ollama für eine einzelne Ablesung verwendet. Wirkt bei
  **beiden** Ollama-Varianten (eingebaut und extern), da der Wert bei jeder
  Anfrage mitgeschickt wird. 0 = Ollama entscheidet automatisch.
- **Maximale CPU-Auslastung** (`ollama_local_cpu_percent`) – eine echte
  Prozent-Drosselung (100% = ein Kern voll ausgelastet, 400% = vier Kerne).
  Wirkt **nur beim eingebauten Ollama** (`ollama_local`), da dafür Zugriff
  auf den laufenden Prozess nötig ist – bei einem externen Server lässt sich
  das von hier aus nicht steuern. 0 = unbegrenzt.

Beide Regler bremsen die Erkennung, wenn sie zu eng gesetzt werden – eine
Ablesung dauert dann länger, dafür bleibt mehr Leistung für Home Assistant
und andere Add-ons übrig. Sinnvoll auf Hosts, die neben diesem Add-on noch
viel anderes laufen lassen.

## CPU-Auslastung aller Kerne (ab 5.4.0)

Neue Seite **„CPU-Auslastung"** (über die Navigation oben auf jeder Seite
erreichbar) zeigt:

- Wie viele CPU-Kerne dieser Host hat.
- Die Auslastung **jedes einzelnen Kerns live** (aktualisiert sich jede
  Sekunde) – anders als die Home-Assistant-Systemübersicht, die meist nur
  einen einzelnen Gesamtwert zeigt.
- Zur Einordnung: die aktuell eingestellten CPU-Regler (Threads pro Anfrage,
  maximale Auslastung des eingebauten Ollama).

Nützlich, um direkt zu sehen, ob eine OCR-Anfrage den Host wirklich stark
auslastet und ob die CPU-Regler (siehe oben) etwas bewirken.
