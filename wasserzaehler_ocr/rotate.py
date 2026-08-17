"""Rotations- und Zuschnitt-Logik fuer das Wasserzaehler-Kamerabild.

Basiert auf dem urspruenglichen cam_rotate.py-Skript, jetzt parametrisiert.
render() gibt das fertige Bild zurueck (fuer die Live-Vorschau im Tuner),
rotate_and_crop() speichert es zusaetzlich atomar in eine Datei.
"""

from pathlib import Path

from PIL import Image


def render(
    src_path: Path,
    angle: float,
    fill_color: str,
    crop_top: int,
    crop_bottom: int,
    crop_left: int,
    crop_right: int,
    log=None,
):
    """Rotiert und schneidet das Bild zu und gibt das PIL-Image zurueck.

    Wirft FileNotFoundError, wenn die Quelle fehlt, und ValueError, wenn die
    Schnittwerte nicht in das rotierte Bild passen.
    """
    if not src_path.exists():
        raise FileNotFoundError(f"Quelldatei fehlt: {src_path}")

    with Image.open(src_path) as im:
        if log:
            log(f"Eingang: {im.size[0]}x{im.size[1]}")
        rot = im.convert("RGB").rotate(
            angle,
            resample=Image.BICUBIC,
            expand=True,  # Leinwand vergroessern, keine Bildinfo verlieren
            fillcolor=fill_color,
        )

    if log:
        log(f"Rotiert: {rot.size[0]}x{rot.size[1]}")

    top = crop_top
    bottom = rot.height - crop_bottom
    left = crop_left
    right = rot.width - crop_right

    if bottom <= top:
        raise ValueError(
            f"Schnitt oben/unten {crop_top}+{crop_bottom} passt nicht in "
            f"Hoehe {rot.height}. Werte reduzieren."
        )
    if right <= left:
        raise ValueError(
            f"Schnitt links/rechts {crop_left}+{crop_right} passt nicht in "
            f"Breite {rot.width}. Werte reduzieren."
        )

    return rot.crop((left, top, right, bottom))


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
    """Rotiert/schneidet zu und speichert atomar nach dst_path.

    Gibt (breite, hoehe) des Ergebnisbilds zurueck.
    """
    out = render(
        src_path=src_path,
        angle=angle,
        fill_color=fill_color,
        crop_top=crop_top,
        crop_bottom=crop_bottom,
        crop_left=crop_left,
        crop_right=crop_right,
        log=log,
    )

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_path.with_suffix(".tmp.jpg")
    out.save(tmp, "JPEG", quality=quality, subsampling=subsampling)
    tmp.replace(dst_path)  # atomar, damit HA nie eine halbe Datei liest

    if log:
        log(
            f"Ausgang: {out.size[0]}x{out.size[1]} -> {dst_path.name} "
            f"({dst_path.stat().st_size} Bytes)"
        )

    return out.size
