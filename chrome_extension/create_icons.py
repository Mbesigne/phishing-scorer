#!/usr/bin/env python3
"""
Générateur d'icônes pour l'extension Chrome Phishing Risk Scorer.
Nécessite : pip install Pillow

Usage : python create_icons.py
        → Crée icons/icon-16.png, icons/icon-48.png, icons/icon-128.png
"""

import os

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("❌  Pillow non installé. Lancez : pip install Pillow")
    raise SystemExit(1)

SIZES = [16, 48, 128]

def create_shield_icon(size: int) -> Image.Image:
    """Dessine un icône bouclier violet sur fond transparent."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s    = size

    # Cercle de fond dégradé simulé (2 passes)
    for i in range(s // 2):
        alpha = int(255 * (1 - i / (s / 2)) * 0.9)
        r = int(124 - i * 20 / (s / 2))
        g = int(58  + i * 10 / (s / 2))
        b = int(237 - i * 30 / (s / 2))
        draw.ellipse([i, i, s - i - 1, s - i - 1], outline=(r, g, b, alpha))

    # Fond du cercle plein
    m = max(1, s // 10)
    draw.ellipse([m, m, s - m - 1, s - m - 1], fill=(124, 58, 237, 230))

    # Bouclier (polygone blanc)
    cx = s / 2
    top  = s * 0.18
    bot  = s * 0.82
    left = s * 0.22
    right = s * 0.78
    mid  = s * 0.58

    shield_pts = [
        (cx,   top),
        (right, top + (mid - top) * 0.25),
        (right, mid),
        (cx,   bot),
        (left,  mid),
        (left,  top + (mid - top) * 0.25),
    ]
    draw.polygon(shield_pts, fill=(255, 255, 255, 210))

    # Coche (check mark) violette dans le bouclier
    lw = max(2, s // 14)
    check = [
        (cx - s * 0.16, cx),
        (cx - s * 0.04, cx + s * 0.13),
        (cx + s * 0.18, cx - s * 0.12),
    ]
    draw.line(check, fill=(124, 58, 237, 255), width=lw)

    return img


def main():
    os.makedirs("icons", exist_ok=True)
    for size in SIZES:
        icon = create_shield_icon(size)
        path = f"icons/icon-{size}.png"
        icon.save(path)
        print(f"✅  Créé : {path}")
    print("\nIcones générées avec succès !")
    print("Rechargez l'extension dans chrome://extensions/ si elle était déjà chargée.")


if __name__ == "__main__":
    main()
