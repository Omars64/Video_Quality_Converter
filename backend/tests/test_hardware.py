from app.hardware import detect_hardware


def test_hardware_shape():
    data = detect_hardware(refresh=True)
    assert "recommendedEngine" in data
    assert data["recommendedEngine"] in {"cpu", "nvidia", "qsv"}
    assert isinstance(data["engines"], list)
    assert any(item["value"] == "cpu" for item in data["engines"])
