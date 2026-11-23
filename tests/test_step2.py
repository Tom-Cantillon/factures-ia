"""Tests de l'étape 2 : rendu des pages et format de la requête OCR (sans appel réseau)."""

import base64
import io
from types import SimpleNamespace

import pymupdf
import pytest

from factures.ocr import LightOnOcr, get_engine, render_page


def _pdf(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_text((72, 72), "FACTURE")  # A4 portrait
    path = tmp_path / "a.pdf"
    doc.save(path)
    return path


def test_render_page_respects_longest_side(tmp_path):
    png = render_page(_pdf(tmp_path), longest_side=1540)
    pix = pymupdf.Pixmap(io.BytesIO(png).read())
    assert max(pix.width, pix.height) == pytest.approx(1540, abs=1)
    assert pix.height > pix.width  # le ratio est conservé


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="# FACTURE"))],
            usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 3}),
        )


def test_lightonocr_request_follows_model_card(tmp_path):
    engine = LightOnOcr(base_url="http://x/v1", api_key="test", model="m")
    fake = FakeCompletions()
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))

    png = render_page(_pdf(tmp_path), longest_side=200)
    res = engine.ocr_png(png)

    assert res.text == "# FACTURE" and res.usage == {"prompt_tokens": 10, "completion_tokens": 3}
    (msg,) = fake.kwargs["messages"]
    assert msg["role"] == "user"
    (part,) = msg["content"]  # l'image seule, pas de prompt texte
    assert part["type"] == "image_url"
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,") and base64.b64decode(url.split(",", 1)[1]) == png
    assert fake.kwargs["temperature"] == 0.2 and fake.kwargs["top_p"] == 0.9


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError):
        get_engine("inexistant")
