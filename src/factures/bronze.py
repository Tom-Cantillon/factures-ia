"""Étape 3 : couche bronze — le texte brut extrait de chaque PDF, avec sa traçabilité.

Principes :
- **Append-only** : chaque exécution ajoute de nouveaux fichiers Parquet, n'en modifie ni n'en
  supprime jamais. La bronze est la mémoire de ce qui a été extrait, et comment : si le parseur
  silver change, on la relit sans refaire d'OCR (coûteux et non déterministe).
- **Incrémental** : un document est identifié par le SHA-256 de son contenu (pas par son nom).
  S'il est déjà dans `documents`, il n'est ni relu ni ré-OCRisé.
- **Tolérant aux pannes** : une erreur d'extraction est tracée dans `extraction_errors` et le
  document, absent de `documents`, sera retenté à la prochaine exécution. Après plusieurs échecs
  OCR consécutifs, le service est considéré indisponible et les appels suivants sont évités.

Tables (dossiers de fichiers Parquet sous data/bronze/) :
- documents/          une ligne par document extrait avec succès
- extraction_errors/  une ligne par échec (journal, append-only)
"""

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf

from factures import __version__, config
from factures.detect import inspect_pdf
from factures.fetch import _sha256, load_manifest
from factures.ocr import DEFAULT_LONGEST_SIDE, OcrEngine, render_page

log = logging.getLogger(__name__)

DOCUMENTS = "documents"
ERRORS = "extraction_errors"

DOCUMENTS_SCHEMA = pa.schema([
    ("doc_id", pa.string()),                  # SHA-256 du PDF : identité du document
    ("file_name", pa.string()),
    ("s3_uri", pa.string()),
    ("s3_etag", pa.string()),
    ("size_bytes", pa.int64()),
    ("detected_kind", pa.string()),           # texte | image | mixte (étape 1)
    ("extraction_method", pa.string()),       # pdf_text | ocr | mixte
    ("page_count", pa.int32()),
    ("page_methods", pa.list_(pa.string())),  # méthode utilisée pour chaque page
    ("page_texts", pa.list_(pa.string())),    # texte brut de chaque page
    ("text", pa.string()),                    # pages concaténées
    ("ocr_engine", pa.string()),
    ("ocr_model", pa.string()),
    ("ocr_params", pa.string()),              # JSON : réglages exacts de l'appel
    ("image_longest_side", pa.int32()),
    ("ocr_prompt_tokens", pa.int64()),
    ("ocr_completion_tokens", pa.int64()),
    ("ocr_seconds", pa.float64()),
    ("extraction_seconds", pa.float64()),
    ("extracted_at", pa.timestamp("us", tz="UTC")),
    ("run_id", pa.string()),
    ("pipeline_version", pa.string()),
])

ERRORS_SCHEMA = pa.schema([
    ("doc_id", pa.string()),
    ("file_name", pa.string()),
    ("s3_uri", pa.string()),
    ("stage", pa.string()),                   # pdf | ocr
    ("error_type", pa.string()),
    ("error_message", pa.string()),
    ("attempts", pa.int32()),
    ("failed_at", pa.timestamp("us", tz="UTC")),
    ("run_id", pa.string()),
])

PAGE_SEPARATOR = "\n\n"
MAX_ATTEMPTS = 3              # tentatives par page en cas d'erreur transitoire
BREAKER_THRESHOLD = 3         # échecs OCR consécutifs avant de considérer le service indisponible
FLUSH_EVERY = 10              # documents par fichier Parquet (limite la perte en cas d'arrêt brutal)


class ExtractionError(Exception):
    def __init__(self, stage: str, attempts: int, cause: BaseException | str):
        self.stage, self.attempts, self.cause = stage, attempts, cause
        super().__init__(str(cause))


@dataclass
class IngestResult:
    run_id: str
    extracted: list[str] = field(default_factory=list)
    already_done: int = 0
    failed: list[str] = field(default_factory=list)
    ocr_calls: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _table_glob(bronze_dir: Path, table: str) -> str:
    return str(bronze_dir / table / "*.parquet")


def _has_files(bronze_dir: Path, table: str) -> bool:
    return any((bronze_dir / table).glob("*.parquet"))


def done_doc_ids(bronze_dir: Path) -> set[str]:
    if not _has_files(bronze_dir, DOCUMENTS):
        return set()
    rows = duckdb.execute("SELECT DISTINCT doc_id FROM read_parquet(?)", [_table_glob(bronze_dir, DOCUMENTS)])
    return {r[0] for r in rows.fetchall()}


def _write_part(bronze_dir: Path, table: str, rows: list[dict], schema: pa.Schema, run_id: str, part: int) -> None:
    if not rows:
        return
    out_dir = bronze_dir / table
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{run_id}-{part:04d}.parquet"
    tmp = final.with_suffix(".parquet.tmp")  # ignoré par le glob *.parquet tant qu'il n'est pas complet
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), tmp)
    tmp.replace(final)


def _is_retryable(exc: BaseException) -> bool:
    """Les erreurs d'authentification / de requête ne passeront pas mieux en réessayant."""
    try:
        import openai
    except ImportError:  # pragma: no cover
        return True
    return not isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError,
                                openai.BadRequestError, openai.NotFoundError))


class _Breaker:
    """Coupe-circuit : après N échecs OCR consécutifs, on arrête d'appeler le service pour ce run."""

    def __init__(self, threshold: int):
        self.threshold, self.failures, self.lock = threshold, 0, threading.Lock()

    @property
    def open(self) -> bool:
        return self.failures >= self.threshold

    def record(self, ok: bool) -> None:
        with self.lock:
            self.failures = 0 if ok else self.failures + 1


def _ocr_with_retry(engine: OcrEngine, png: bytes, breaker: _Breaker, backoff: float):
    last_exc: BaseException | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if breaker.open:
            # On garde la vraie dernière erreur si ce document a déjà été tenté.
            raise ExtractionError("ocr", attempt - 1, last_exc or "OCR indisponible (coupe-circuit ouvert) : non tenté")
        try:
            res = engine.ocr_png(png)
            breaker.record(True)
            return res, attempt
        except Exception as exc:  # noqa: BLE001 — toute erreur du fournisseur est tracée
            breaker.record(False)
            last_exc = exc
            if attempt == MAX_ATTEMPTS or not _is_retryable(exc):
                raise ExtractionError("ocr", attempt, exc) from exc
            log.warning("OCR échec (tentative %d/%d) : %s", attempt, MAX_ATTEMPTS, exc)
            time.sleep(backoff * 2 ** (attempt - 1))


def extract_document(path: Path, meta: dict, get_engine: Callable[[], OcrEngine], breaker: _Breaker,
                     run_id: str, longest_side: int, backoff: float = 1.0) -> tuple[dict, int]:
    """Extrait un PDF : couche texte native si elle existe, OCR sinon (page par page)."""
    start = time.perf_counter()
    try:
        info = inspect_pdf(path)
        with pymupdf.open(path) as doc:
            texts = [page.get_text() for page in doc]
    except Exception as exc:  # PDF illisible / corrompu
        raise ExtractionError("pdf", 1, exc) from exc

    methods = ["pdf_text" if k == "texte" else "ocr" for k in info.page_kinds]
    ocr_pages = [i for i, m in enumerate(methods) if m == "ocr"]
    engine = get_engine() if ocr_pages else None
    tokens_in = tokens_out = 0
    ocr_seconds, calls, ocr_params = 0.0, 0, None

    for i in ocr_pages:
        png = render_page(path, i, longest_side)
        res, attempts = _ocr_with_retry(engine, png, breaker, backoff)
        calls += attempts
        texts[i] = res.text
        tokens_in += res.usage.get("prompt_tokens") or 0
        tokens_out += res.usage.get("completion_tokens") or 0
        ocr_seconds += res.seconds
        ocr_params = res.params

    method = "pdf_text" if not ocr_pages else ("ocr" if len(ocr_pages) == len(methods) else "mixte")
    row = {
        "doc_id": meta["sha256"],
        "file_name": path.name,
        "s3_uri": meta.get("s3_uri"),
        "s3_etag": meta.get("etag"),
        "size_bytes": path.stat().st_size,
        "detected_kind": info.kind,
        "extraction_method": method,
        "page_count": info.pages,
        "page_methods": methods,
        "page_texts": texts,
        "text": PAGE_SEPARATOR.join(texts),
        "ocr_engine": engine.name if engine else None,
        "ocr_model": getattr(engine, "model", None) if engine else None,
        "ocr_params": json.dumps(ocr_params, sort_keys=True) if ocr_params else None,
        "image_longest_side": longest_side if ocr_pages else None,
        "ocr_prompt_tokens": tokens_in if ocr_pages else None,
        "ocr_completion_tokens": tokens_out if ocr_pages else None,
        "ocr_seconds": ocr_seconds if ocr_pages else None,
        "extraction_seconds": time.perf_counter() - start,
        "extracted_at": _now(),
        "run_id": run_id,
        "pipeline_version": __version__,
    }
    return row, calls


def ingest(get_engine: Callable[[], OcrEngine], landing_dir: Path = config.LANDING_DIR,
           bronze_dir: Path = config.BRONZE_DIR, limit: int | None = None, workers: int = 4,
           longest_side: int = DEFAULT_LONGEST_SIDE, backoff: float = 1.0) -> IngestResult:
    run_id = _now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    result = IngestResult(run_id=run_id)
    manifest = load_manifest(landing_dir)
    done = done_doc_ids(bronze_dir)

    # Planification : documents présents en landing et pas encore en bronze (dédoublonnés par contenu).
    todo, seen = [], set()
    for path in sorted(landing_dir.rglob("*.pdf")):
        key = path.relative_to(landing_dir).as_posix()
        meta = dict(manifest.get(key) or {})
        meta.setdefault("sha256", _sha256(path))
        if meta["sha256"] in done:
            result.already_done += 1
        elif meta["sha256"] in seen:
            log.warning("%s : contenu identique à un autre fichier de ce lot, ignoré", key)
        else:
            seen.add(meta["sha256"])
            todo.append((path, meta))
    if limit is not None:
        todo = todo[:limit]

    breaker = _Breaker(BREAKER_THRESHOLD)
    docs, errors, part = [], [], 0

    def flush(force: bool = False) -> None:
        nonlocal docs, errors, part
        if docs and (force or len(docs) >= FLUSH_EVERY):
            _write_part(bronze_dir, DOCUMENTS, docs, DOCUMENTS_SCHEMA, run_id, part)
            docs, part = [], part + 1
        if errors and force:
            _write_part(bronze_dir, ERRORS, errors, ERRORS_SCHEMA, run_id, part)
            errors, part = [], part + 1

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(extract_document, p, m, get_engine, breaker, run_id, longest_side, backoff): (p, m)
            for p, m in todo
        }
        for fut in as_completed(futures):  # un seul écrivain (ce thread) : pas d'écriture concurrente
            path, meta = futures[fut]
            try:
                row, calls = fut.result()
                result.ocr_calls += calls
                docs.append(row)
                result.extracted.append(path.name)
                log.info("ok  %s (%s, %.1fs)", path.name, row["extraction_method"], row["extraction_seconds"])
            except ExtractionError as err:
                if err.stage == "ocr":
                    result.ocr_calls += err.attempts
                errors.append({
                    "doc_id": meta["sha256"], "file_name": path.name, "s3_uri": meta.get("s3_uri"),
                    "stage": err.stage, "error_type": type(err.cause).__name__ if not isinstance(err.cause, str) else "Skipped",
                    "error_message": str(err.cause)[:1000], "attempts": err.attempts,
                    "failed_at": _now(), "run_id": run_id,
                })
                result.failed.append(path.name)
                log.error("ERR %s [%s] %s", path.name, err.stage, str(err.cause)[:200])
            flush()
    flush(force=True)
    return result
