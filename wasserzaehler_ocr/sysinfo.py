"""Systeminformationen und Modellempfehlung anhand des verfuegbaren RAM.

Die Groessenangaben stammen aus der Praxis dieses Projekts: Qwen2.5-VL liest
Ziffern deutlich zuverlaessiger als LLaVA oder Moondream (siehe README), daher
ist die Empfehlung bewusst auf die Qwen-Familie ausgerichtet. Tesseract
braucht kein nennenswertes RAM, ist aber bei diesem Zaehlwerk-Typ schwaecher.
"""

# (Modellname, minimal empfohlenes freies RAM in GB, Kurzbeschreibung)
# Sortiert von klein nach gross.
MODEL_TABLE = [
    {"model": "moondream", "min_ram_gb": 2.0,
     "note": "sehr genügsam, aber schwach bei Ziffern – nur als Notlösung"},
    {"model": "qwen2.5vl:3b", "min_ram_gb": 3.5,
     "note": "guter Kompromiss aus Geschwindigkeit und Erkennungsqualität"},
    {"model": "qwen2.5vl:7b", "min_ram_gb": 6.0,
     "note": "beste Ziffernerkennung in diesem Projekt, aber langsamer auf CPU"},
    {"model": "llama3.2-vision", "min_ram_gb": 9.0,
     "note": "sehr groß, auf CPU oft mehrere Minuten pro Bild"},
]

TESSERACT_NOTE = (
    "Tesseract braucht kaum RAM und ist sehr schnell, liest gewölbte "
    "Rollenzählwerke aber oft schlechter als ein Vision-Modell. Guter "
    "Startpunkt zum Test, bei Problemen auf ein Modell wechseln."
)


def _read_mem_gb():
    """Liest Gesamt- und verfuegbaren RAM aus /proc/meminfo (in GB)."""
    total_kb = avail_kb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
    except OSError:
        pass
    total_gb = round(total_kb / 1024 / 1024, 1) if total_kb else None
    avail_gb = round(avail_kb / 1024 / 1024, 1) if avail_kb else total_gb
    return total_gb, avail_gb


def get_recommendation(log=None):
    """Liefert RAM-Info plus Modellempfehlung fuer lokale Ollama-Modelle.

    Empfohlen wird das groesste Modell, dessen min_ram_gb mit Sicherheits-
    puffer (70% des verfuegbaren RAM) noch passt - Ollama selbst, das
    Betriebssystem und Home Assistant brauchen ja auch RAM.
    """
    total_gb, avail_gb = _read_mem_gb()
    if avail_gb is None:
        return {
            "mem_total_gb": None, "mem_available_gb": None,
            "recommended_model": None, "table": [], "tesseract_note": TESSERACT_NOTE,
            "error": "RAM konnte nicht ermittelt werden (/proc/meminfo fehlt)",
        }

    budget = avail_gb * 0.7
    table = []
    best = None
    for entry in MODEL_TABLE:
        fits = entry["min_ram_gb"] <= budget
        table.append({**entry, "fits": fits})
        if fits:
            best = entry["model"]

    if best is None:
        # nichts passt bequem -> kleinstes Modell als Notloesung vorschlagen,
        # aber Tesseract als eigentliche Empfehlung markieren
        best = None

    result = {
        "mem_total_gb": total_gb,
        "mem_available_gb": avail_gb,
        "recommended_model": best,
        "recommended_provider": "ollama_local" if best else "tesseract",
        "table": table,
        "tesseract_note": TESSERACT_NOTE,
    }
    if log:
        log(f"RAM: {avail_gb} GB frei von {total_gb} GB -> Empfehlung: "
            f"{result['recommended_provider']}"
            f"{' (' + best + ')' if best else ''}")
    return result
