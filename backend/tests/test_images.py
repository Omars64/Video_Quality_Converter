from pathlib import Path

from PIL import Image

from app.images import convert_images, enhance_image


def _make_image(path: Path, size=(64, 48), color=(120, 80, 60)):
    Image.new("RGB", size, color).save(path)


def test_enhance_image(tmp_path):
    source = tmp_path / "source.jpg"
    output = tmp_path / "enhanced.png"
    _make_image(source)
    progress = []
    enhance_image(source, output, scale=2, strength="natural", output_format="png", on_progress=progress.append)
    assert output.exists()
    with Image.open(output) as image:
        assert image.size == (128, 96)
    assert progress[-1] == 100


def test_merge_images_to_pdf(tmp_path):
    first = tmp_path / "one.jpg"
    second = tmp_path / "two.png"
    output = tmp_path / "merged.pdf"
    _make_image(first)
    _make_image(second, color=(50, 140, 90))
    convert_images([first, second], output, "pdf", lambda _: None)
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_merge_images_to_docx(tmp_path):
    first = tmp_path / "one.jpg"
    second = tmp_path / "two.png"
    output = tmp_path / "merged.docx"
    _make_image(first)
    _make_image(second)
    convert_images([first, second], output, "docx", lambda _: None)
    assert output.exists()
    assert output.read_bytes().startswith(b"PK")
