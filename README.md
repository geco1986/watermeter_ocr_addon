# Wasserzähler OCR – Home-Assistant-Add-on-Repository

Dieses Repository enthält das **Wasserzähler-OCR-Add-on**: Es holt das Bild
deiner ESPHome-Kamera, schaltet die Lampe, rotiert/schneidet zu, liest den
Zähler per Ollama-Vision-Modell aus, prüft die Plausibilität und liefert
Zählerstand, Durchflussrate und Status.

> **Hinweis:** Die zugehörige **Integration** (native HA-Entitäten) liegt in
> einem separaten Repository und wird über HACS installiert. Dieses Repository
> hier ist nur das Add-on.

## Installation über den Add-on-Store

1. Dieses Repository zu GitHub hochladen (siehe unten).
2. In Home Assistant: Einstellungen → Add-ons → Add-on-Store → oben rechts die
   drei Punkte → **Repositories** (Repository hinzufügen).
3. Die GitHub-URL dieses Repos einfügen und hinzufügen.
4. Der Store lädt neu; das Add-on „Wasserzähler Rotate & OCR" erscheint unter
   diesem Repository → installieren.
5. Konfigurieren (Kamera-Entität, Lampe, Ollama-URL, Modell) und starten.

## Repository zu GitHub hochladen

```bash
cd wasserzaehler_ocr_addon_repo
git init
git add .
git commit -m "Initial commit: Wasserzähler OCR Add-on"
git branch -M main
git remote add origin https://github.com/DEIN-USER/wasserzaehler_ocr_addon.git
git push -u origin main
```

## Inhalt

- `wasserzaehler_ocr/` – das eigentliche Add-on (config.yaml, Dockerfile,
  Python-Module, translations, Icon)
- `wasserzaehler_ocr/pi_setup/` – optionales Skript, falls du Ollama auf einem
  separaten Raspberry Pi betreiben willst

Details zu Konfiguration, Endpunkten und dem `set_value`-Aufruf in
`wasserzaehler_ocr/README.md`.

## Lizenz

MIT – siehe LICENSE.
