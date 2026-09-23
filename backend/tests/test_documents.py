import zipfile
import shutil
import pytest
from PIL import Image
from app.documents import convert_sources, validate_source
from app.images import ImageValidationError, enhance_image
from app.control import JobControl
from app.config import settings
from docx import Document


def test_pdf_pages_to_png_zip(tmp_path):
    source = tmp_path / "source.pdf"
    Image.new("RGB", (64, 48), "red").save(source, "PDF")
    validate_source(source)
    output = tmp_path / "pages.zip"
    convert_sources([source], output, "png", lambda _: None, JobControl("test"))
    with zipfile.ZipFile(output) as archive:
        assert len(archive.namelist()) == 1
        assert archive.read(archive.namelist()[0]).startswith(b"\x89PNG")


def test_docx_rejects_external_content(tmp_path):
    source = tmp_path / "linked.docx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/_rels/document.xml.rels", '<Relationships><Relationship TargetMode="External" Target="http://localhost"/></Relationships>')
    with pytest.raises(ImageValidationError, match="external"):
        validate_source(source)


def test_upscale_memory_guard(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100)).save(source)
    monkeypatch.setattr(settings, "max_image_pixels", 20_000)
    with pytest.raises(ImageValidationError, match="smaller scale"):
        enhance_image(source, tmp_path / "out.png", 4, "natural", "png", lambda _: None)


@pytest.mark.skipif(not (shutil.which("libreoffice") or shutil.which("soffice")), reason="LibreOffice is installed in Docker and CI")
def test_docx_to_pdf(tmp_path):
    source = tmp_path / "sample.docx"
    document = Document()
    document.add_paragraph("Media Forge test document")
    document.save(source)
    validate_source(source)
    output = tmp_path / "converted.pdf"
    convert_sources([source], output, "pdf", lambda _: None, JobControl("docx-test"))
    assert output.read_bytes().startswith(b"%PDF")
