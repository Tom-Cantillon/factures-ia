"""Étape 2 : OCR d'une page de PDF.

Le reste du pipeline ne dépend que de l'interface `OcrEngine` (une image PNG en entrée, du texte en
sortie). Changer de fournisseur = écrire une autre classe qui la respecte et la choisir par la
variable d'environnement OCR_ENGINE, sans toucher au reste du code.

LightOnOCR-3 (fiche du modèle, https://huggingface.co/lightonai/LightOnOCR-3-1B) :
- un seul message `user` contenant uniquement l'image en data-URI PNG, sans texte : le prompt vide
  déclenche la transcription en markdown (un texte libre est « hors distribution ») ;
- rendu recommandé : plus grand côté ≈ 1540 px, en conservant le ratio ;
- paramètres recommandés : temperature 0.2, top_p 0.9, max_tokens 4096.
"""

import base64
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pymupdf

DEFAULT_LONGEST_SIDE = 1540


@dataclass
class OcrResult:
    text: str
    engine: str
    model: str
    seconds: float
    params: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


class OcrEngine(Protocol):
    name: str

    def ocr_png(self, png: bytes) -> OcrResult: ...


def render_page(pdf_path: Path, page: int = 0, longest_side: int = DEFAULT_LONGEST_SIDE) -> bytes:
    """Rend une page en PNG, redimensionnée pour que son plus grand côté fasse `longest_side` pixels."""
    with pymupdf.open(pdf_path) as doc:
        p = doc[page]
        scale = longest_side / max(p.rect.width, p.rect.height)
        pix = p.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")


class LightOnOcr:
    """LightOnOCR-3 servi par vLLM derrière une API compatible OpenAI (AI Gateway Hyperfluid)."""

    name = "lightonocr"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0,
                 max_tokens: int = 4096, temperature: float = 0.2, top_p: float = 0.9):
        from openai import OpenAI

        # max_retries=0 : la stratégie de reprise est gérée par le pipeline (étape 3), pas cachée ici.
        self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        self.model = model
        self.params = {"max_tokens": max_tokens, "temperature": temperature, "top_p": top_p}

    def ocr_png(self, png: bytes) -> OcrResult:
        data_uri = "data:image/png;base64," + base64.b64encode(png).decode()
        start = time.perf_counter()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_uri}}]}],
            **self.params,
        )
        seconds = time.perf_counter() - start
        usage = resp.usage.model_dump() if resp.usage else {}
        return OcrResult(
            text=resp.choices[0].message.content or "",
            engine=self.name,
            model=self.model,
            seconds=seconds,
            params=dict(self.params),
            usage={k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")},
        )


def get_engine(name: str | None = None) -> OcrEngine:
    """Fabrique le moteur choisi par configuration (OCR_ENGINE, par défaut lightonocr)."""
    name = name or os.getenv("OCR_ENGINE", "lightonocr")
    if name == "lightonocr":
        return LightOnOcr(
            base_url=os.environ["OCR_BASE_URL"],
            api_key=os.environ["OCR_API_KEY"],
            model=os.getenv("OCR_MODEL", "lightonocr-3-1b-test"),
        )
    raise ValueError(f"Moteur OCR inconnu : {name!r}")
