"""Tests de l'étape 1 : détection texte / image et récupération incrémentale."""

from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from factures.detect import inspect_pdf
from factures.fetch import fetch


def _text_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "FACTURE N° A-2025-0001 Total TTC 1 234,56 EUR Client Dupont SARL")
    doc.save(path)
    return path


def _image_pdf(path: Path) -> Path:
    """PDF « scanné » : une page qui ne contient qu'une image (rendu d'une page texte)."""
    src = pymupdf.open(_text_pdf(path.with_name("src.pdf")))
    pix = src[0].get_pixmap(dpi=72)
    doc = pymupdf.open()
    doc.new_page().insert_image(doc[0].rect, pixmap=pix)
    doc.save(path)
    return path


def test_detect_text_pdf(tmp_path):
    info = inspect_pdf(_text_pdf(tmp_path / "a.pdf"))
    assert info.kind == "texte" and not info.needs_ocr


def test_detect_image_pdf(tmp_path):
    info = inspect_pdf(_image_pdf(tmp_path / "b.pdf"))
    assert info.kind == "image" and info.needs_ocr and info.images == 1


class FakeS3:
    """Bucket S3 en mémoire, avec la même interface que le client boto3 utilisé."""

    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.downloads = 0

    def get_paginator(self, _name):
        return self

    def paginate(self, Bucket):
        yield {
            "Contents": [
                {"Key": k, "ETag": f'"{hash(v)}"', "Size": len(v), "LastModified": datetime.now(timezone.utc)}
                for k, v in self.objects.items()
            ]
        }

    def download_file(self, bucket, key, filename):
        self.downloads += 1
        Path(filename).write_bytes(self.objects[key])


def test_fetch_is_incremental(tmp_path):
    s3 = FakeS3({"f1.pdf": b"%PDF-1", "f2.pdf": b"%PDF-2", "notes.txt": b"x"})
    first = fetch("b", tmp_path, s3)
    assert sorted(first.downloaded) == ["f1.pdf", "f2.pdf"]  # les non-PDF sont ignorés

    second = fetch("b", tmp_path, s3)
    assert second.downloaded == [] and s3.downloads == 2

    s3.objects["f1.pdf"] = b"%PDF-1 corrigee"  # même nom, contenu différent → re-téléchargé
    third = fetch("b", tmp_path, s3)
    assert third.downloaded == ["f1.pdf"]
