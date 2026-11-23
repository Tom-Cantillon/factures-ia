"""Étape 1 : récupération incrémentale des factures du bucket S3 vers la zone d'arrivée (landing).

Un objet est considéré « déjà vu » si le manifeste local contient la même clé avec le même ETag
(empreinte calculée par S3). Le nom seul ne suffit pas : un fichier peut être remplacé sous le même nom.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import boto3

from factures import config

MANIFEST_NAME = "_manifest.json"


@dataclass
class FetchResult:
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(landing_dir: Path) -> dict:
    path = landing_dir / MANIFEST_NAME
    return json.loads(path.read_text()) if path.exists() else {}


def _save_manifest(landing_dir: Path, manifest: dict) -> None:
    tmp = landing_dir / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.replace(landing_dir / MANIFEST_NAME)


def fetch(bucket: str = config.S3_BUCKET, landing_dir: Path = config.LANDING_DIR, s3=None) -> FetchResult:
    """Télécharge les PDF nouveaux ou modifiés du bucket. Relancer ne retélécharge rien."""
    s3 = s3 or boto3.client("s3")
    landing_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(landing_dir)
    result = FetchResult()

    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key, etag = obj["Key"], obj["ETag"].strip('"')
            if not key.lower().endswith(".pdf"):
                continue
            local = landing_dir / key
            known = manifest.get(key)
            if known and known["etag"] == etag and local.exists():
                result.skipped.append(key)
                continue

            local.parent.mkdir(parents=True, exist_ok=True)
            tmp = local.with_suffix(local.suffix + ".part")
            s3.download_file(bucket, key, str(tmp))
            tmp.replace(local)  # écriture atomique : jamais de PDF à moitié téléchargé

            manifest[key] = {
                "s3_uri": f"s3://{bucket}/{key}",
                "etag": etag,
                "size": obj["Size"],
                "s3_last_modified": obj["LastModified"].isoformat(),
                "sha256": _sha256(local),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_manifest(landing_dir, manifest)
            result.downloaded.append(key)

    return result
