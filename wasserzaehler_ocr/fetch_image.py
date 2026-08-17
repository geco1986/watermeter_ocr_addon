"""Bildabruf von der Home-Assistant-Kamera-Entitaet.

Nutzt den camera_proxy-Endpunkt der HA-API. Das Add-on bekommt vom
Supervisor automatisch ein Token in der Umgebungsvariable SUPERVISOR_TOKEN,
mit dem der Zugriff auf http://supervisor/core/api/... erlaubt ist.
"""

import os
from pathlib import Path

import requests

SUPERVISOR_API = "http://supervisor/core/api"


def _call_service(domain: str, service: str, entity_id: str, timeout: int, log):
    """Ruft einen HA-Service auf, z. B. light.turn_on / switch.turn_off."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError(
            "SUPERVISOR_TOKEN fehlt - laeuft das Add-on mit homeassistant_api: true?"
        )
    url = f"{SUPERVISOR_API}/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(
        url, headers=headers, json={"entity_id": entity_id}, timeout=timeout
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Service {domain}.{service} fuer {entity_id} fehlgeschlagen "
            f"(HTTP {resp.status_code})."
        )


def set_light(entity_id: str, on: bool, timeout: int, log):
    """Schaltet die Lampe der Kamera ein oder aus.

    Domaene (light/switch) wird aus der Entity-ID abgeleitet. Fehler beim
    Ausschalten werden nur geloggt, nicht geworfen - das Bild ist wichtiger.
    """
    if not entity_id:
        return  # keine Lampe konfiguriert -> nichts tun

    domain = entity_id.split(".", 1)[0]
    if domain not in ("light", "switch"):
        log(f"WARNUNG: Lampe '{entity_id}' hat unerwartete Domaene '{domain}', "
            f"versuche es trotzdem.")

    service = "turn_on" if on else "turn_off"
    try:
        _call_service(domain, service, entity_id, timeout, log)
        log(f"Lampe {entity_id} -> {'AN' if on else 'AUS'}")
    except Exception as exc:
        # Ausschalten soll den Ablauf nie abbrechen; Einschalten schon eher,
        # aber wir loggen es und lassen den Aufrufer weitermachen.
        log(f"WARNUNG: Lampe schalten fehlgeschlagen: {exc}")


def fetch_camera_image(camera_entity: str, dst_path: Path, timeout: int, log):
    """Holt ein aktuelles Bild der Kamera-Entitaet und speichert es.

    Gibt dst_path zurueck. Wirft Exceptions bei Fehlern.
    """
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError(
            "SUPERVISOR_TOKEN fehlt - laeuft das Add-on mit homeassistant_api: true?"
        )

    url = f"{SUPERVISOR_API}/camera_proxy/{camera_entity}"
    headers = {"Authorization": f"Bearer {token}"}

    log(f"Hole Bild von {camera_entity} ...")
    resp = requests.get(url, headers=headers, timeout=timeout)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Kamera-Abruf fehlgeschlagen (HTTP {resp.status_code}). "
            f"Existiert die Entitaet '{camera_entity}' und liefert sie ein Bild?"
        )

    content = resp.content
    if not content:
        raise RuntimeError(f"Kamera '{camera_entity}' lieferte ein leeres Bild.")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_path.with_suffix(".download.jpg")
    tmp.write_bytes(content)
    tmp.replace(dst_path)

    log(f"Bild gespeichert: {dst_path.name} ({len(content)} Bytes)")
    return dst_path
