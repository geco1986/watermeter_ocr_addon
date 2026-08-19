"""Liest Kernanzahl und Pro-Kern-CPU-Auslastung aus /proc/stat.

Laeuft als leichter Hintergrund-Thread, der einmal pro Sekunde die
Auslastung je Kern berechnet und zwischenspeichert. Der /cpu_stats-Endpunkt
liefert dann sofort den letzten Stand, ohne bei jeder Anfrage zu blockieren
oder selbst zu messen.

Rechenweg (Standardverfahren, wie htop/top es machen): /proc/stat liefert
kumulative Jiffies seit Systemstart je Kern. Zwei Messungen im Abstand von
1s ergeben per Differenz die Auslastung in diesem Intervall.
"""

import os
import threading
import time
from collections import deque

_LOCK = threading.Lock()
_HISTORY_LEN = 30  # ca. 30 Sekunden Verlauf bei 1s-Takt

_state = {
    "core_count": 0,
    "overall_percent": 0.0,
    "cores": [],  # Liste von {"percent": float, "history": deque[float]}
    "updated_at": 0.0,
}

_started = False
_start_lock = threading.Lock()


def _read_stat() -> dict:
    """Liest /proc/stat, gibt {"cpu0": (idle, total), ...} zurueck."""
    result = {}
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("cpu"):
                    continue
                parts = line.split()
                label = parts[0]
                if label == "cpu" or not label[3:].isdigit():
                    continue  # Sammelzeile "cpu" oder unerwartetes Format ueberspringen
                try:
                    nums = [int(x) for x in parts[1:]]
                except ValueError:
                    continue
                if len(nums) < 4:
                    continue
                idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
                total = sum(nums)
                result[label] = (idle, total)
    except OSError:
        pass
    return result


def _count_cores_fallback() -> int:
    """Schnelle, sofortige Kernanzahl (bevor der erste Sampler-Durchlauf fertig ist)."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            n = sum(1 for line in fh if line.startswith("processor"))
        if n:
            return n
    except OSError:
        pass
    return os.cpu_count() or 1


def _sampler_loop():
    prev = _read_stat()
    while True:
        time.sleep(1.0)
        cur = _read_stat()
        labels = sorted(
            (k for k in cur if k.startswith("cpu") and k[3:].isdigit()),
            key=lambda k: int(k[3:]),
        )

        percents = []
        for label in labels:
            if label not in prev:
                percents.append(0.0)
                continue
            idle_prev, total_prev = prev[label]
            idle_cur, total_cur = cur[label]
            d_idle = idle_cur - idle_prev
            d_total = total_cur - total_prev
            pct = 0.0 if d_total <= 0 else max(0.0, min(100.0, (1 - d_idle / d_total) * 100))
            percents.append(round(pct, 1))

        overall = round(sum(percents) / len(percents), 1) if percents else 0.0

        with _LOCK:
            _state["core_count"] = len(percents)
            _state["overall_percent"] = overall
            if len(_state["cores"]) != len(percents):
                _state["cores"] = [
                    {"percent": p, "history": deque([p], maxlen=_HISTORY_LEN)}
                    for p in percents
                ]
            else:
                for i, p in enumerate(percents):
                    _state["cores"][i]["percent"] = p
                    _state["cores"][i]["history"].append(p)
            _state["updated_at"] = time.time()

        prev = cur


def ensure_started():
    """Startet den Hintergrund-Sampler einmalig (mehrfacher Aufruf ist sicher)."""
    global _started
    with _start_lock:
        if not _started:
            threading.Thread(target=_sampler_loop, daemon=True).start()
            _started = True


def get_snapshot() -> dict:
    """Aktueller Stand: Kernanzahl, Gesamtauslastung, je-Kern-Auslastung + Verlauf."""
    ensure_started()
    with _LOCK:
        core_count = _state["core_count"] or _count_cores_fallback()
        return {
            "core_count": core_count,
            "overall_percent": _state["overall_percent"],
            "cores": [
                {"percent": c["percent"], "history": list(c["history"])}
                for c in _state["cores"]
            ],
            "updated_at": _state["updated_at"],
        }
