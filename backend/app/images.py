import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from docx import Document
from docx.shared import Inches
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, UnidentifiedImageError


class ImageValidationError(ValueError):
    pass


FORMAT_EXTENSIONS = {
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "bmp": ".bmp",
    "tiff": ".tiff",
    "pdf": ".pdf",
    "docx": ".docx",
}

FORMAT_MIMES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _load_image(path: Path) -> Image.Image:
    try:
        image = Image.open(path)
        image.load()
        return ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError(f"{path.name} is not a readable image.") from exc


def probe_image(path: Path) -> dict[str, int | str]:
    image = _load_image(path)
    try:
        return {"width": image.width, "height": image.height, "format": image.format or path.suffix.lstrip(".")}
    finally:
        image.close()


def _rgb_with_alpha(image: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    alpha = image.getchannel("A") if "A" in image.getbands() else None
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if alpha is not None else "RGB")
    rgb = image.convert("RGB")
    return rgb, alpha


def enhance_image(
    input_path: Path,
    output_path: Path,
    scale: int,
    strength: str,
    output_format: str,
    on_progress: Callable[[float], None],
) -> None:
    if scale not in {1, 2, 4}:
        raise ValueError("Image scale must be 1x, 2x, or 4x.")
    if strength not in {"natural", "strong"}:
        raise ValueError("Photo enhancement strength must be natural or strong.")
    if output_format not in {"jpg", "png", "webp"}:
        raise ValueError("Enhanced photos can be exported as JPG, PNG, or WebP.")

    image = _load_image(input_path)
    try:
        rgb, alpha = _rgb_with_alpha(image)
        on_progress(15)
        if scale > 1:
            rgb = rgb.resize((rgb.width * scale, rgb.height * scale), Image.Resampling.LANCZOS)
            if alpha is not None:
                alpha = alpha.resize(rgb.size, Image.Resampling.LANCZOS)
        on_progress(42)

        if strength == "strong":
            rgb = rgb.filter(ImageFilter.MedianFilter(size=3))
            rgb = ImageOps.autocontrast(rgb, cutoff=0.5)
            rgb = ImageEnhance.Contrast(rgb).enhance(1.06)
            rgb = ImageEnhance.Color(rgb).enhance(1.05)
            rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.8, percent=155, threshold=3))
        else:
            rgb = ImageOps.autocontrast(rgb, cutoff=0.25)
            rgb = ImageEnhance.Contrast(rgb).enhance(1.025)
            rgb = ImageEnhance.Color(rgb).enhance(1.02)
            rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.35, percent=120, threshold=3))
        on_progress(78)

        if output_format == "png" and alpha is not None:
            result = rgb.convert("RGBA")
            result.putalpha(alpha)
            result.save(output_path, format="PNG", optimize=True)
        elif output_format == "webp":
            if alpha is not None:
                result = rgb.convert("RGBA")
                result.putalpha(alpha)
            else:
                result = rgb
            result.save(output_path, format="WEBP", quality=93, method=6)
        else:
            rgb.save(output_path, format="JPEG", quality=94, optimize=True, progressive=True)
        on_progress(100)
    finally:
        image.close()


def _save_image_as(image: Image.Image, output_path: Path, output_format: str) -> None:
    fmt = "JPEG" if output_format in {"jpg", "jpeg"} else output_format.upper()
    working = ImageOps.exif_transpose(image)
    if output_format in {"jpg", "jpeg", "bmp"} and working.mode not in {"RGB", "L"}:
        background = Image.new("RGB", working.size, "white")
        if "A" in working.getbands():
            background.paste(working.convert("RGBA"), mask=working.getchannel("A"))
        else:
            background.paste(working.convert("RGB"))
        working = background
    options = {}
    if output_format in {"jpg", "jpeg"}:
        options = {"quality": 94, "optimize": True, "progressive": True}
    elif output_format == "webp":
        options = {"quality": 93, "method": 6}
    elif output_format == "png":
        options = {"optimize": True}
    working.save(output_path, format=fmt, **options)


def _images_to_pdf(paths: list[Path], output_path: Path, on_progress: Callable[[float], None]) -> None:
    pages: list[Image.Image] = []
    try:
        for index, path in enumerate(paths):
            image = _load_image(path)
            page = image.convert("RGB")
            pages.append(page)
            image.close()
            on_progress(10 + (index + 1) / len(paths) * 65)
        if not pages:
            raise ImageValidationError("No images were supplied.")
        pages[0].save(output_path, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
        on_progress(100)
    finally:
        for page in pages:
            page.close()


def _images_to_docx(paths: list[Path], output_path: Path, on_progress: Callable[[float], None]) -> None:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.45)
    section.bottom_margin = Inches(0.45)
    section.left_margin = Inches(0.45)
    section.right_margin = Inches(0.45)
    max_width = 7.6
    max_height = 10.1

    with tempfile.TemporaryDirectory(prefix="mediaforge-docx-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        for index, path in enumerate(paths):
            image = _load_image(path)
            try:
                width_px, height_px = image.size
                ratio = width_px / height_px if height_px else 1
                page_width = max_width
                page_height = page_width / ratio
                if page_height > max_height:
                    page_height = max_height
                    page_width = page_height * ratio

                insert_path = path
                if image.format not in {"JPEG", "PNG", "GIF", "BMP", "TIFF"}:
                    insert_path = temp_dir_path / f"page-{index + 1}.png"
                    image.convert("RGBA" if "A" in image.getbands() else "RGB").save(insert_path, "PNG")
                document.add_picture(str(insert_path), width=Inches(page_width), height=Inches(page_height))
                if index < len(paths) - 1:
                    document.add_page_break()
            finally:
                image.close()
            on_progress(10 + (index + 1) / len(paths) * 75)
        document.save(output_path)
        on_progress(100)


def convert_images(
    input_paths: list[Path],
    output_path: Path,
    output_format: str,
    on_progress: Callable[[float], None],
) -> None:
    output_format = output_format.lower()
    if output_format not in FORMAT_EXTENSIONS:
        raise ValueError("Unsupported image output format.")
    if not input_paths:
        raise ImageValidationError("Choose at least one image.")

    if output_format == "pdf":
        _images_to_pdf(input_paths, output_path, on_progress)
        return
    if output_format == "docx":
        _images_to_docx(input_paths, output_path, on_progress)
        return

    if len(input_paths) == 1:
        image = _load_image(input_paths[0])
        try:
            _save_image_as(image, output_path, output_format)
        finally:
            image.close()
        on_progress(100)
        return

    # Multiple image-to-image conversions are delivered as a ZIP archive.
    with tempfile.TemporaryDirectory(prefix="mediaforge-convert-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        converted: list[Path] = []
        for index, input_path in enumerate(input_paths):
            image = _load_image(input_path)
            try:
                destination = temp_dir_path / f"{input_path.stem}{FORMAT_EXTENSIONS[output_format]}"
                counter = 2
                while destination.exists():
                    destination = temp_dir_path / f"{input_path.stem}-{counter}{FORMAT_EXTENSIONS[output_format]}"
                    counter += 1
                _save_image_as(image, destination, output_format)
                converted.append(destination)
            finally:
                image.close()
            on_progress(5 + (index + 1) / len(input_paths) * 80)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in converted:
                archive.write(path, arcname=path.name)
        on_progress(100)
