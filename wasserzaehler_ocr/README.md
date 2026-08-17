# Wasserzähler Rotate & OCR – Home-Assistant-Add-on

> **Version 4.4.0** – komplettes Paket. Holt das Kamerabild, schaltet die
> Lampe, rotiert/schneidet zu, liest den Zähler per Ollama-Vision-Modell,
> prüft die Plausibilität und liefert Zählerstand, Durchflussrate und Status.

## Schnellstart (5 Schritte)

1. **Ganzen Ordner kopieren** nach `/addons/wasserzaehler_ocr/` auf dem
   HA-Host (per Samba-, „File editor"- oder „Studio Code Server"-Add-on).
   Alle Dateien inkl. Unterordner `translations/` müssen mit.
2. **App-Store neu laden:** Einstellungen → Apps → App-Store → drei Punkte →
   neu laden (oder per SSH `ha addons reload`).
3. **Installieren:** Unter „Lokale Apps" erscheint „Wasserzähler Rotate & OCR"
   → installieren (erster Build dauert ein paar Minuten).
4. **Konfigurieren** (Reiter Konfiguration), mindestens:
   - `camera_entity` → deine Kamera (z. B. `camera.esp32_cam_esp32_kamera`)
   - `light_entity` → deine Lampe (z. B. `light.esp32_cam_kamera_blitzlicht`)
   - `ollama_url` → z. B. `http://192.168.3.3:11434/api/generate`
   - `ollama_model` → dein funktionierendes Modell (z. B. `gemma4:e2b`)
5. **Starten** und testen: `http://<HA-HOST-IP>:5000/process` im Browser.

Danach den REST-Sensor aus dem Abschnitt „Aufruf aus Home Assistant" unten in
die `configuration.yaml` eintragen.

---

Dieses Add-on übernimmt die komplette Kette in einem:

1. **Bild holen** – ruft ein aktuelles Bild deiner ESPHome-Kamera über die
   Home-Assistant-API (camera_proxy) ab. Kein Eingriff am ESP nötig.
2. **Rotieren & Zuschneiden** (Logik aus deinem `cam_rotate.py`).
3. **OCR** – schickt das zugeschnittene Bild an einen **ausgelagerten
   Ollama-Vision-Server** (z. B. auf einem Raspberry Pi 4) und liest die
   Ziffern aus.

Die schwere Bilderkennung läuft damit nicht mehr auf dem Home-Assistant-Host,
sondern auf dem separaten Pi. Auf dem HA-Host bleibt nur das leichte
Add-on (Bild holen, drehen, weiterreichen).

## Teil 1 – Ollama auf dem Raspberry Pi 4 einrichten

Im Ordner `pi_setup/` liegt `install_ollama_pi.sh`. Auf dem Pi ausführen:

```bash
chmod +x install_ollama_pi.sh
./install_ollama_pi.sh
```

Das Skript prüft Architektur und RAM, installiert Ollama, macht es im
Netzwerk erreichbar (OLLAMA_HOST=0.0.0.0) und lädt das Modell moondream.
Am Ende zeigt es die IP des Pi an – die brauchst du für die Add-on-Option
`ollama_url`.

**Zum Modell:** Standard ist `moondream` – ein winziges Vision-Modell (~830 MB,
braucht ~2 GB RAM), das auf einem 4-GB-Pi 4 läuft. Falls du einen 8-GB-Pi
hast und bessere Erkennung willst, kannst du im Skript und in der
Add-on-Option `ollama_model` auf `gemma4:e2b` wechseln.

## Teil 2 – Add-on in Home Assistant installieren

1. Ordner `wasserzaehler_addon` nach `/addons/wasserzaehler_ocr/` auf dem
   HA-Host kopieren (alle Dateien inkl. `translations/`-Unterordner; der
   Ordner `pi_setup/` darf mit dabei sein, stört nicht).
2. Einstellungen → Apps → App-Store → oben rechts (drei Punkte) → neu laden.
   Alternativ per SSH: `ha addons reload`.
3. Unter „Lokale Apps" erscheint „Wasserzähler Rotate & OCR" → installieren.
4. Beim ersten Start baut das Add-on das Image – ein paar Minuten.
5. In der Konfiguration mindestens setzen:
   - `camera_entity` → Entity-ID deiner Kamera (z. B. camera.watermeter)
   - `ollama_url` → http://<PI-IP>:11434/api/generate
6. Add-on starten.

## Konfiguration

Alle Werte sind über die Konfigurationsseite einstellbar. Standardwerte
entsprechen deinen bisherigen Einstellungen.

| Option | Standard | Bedeutung |
|---|---|---|
| camera_entity | camera.watermeter | HA-Kamera, von der das Bild geholt wird |
| light_entity | (leer) | Lampe (light./switch.), die vor dem Foto an- und danach ausgeht |
| light_warmup | 10 | Wartezeit nach Licht-an bis zum Foto (Sek.) |
| src_path | /config/watermeter/watermeter_image.jpg | abgelegtes Rohbild |
| dst_path | /config/watermeter/watermeter_rotated.jpg | zugeschnittenes Bild |
| save_source | true | Rohbild behalten (zum Kalibrieren) |
| rotate_angle | 53 | Drehwinkel (gegen Uhrzeigersinn) |
| fill_color | black | Eckenfüllung |
| crop_top / _bottom / _left / _right | 400 / 340 / 75 / 200 | Zuschnitt in Pixel |
| jpeg_quality | 25 | JPEG-Qualität |
| jpeg_subsampling | 0 | 0 = 4:4:4 |
| ollama_url | http://192.168.3.3:11434/api/generate | ausgelagerter Ollama-Server |
| ollama_model | gemma4:e2b | Vision-Modell |
| ollama_keep_alive | 0 | 0 = Modell nach jedem Lauf entladen |
| ollama_timeout | 120 | max. Wartezeit auf Antwort (Sek.) |
| ocr_main_digits | 5 | schwarze Vorkommastellen |
| ocr_decimal_digits | 3 | rote Nachkommastellen |
| plausibility_check | true | Plausibilitätsprüfung ein/aus |
| max_increase | 5.0 | max. erlaubter Zuwachs pro Ablesung (m³) |
| allow_equal | true | gleicher Wert wie zuvor erlaubt |
| reject_implausible | true | unplausible Werte verwerfen statt nur markieren |
| last_value_path | /config/watermeter/last_value.json | Speicher des letzten guten Werts |
| log_max_bytes | 50000 | Log-Rotationsgröße |

## Aufruf aus Home Assistant

REST-Sensor in der `configuration.yaml`. Als IP die des HA-Hosts eintragen
(nicht „localhost"):

```yaml
rest:
  - resource: "http://<HA-HOST-IP>:5000/process"
    scan_interval: 120
    timeout: 130
    sensor:
      - name: "Wasserzähler Rohwert"
        value_template: "{{ value_json.raw_digits }}"
      - name: "Wasserzähler Stand"
        value_template: "{{ value_json.value }}"
        unit_of_measurement: "m³"
        device_class: water
        state_class: total_increasing
      - name: "Wasserzähler Durchfluss"
        value_template: "{{ value_json.flow_rate_l_min }}"
        unit_of_measurement: "L/min"
        state_class: measurement
      - name: "Wasserzähler Fehlerzähler"
        value_template: "{{ value_json.error_count }}"
        state_class: measurement
    binary_sensor:
      - name: "Wasserzähler Status"
        value_template: "{{ value_json.status != 'ok' }}"
        device_class: problem
```

Damit hast du in HA:
- **Wasserzähler Stand** (m³) – für das Energie-Dashboard
- **Wasserzähler Durchfluss** (L/min) – aktuelle Durchflussrate
- **Wasserzähler Fehlerzähler** – zählt aufeinanderfolgende Fehler, 0 nach Erfolg
- **Wasserzähler Status** – „Problem" an, sobald `status` nicht „ok" ist; der
  genaue Fehlertext steht im Attribut bzw. im `status`-Feld. Ideal für eine
  Automation wie „benachrichtige mich, wenn der Fehlerzähler über 3 steigt".

Der Endpunkt `/process` liefert bei Erfolg:

```json
{"raw_digits": "01260624", "value": 1260.624, "plausible": true,
 "last_value": 1260.123, "flow_rate_l_min": 0.5, "status": "ok",
 "error_count": 0}
```

Felder:
- `value` - Zaehlerstand in m3
- `flow_rate_l_min` - aktuelle Durchflussrate in Litern pro Minute
  (aus der Differenz zur letzten Messung und der Zeit dazwischen; beim
  allerersten Lauf `null`, da es keinen Vergleich gibt; bei einer
  fehlgeschlagenen Ablesung `0`)
- `status` - "ok" bei Erfolg, sonst der Fehlergrund als Text
- `error_count` - Anzahl der aufeinanderfolgenden Fehler (0 nach Erfolg)

und bei Problemen (HTTP 422):

```json
{"raw_digits": null, "error": "erwartet 8 Ziffern, erkannt 7: '0126062'"}
```

## Plausibilitätsprüfung

Nach der OCR prüft das Add-on den Wert gegen den zuletzt gespeicherten guten
Wert (in `last_value_path`). Zwei Regeln:

1. **Monotonie** – ein Wasserzähler läuft nur vorwärts. Ein Wert, der kleiner
   ist als der letzte, gilt als unplausibel. Mit `allow_equal: true` darf der
   Wert gleich bleiben (sinnvoll, wenn zwischen zwei Ablesungen kein Verbrauch
   war).
2. **Maximaler Sprung** – der Zuwachs darf `max_increase` (in m³) nicht
   überschreiten. Ein plötzlicher Riesensprung ist meist ein OCR-Fehler.

Bei `reject_implausible: true` wird ein unplausibler Wert **verworfen**
(`raw_digits`/`value` = null, zusätzlich `rejected: true` und `error` mit
Begründung), damit dein Sensor nicht auf einen Fehlwert springt. Der letzte
gute Wert bleibt als Referenz erhalten. Bei `false` wird der Wert trotzdem
geliefert, aber mit `plausible: false` markiert – dann entscheidest du in HA
selbst.

**Letzten Wert halten (`hold_last_on_failure`, Standard an):** Schlaegt eine
Ablesung fehl oder ist der Wert unplausibel (zu klein, zu grosser Sprung),
behaelt der Zaehlerstand (`value`) den letzten gueltigen Wert, statt auf null
zu fallen. So bleibt dein Sensor in Home Assistant gueltig und faellt nicht
auf „unbekannt". Die Felder `status`, `error_count` und `held: true` zeigen
trotzdem an, dass die aktuelle Ablesung nicht geklappt hat. Nur wenn es noch
gar keinen gueltigen Vorwert gibt (allererster Lauf), bleibt `value` null.

**Erster Lauf:** Solange noch kein letzter Wert gespeichert ist, wird jeder
Wert akzeptiert (es gibt ja keinen Vergleich). Falls du einen Startwert
vorgeben willst, lege `last_value.json` mit z. B. `{"value": 1260.624}` selbst
an, bevor du das erste Mal ausliest.

## Fehlersuche

- Add-on-Log: Einstellungen → Apps → Wasserzähler Rotate & OCR → Protokoll.
- Ausfuehrliches Verarbeitungslog: direkt im Add-on unter "Protokoll" (Log-Tab), nicht mehr als Datei.
- Health-Check: `curl http://<HA-HOST-IP>:5000/health` → `{"status": "ok"}`.
- Ollama erreichbar? Vom HA-Host aus: `curl http://<PI-IP>:11434/api/tags`.
- Falsche Ziffernzahl? Zuerst `watermeter_rotated.jpg` anschauen und crop-Werte
  anpassen, bis nur die Ziffernreihe im Bild ist.

## Zählerstand manuell setzen

Falls ein legitimer großer Sprung von der Plausibilitätsprüfung blockiert
wird, kannst du den gespeicherten Wert überschreiben:

- Über die Integration (empfohlen): Dienst `wasserzaehler_ocr.set_value` mit
  dem gewünschten m³-Wert aufrufen (Entwicklerwerkzeuge → Aktionen, oder per
  Knopf im Dashboard).
- Direkt per HTTP: `http://<HA-HOST-IP>:5000/set_value?value=1265.500`

Dabei wird der Zeitstempel auf jetzt gesetzt (die Durchflussberechnung startet
frisch) und der Fehlerzähler zurückgesetzt.

## Rotation & Zuschnitt einstellen (Tuner-Webseite)

Statt die crop-Werte zu erraten, kannst du sie live einstellen:

1. Im Browser `http://<HA-HOST-IP>:5000/tuner` öffnen.
2. „Neues Bild von Kamera holen" (holt ein frisches Bild mit Lampe, wie im
   echten Ablauf) – oder das zuletzt gespeicherte Quellbild wird genutzt.
3. Drehwinkel und Zuschnitt (oben/unten/links/rechts) sowie JPEG-Qualität per
   Schieberegler anpassen. Die Vorschau rechts aktualisiert sich sofort und
   zeigt genau das Bild, das an die OCR geht.
4. Wenn nur noch die Ziffernreihe im Vorschaubild ist: „Werte speichern
   (überschreiben)". Ab dann gelten diese Werte für alle Ablesungen.
5. „Auf Add-on-Konfig zurücksetzen" verwirft die getunten Werte wieder.

Die getunten Werte liegen in `tuning_path` (Standard
`/config/watermeter/tuning.json`) und haben Vorrang vor den Rotations-/
Zuschnittwerten in der Add-on-Konfiguration, solange die Datei existiert.
Willst du sie dauerhaft als Standard, kannst du sie zusätzlich in die
Add-on-Konfiguration eintragen.

## Benutzeroberfläche (Button „Benutzeroberfläche öffnen")

Das Add-on hat eine eingebaute Weboberfläche über Ingress. Nach dem Start
erscheint im Add-on-Info-Bildschirm der Button **„Benutzeroberfläche öffnen"**
(und ein Eintrag „Wasserzähler" in der HA-Seitenleiste). Die Startseite bietet:

- **Auswertung starten** – löst eine komplette Ablesung aus und zeigt
  Zählerstand, Durchfluss, Status und das zugeschnittene Bild direkt an.
- **Bild optimieren** – öffnet den Tuner (Rotation & Zuschnitt live einstellen).

Technisch lauscht das Add-on auf zwei Ports: 8099 für Ingress (der Button,
abgesichert über die HA-Anmeldung) und 5000 für die HTTP-API (die von der
Integration bzw. dem REST-Sensor genutzt wird). Beide bieten dieselben
Funktionen.

## Übersichtsseite (Kommandozentrale)

Die Startseite (Button „Benutzeroberfläche öffnen") zeigt jetzt:

- **Aktueller Stand** – Zählerstand, Durchfluss, Zeitpunkt der letzten
  erfolgreichen Ablesung, Fehlerzähler und der Live-Prozessstatus
  (Bild holen → Zuschneiden → OCR läuft → fertig), der sich während einer
  Auswertung automatisch aktualisiert.
- **Letztes Ergebnis** – alle Details inklusive ausführlicher Fehlerbeschreibung.
- **Zählerstand überschreiben** – Eingabefeld, vorbefüllt mit dem letzten
  ermittelten Wert; anpassen und speichern.
- **Bilder der letzten Analyse** – das zugeschnittene (an die OCR gesendete)
  Bild und das Rohbild der Kamera.
- **Ollama-Status** – zeigt, ob der Server erreichbar und das Modell geladen ist.
- **Letzte Protokollzeilen** – die jüngsten Log-Einträge direkt auf der Seite.

Die Seite pollt den Status alle 2 Sekunden, sodass ein laufender
Ablesevorgang live mitverfolgt werden kann.

## KI-Anbieter wählen (lokal, extern oder Cloud)

Über die Option `ocr_provider` wählst du, welche KI die Ziffern liest:

- **ollama_local** – Ollama läuft direkt im Add-on. Ollama wird beim ersten
  Start mit diesem Anbieter heruntergeladen (persistent in `/data`, überlebt
  Neustarts) und das Modell (`ollama_model`) automatisch geladen. Bequem, aber
  die Rechenlast liegt auf dem HA-Host. Braucht beim ersten Start einmalig
  Internet für den Ollama-Download; danach nicht mehr.
- **ollama_remote** – ein externer Ollama-Server (Standard), über `ollama_url`.
- **openai** – OpenAI Vision. Nötig: `openai_api_key`, `openai_model`
  (z. B. gpt-4o-mini).
- **gemini** – Google Gemini. Nötig: `gemini_api_key`, `gemini_model`
  (z. B. gemini-2.0-flash).
- **claude** – Anthropic Claude. Nötig: `claude_api_key`, `claude_model`.

Der aktive Anbieter und sein Status (erreichbar / Schlüssel gesetzt) werden auf
der Übersichtsseite unter „KI-Anbieter" angezeigt.

**Hinweis zu Cloud-Anbietern:** Es entstehen Kosten pro Anfrage, und das
Zählerbild wird an den jeweiligen Dienst übertragen. Der API-Schlüssel wird in
den Add-on-Optionen gespeichert.
