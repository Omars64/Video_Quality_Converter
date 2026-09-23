"""Bounded PDF/DOCX page conversion. DOCX output is intentionally image-based."""
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pypdfium2 as pdfium

from .config import settings
from .control import run_managed_process
from .images import ImageValidationError, convert_images, probe_image


def validate_source(path: Path):
    if path.suffix.lower() == ".pdf":
        try:
            with pdfium.PdfDocument(path) as document:
                if not 0 < len(document) <= settings.max_document_pages:
                    raise ImageValidationError(f"Use a PDF with 1–{settings.max_document_pages} pages.")
        except pdfium.PdfiumError as exc:
            raise ImageValidationError("PDF is unreadable or password protected.") from exc
    elif path.suffix.lower() == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    raise ImageValidationError("Expanded document exceeds 50 MB.")
                if "word/document.xml" not in archive.namelist():
                    raise ImageValidationError("Not a valid DOCX document.")
                for name in archive.namelist():
                    if name.endswith(".rels"):
                        root = ElementTree.fromstring(archive.read(name))
                        if any(item.get("TargetMode") == "External" for item in root):
                            raise ImageValidationError("Remove external links and linked files before converting this document.")
                    if "vbaproject" in name.lower() or "embeddings/" in name.lower():
                        raise ImageValidationError("Embedded programs are not supported.")
        except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ImageValidationError("DOCX is unreadable.") from exc
    else:
        probe_image(path)


def convert_sources(paths, output, output_format, progress, control):
    with tempfile.TemporaryDirectory(prefix="mediaforge-pages-") as folder:
        directory = Path(folder)
        images = []
        for index, original in enumerate(paths):
            control.check()
            path = original
            if path.suffix.lower() == ".docx":
                executable = shutil.which("libreoffice") or shutil.which("soffice")
                if not executable:
                    raise ImageValidationError("DOCX input needs LibreOffice on the processing server.")
                proc = run_managed_process([
                    executable, f"-env:UserInstallation={(directory / 'profile').as_uri()}",
                    "--headless", "--convert-to", "pdf", "--outdir", str(directory), str(path),
                ], control)
                try:
                    proc.communicate(timeout=120)
                except subprocess.TimeoutExpired as exc:
                    control.stop()
                    raise ImageValidationError("Document conversion timed out. Try a smaller document.") from exc
                finally:
                    control.unregister_process(proc)
                control.check()
                path = directory / f"{original.stem}.pdf"
                if proc.returncode or not path.exists():
                    raise ImageValidationError("This DOCX document could not be converted.")
            if path.suffix.lower() == ".pdf":
                validate_source(path)
                with pdfium.PdfDocument(path) as document:
                    for page_number in range(len(document)):
                        control.check()
                        page = document[page_number]
                        try:
                            width, height = page.get_size()
                            scale = min(1.5, (settings.max_image_pixels / max(1, width * height)) ** 0.5)
                            bitmap = page.render(scale=scale)
                            try:
                                image = bitmap.to_pil()
                                destination = directory / f"{index + 1}-page-{page_number + 1}.png"
                                image.save(destination)
                                image.close()
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
                        images.append(destination)
                        if len(images) > settings.max_document_pages:
                            raise ImageValidationError("Too many pages. Convert fewer documents at once.")
            else:
                images.append(path)
            progress(20 * (index + 1) / len(paths))
        convert_images(images, output, output_format, lambda value: progress(20 + value * 0.8))
