"""Étape 1 : un PDF a-t-il une couche texte exploitable, ou faut-il de l'OCR ?

La décision se fait page par page, sur le contenu du PDF (jamais sur son nom) :
une page est « texte » si sa couche texte contient assez de caractères alphanumériques.
Un document est « texte » si toutes ses pages le sont, « image » si aucune, sinon « mixte ».
"""

from dataclasses import dataclass
from pathlib import Path

import pymupdf

# Une page scannée peut contenir quelques caractères parasites (tampon, n° de page ajouté par le
# scanner) ; une vraie facture native en a des centaines. Le seuil est volontairement bas.
MIN_CHARS_PER_PAGE = 30


@dataclass
class PdfInfo:
    path: Path
    pages: int
    chars_per_page: list[int]
    images: int
    page_kinds: list[str]

    @property
    def kind(self) -> str:
        kinds = set(self.page_kinds)
        if kinds == {"texte"}:
            return "texte"
        if kinds == {"image"} or not kinds:
            return "image"
        return "mixte"

    @property
    def needs_ocr(self) -> bool:
        return self.kind != "texte"


def inspect_pdf(path: Path, min_chars: int = MIN_CHARS_PER_PAGE) -> PdfInfo:
    with pymupdf.open(path) as doc:
        chars, images = [], 0
        for page in doc:
            text = page.get_text()
            chars.append(sum(c.isalnum() for c in text))
            images += len(page.get_images())
    return PdfInfo(
        path=path,
        pages=len(chars),
        chars_per_page=chars,
        images=images,
        page_kinds=["texte" if n >= min_chars else "image" for n in chars],
    )
