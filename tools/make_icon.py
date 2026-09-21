"""Generate the TechReader application icon (icon.ico).

Draws a rounded teal square with a bold white "TR" monogram, then saves it
as a multi-resolution .ico suitable for the PyInstaller EXE icon.

Usage:  python tools/make_icon.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "icon.ico")

BG = (13, 115, 119, 255)      # teal
BG_DARK = (10, 96, 100, 255)  # bottom of the subtle vertical gradient
FG = (255, 255, 255, 255)
RADIUS = 48                   # in 256-unit space

FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_FALLBACK = r"C:\Windows\Fonts\arialbd.ttf"

SIZES = (256, 128, 64, 48, 32, 24, 16)


def build_one(size: int) -> Image.Image:
    s = size / 256.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=round(RADIUS * s),
                        fill=BG)

    # Subtle top-to-bottom gradient: overlay a darker rounded rect at the
    # bottom half through an alpha mask.
    grad = Image.new("L", (1, size), 0)
    for y in range(size):
        a = int(90 * max(0.0, y / (size - 1) - 0.45) / 0.55)
        grad.putpixel((0, y), min(a, 90))
    mask = Image.new("L", (size, size), 0)
    mask.paste(grad.resize((size, size)), (0, 0))
    overlay = Image.new("RGBA", (size, size), BG_DARK)
    overlay.putalpha(mask)
    img.alpha_composite(overlay)

    # "TR" monogram, optically centered.
    try:
        font = ImageFont.truetype(FONT_BOLD, round(size * 0.52))
    except OSError:
        font = ImageFont.truetype(FONT_FALLBACK, round(size * 0.52))
    bbox = d.textbbox((0, 0), "TR", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1] - size * 0.01
    d.text((x, y), "TR", font=font, fill=FG)

    # 16 px legibility: hairline inner border keeps the square from melting.
    if size <= 32:
        d.rounded_rectangle([0, 0, size - 1, size - 1],
                            radius=round(RADIUS * s), outline=FG, width=1)
    return img


def main() -> None:
    frames = [build_one(sz) for sz in SIZES]
    frames[0].save(OUT, format="ICO", sizes=[(sz, sz) for sz in SIZES],
                   append_images=frames[1:])
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")


if __name__ == "__main__":
    main()
