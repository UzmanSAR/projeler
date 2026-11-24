"""DoechBots PWA ikonlarını üretir.

Kullanım:
    python3 make_icons.py              # geçici "DB" monogramlı ikonlar
    python3 make_icons.py logo.png     # kendi logondan (kare, en az 512x512, şeffaf zemin olabilir)

Çıktı: icons/ klasörü (icon-192, icon-512, maskable-512, apple-touch-icon, favicon-32).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (15, 17, 21)        # #0f1115, manifest'teki background_color ile aynı
ACCENT = (245, 184, 61)  # #f5b83d
OUT = Path(__file__).parent / "icons"


def monogram(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    draw = ImageDraw.Draw(img)
    font = None
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            font = ImageFont.truetype(name, int(size * 0.42))
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    draw.text((size / 2, size / 2), "DB", fill=ACCENT, font=font, anchor="mm")
    return img


def from_logo(path: str, size: int) -> Image.Image:
    logo = Image.open(path).convert("RGBA")
    logo.thumbnail((size, size), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), BG)
    img.alpha_composite(logo, ((size - logo.width) // 2, (size - logo.height) // 2))
    return img


def make(size: int, logo: str | None, safe: float = 1.0) -> Image.Image:
    """safe < 1: içerik ortadaki güvenli alana küçültülür (maskable ikon için %80)."""
    inner = int(size * safe)
    art = from_logo(logo, inner) if logo else monogram(inner)
    img = Image.new("RGBA", (size, size), BG)
    img.alpha_composite(art, ((size - inner) // 2, (size - inner) // 2))
    return img


def main() -> None:
    logo = sys.argv[1] if len(sys.argv) > 1 else None
    OUT.mkdir(exist_ok=True)
    make(192, logo).save(OUT / "icon-192.png")
    make(512, logo).save(OUT / "icon-512.png")
    make(512, logo, safe=0.8).save(OUT / "maskable-512.png")
    make(180, logo).convert("RGB").save(OUT / "apple-touch-icon.png")   # iOS saydamlığı siyaha çevirir
    make(32, logo).save(OUT / "favicon-32.png")
    print("İkonlar yazıldı:", OUT)


if __name__ == "__main__":
    main()
