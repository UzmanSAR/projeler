"""Model fotoğrafları: telefondan gelen fotoğraf küçültülür, yönü düzeltilir, konum ve cihaz bilgisi
(EXIF) silinir ve WebP olarak veritabanına yazılır. Ayrı bir dosya deposu gerekmez; Render'ın diski
her yayında sıfırlandığı için fotoğraflar diskte tutulmaz."""
import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 15 * 1024 * 1024        # telefon fotoğrafları 3-8 MB olur
FULL_SIDE, THUMB_SIDE = 1400, 520    # uzun kenar (px)
Image.MAX_IMAGE_PIXELS = 60_000_000  # sıkıştırma bombasına karşı üst sınır
ALLOWED = {"JPEG", "PNG", "WEBP", "MPO"}   # MPO: bazı telefonların JPEG'i


class ImageError(ValueError):
    pass


def _encode(img, side, quality):
    img = img.copy()
    img.thumbnail((side, side), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=quality, method=6)
    return out.getvalue(), img.size


def process(upload):
    """Yüklenen dosyadan (tam boy, küçük resim, genişlik, yükseklik, özet) döndürür."""
    if upload.size > MAX_UPLOAD:
        raise ImageError("Fotoğraf çok büyük (en fazla 15 MB).")
    try:
        img = Image.open(upload)
        if img.format not in ALLOWED:
            raise ImageError("Bu dosya türü desteklenmiyor. JPEG, PNG ya da WebP fotoğraf seçin.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("Fotoğraf okunamadı. Başka bir fotoğraf deneyin.")
    img = ImageOps.exif_transpose(img)          # telefonda yan çekilmiş fotoğraf dik dursun
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if img.mode == "RGBA":                       # saydam PNG: açık zemine oturt
        base = Image.new("RGB", img.size, (246, 244, 240))
        base.paste(img, mask=img.getchannel("A"))
        img = base
    if min(img.size) < 200:
        raise ImageError("Fotoğraf çok küçük. En az 200 piksel olmalı.")
    full, size = _encode(img, FULL_SIDE, 80)     # yeni dosyada EXIF yok: konum bilgisi gitmiş olur
    thumb, _ = _encode(img, THUMB_SIDE, 76)
    return full, thumb, size[0], size[1], hashlib.sha1(full).hexdigest()[:12]


def apply(style, upload):
    style.image, style.thumb, style.width, style.height, style.digest = process(upload)
