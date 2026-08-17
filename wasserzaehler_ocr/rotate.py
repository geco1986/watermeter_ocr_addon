"""Rotations- und Zuschnitt-Logik fuer das Wasserzaehler-Kamerabild.

Basiert auf dem urspruenglichen cam_rotate.py-Skript, jetzt parametrisiert
ueber die Home-Assistant-Add-on-Optionen statt fest codierter Konstanten.
"""

from pathlib import Path

from PIL import Image


def rotate_and_crop(
    src_path: Path,
    dst_path: Path,
    angle: float,
    fill_color: str,
    crop_top: int,
    crop_bottom: int,
    crop_left: int,
    crop_right: int,
    quality: int,
    subsampling: int,
    log,
):
    """Rotiert und schneidet das Bild zu, speichert atomar nach dst_path.

    Gibt (breite, hoehe) des Ergebnisbilds zurueck. Wirft Exceptions bei
    Fehlern - der Aufrufer kuemmert sich um Logging und Fehlerantwort.
    """
    if not src_path.exists():
        raise FileNotFoundError(f"Quelldatei fehlt: {src_path}")

    with Image.open(src_path) as im:
        log(f"Eingang: {im.size[0]}x{im.size[1]}")
        rot = im.convert("RGB").rotate(
            angle,
            resample=Image.BICUBIC,
            expand=True,  # Leinwand vergroessern, keine Bildinfo verlieren
            fillcolor=fill_color,
        )

    log(f"Rotiert: {rot.size[0]}x{rot.size[1]}")

    top = crop_top
    bottom = rot.height - crop_bottom
    left = crop_left
    right = rot.width - crop_right

    if bottom <= top:
        raise ValueError(
            f"Schnitt oben/unten {crop_top}+{crop_bottom} passt nicht in "
            f"Hoehe {rot.height}. Werte in der Add-on-Konfiguration reduzieren."
        )
    if right <= left:
        raise ValueError(
            f"Schnitt links/rechts {crop_left}+{crop_right} passt nicht in "
            f"Breite {rot.width}. Werte in der Add-on-Konfiguration reduzieren."
        )

    out = rot.crop((left, top, right, bottom))

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_path.with_suffix(".tmp.jpg")
    out.save(tmp, "JPEG", quality=quality, subsampling=subsampling)
    tmp.replace(dst_path)  # atomar, damit HA nie eine halbe Datei liest

    log(
        f"Ausgang: {out.size[0]}x{out.size[1]} -> {dst_path.name} "
        f"({dst_path.stat().st_size} Bytes)"
    )

    return out.size
