"""Étape 5 : mesurer la qualité de l'OCR, champ par champ, contre une vérité terrain.

Deux jeux d'évaluation :
- **réel** (`eval/ground_truth.json`) : un échantillon de vrais scans dont les valeurs exactes ont été
  vérifiées à la main sur l'image (voir eval/README.md pour la méthode) ;
- **synthétique** : les PDF *natifs* rendus en image puis dégradés (rotation, flou, bruit, JPEG) pour
  imiter un scan. Leur vérité terrain est exacte et gratuite : c'est la couche texte du PDF.

Réglages comparés :
- `silver` : ce que contient réellement la couche silver (pipeline de production) ;
- `ocr-<N>px` : ré-OCR de l'échantillon avec une image de N pixels de plus grand côté. Les sorties
  sont mises en cache dans data/eval/ (jamais dans la bronze : ce sont des essais, pas la production).
"""

import io
import json
import random
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from factures import config
from factures.ocr import render_page
from factures.parser import parse_amount, parse_date, parse_invoice, parse_rate

EVAL_DIR = config.PROJECT_ROOT / "eval"
TRUTH_PATH = EVAL_DIR / "ground_truth.json"
CACHE_DIR = config.DATA_DIR / "eval"

FIELDS = [
    "invoice_number", "issue_date", "due_date", "supplier_name", "supplier_siret", "supplier_vat_number",
    "client_name", "client_siret", "category", "status", "payment_method", "iban",
    "total_ht", "total_tva", "total_ttc", "line_count", "lines",
]
MONEY_FIELDS = {"total_ht", "total_tva", "total_ttc"}
LINE_KEYS = ["description", "quantity", "unit_price_ht", "vat_rate", "line_total_ht"]


# --------------------------------------------------------------------------- normalisation commune

def _s(v) -> str | None:
    """Représentation canonique d'une valeur pour la comparaison (Decimal sans zéros inutiles, date ISO)."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, date):
        return v.isoformat()
    return " ".join(str(v).split())


def fields_from_text(text: str) -> dict:
    """Champs évalués, extraits d'un texte brut avec le même parseur que la silver."""
    p = parse_invoice(text)
    f = p.fields
    out = {k: _s(f.get(k)) for k in FIELDS if k not in MONEY_FIELDS | {"issue_date", "due_date", "line_count", "lines"}}
    out.update({k: _s(parse_amount(f.get(k))) for k in MONEY_FIELDS})
    out["issue_date"] = _s(parse_date(f.get("issue_date")))
    out["due_date"] = _s(parse_date(f.get("due_date")))
    out["line_count"] = str(len(p.lines))
    out["lines"] = [
        {"description": _s(ln.description), "quantity": _s(ln.quantity), "unit_price_ht": _s(ln.unit_price_ht),
         "vat_rate": _s(ln.vat_rate), "line_total_ht": _s(ln.line_total_ht)}
        for ln in p.lines
    ]
    return out


def fields_from_silver(file_names: list[str], silver_dir: Path = config.SILVER_DIR) -> dict[str, dict]:
    con = duckdb.connect()
    inv = con.execute(
        f"SELECT * FROM read_parquet('{silver_dir / 'invoices' / 'data.parquet'}') WHERE file_name IN "
        f"(SELECT unnest(?::VARCHAR[]))", [file_names]
    )
    cols = [c[0] for c in inv.description]
    out = {}
    for row in inv.fetchall():
        r = dict(zip(cols, row))
        lines = con.execute(
            f"SELECT {', '.join(LINE_KEYS)} FROM read_parquet('{silver_dir / 'invoice_lines' / 'data.parquet'}') "
            "WHERE invoice_id = ? ORDER BY line_no", [r["invoice_id"]]
        ).fetchall()
        d = {k: _s(r.get(k)) for k in FIELDS if k not in {"lines", "line_count"}}
        d["line_count"] = str(r["line_count"])
        d["lines"] = [dict(zip(LINE_KEYS, map(_s, ln))) for ln in lines]
        out[r["file_name"]] = d
    return out


def compare(pred: dict | None, truth: dict) -> dict[str, bool]:
    """Exactitude champ par champ. Une facture absente de la prédiction compte faux partout."""
    if pred is None:
        return {k: False for k in FIELDS}
    truth = {**truth, "line_count": truth.get("line_count") or str(len(truth["lines"]))}
    res = {}
    for k in FIELDS:
        if k == "lines":
            res[k] = pred.get("lines") == [{lk: _s(_typed(lk, ln.get(lk))) for lk in LINE_KEYS} for ln in truth["lines"]]
        else:
            res[k] = pred.get(k) == _s(_typed(k, truth.get(k)))
    return res


def _typed(key: str, v):
    """La vérité terrain est en JSON (chaînes) : on la ramène au même type que la prédiction."""
    if v is None:
        return None
    if key in MONEY_FIELDS | {"quantity", "unit_price_ht", "line_total_ht"}:
        return Decimal(str(v))
    if key == "vat_rate":
        return Decimal(str(v))
    return v


# --------------------------------------------------------------------------- jeux d'évaluation

def load_truth(path: Path = TRUTH_PATH) -> dict[str, dict]:
    data = json.loads(path.read_text())
    return {k: v for k, v in data["invoices"].items() if v.get("verified")}


def sample_scans(n: int, seed: int = 42, landing_dir: Path = config.LANDING_DIR) -> list[str]:
    """Échantillon reproductible de scans, réparti entre fournisseurs (préfixe du numéro)."""
    scans = sorted(p.name for p in landing_dir.glob("*_scan.pdf"))
    by_supplier: dict[str, list[str]] = {}
    for s in scans:
        by_supplier.setdefault(s.split("_")[1].split("-")[0], []).append(s)
    rng = random.Random(seed)
    for files in by_supplier.values():
        rng.shuffle(files)
    picked, i = [], 0
    while len(picked) < min(n, len(scans)):  # tourniquet entre fournisseurs
        for files in by_supplier.values():
            if i < len(files) and len(picked) < n:
                picked.append(files[i])
        i += 1
    return sorted(picked)


def degrade(png: bytes, seed: int) -> bytes:
    """Transforme le rendu propre d'un PDF natif en « faux scan » (gris, rotation, flou, bruit, JPEG)."""
    from PIL import Image, ImageFilter

    rng = random.Random(seed)
    img = Image.open(io.BytesIO(png)).convert("L")
    img = img.rotate(rng.uniform(-1.5, 1.5), resample=Image.BICUBIC, expand=False, fillcolor=245)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
    # Bruit tiré du générateur avec graine (Image.effect_noise a son propre aléa, non reproductible).
    noise = Image.frombytes("L", img.size, rng.randbytes(img.size[0] * img.size[1]))
    img = Image.blend(img, noise, rng.uniform(0.05, 0.10))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(55, 75))
    out = io.BytesIO()
    Image.open(io.BytesIO(buf.getvalue())).save(out, "PNG")
    return out.getvalue()


# --------------------------------------------------------------------------- OCR avec cache

@dataclass
class OcrRun:
    text: str
    seconds: float


def ocr_cached(engine, pdf: Path, longest_side: int, synthetic: bool = False) -> OcrRun:
    tag = f"{'synth' if synthetic else 'real'}-{engine.name}-{getattr(engine, 'model', '')}-{longest_side}px"
    out = CACHE_DIR / tag / (pdf.stem + ".json")
    if out.exists():
        d = json.loads(out.read_text())
        return OcrRun(d["text"], d["seconds"])
    png = render_page(pdf, 0, longest_side)
    if synthetic:
        png = degrade(png, seed=zlib.crc32(pdf.name.encode()))  # hash() varie d'un processus à l'autre
    start = time.perf_counter()
    res = engine.ocr_png(png)
    run = OcrRun(res.text, time.perf_counter() - start)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"text": run.text, "seconds": run.seconds, "params": res.params}))
    return run


# --------------------------------------------------------------------------- évaluation

@dataclass
class SettingResult:
    name: str
    n: int
    per_field: dict[str, float]
    docs_all_correct: int
    seconds_per_page: float | None
    errors: list[tuple[str, str, object, object]]  # (fichier, champ, prédit, attendu)


def score(name: str, preds: dict[str, dict | None], truth: dict[str, dict], secs: list[float] | None) -> SettingResult:
    per = {k: 0 for k in FIELDS}
    all_ok, errors = 0, []
    for fname, t in truth.items():
        res = compare(preds.get(fname), t)
        for k, ok in res.items():
            per[k] += ok
            if not ok:
                p = preds.get(fname) or {}
                errors.append((fname, k, p.get(k), t.get(k)))
        all_ok += all(res.values())
    n = len(truth)
    return SettingResult(name, n, {k: v / n for k, v in per.items()}, all_ok,
                         sum(secs) / len(secs) if secs else None, errors)


def run_ocr_setting(engine, truth: dict[str, dict], longest_side: int, synthetic: bool, workers: int,
                    landing_dir: Path = config.LANDING_DIR) -> SettingResult:
    files = sorted(truth)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = list(pool.map(lambda f: ocr_cached(engine, landing_dir / f, longest_side, synthetic), files))
    preds = {f: fields_from_text(r.text) for f, r in zip(files, runs)}
    prefix = "synth" if synthetic else "ocr"
    return score(f"{prefix}-{longest_side}px", preds, truth, [r.seconds for r in runs])


def synthetic_truth(silver_dir: Path = config.SILVER_DIR) -> dict[str, dict]:
    """Vérité terrain des faux scans : la silver des PDF natifs (issue de la couche texte, exacte)."""
    natives = duckdb.execute(
        f"SELECT file_name FROM read_parquet('{silver_dir / 'invoices' / 'data.parquet'}') "
        "WHERE extraction_method = 'pdf_text' ORDER BY file_name"
    ).fetchall()
    return fields_from_silver([r[0] for r in natives], silver_dir)


def format_report(results: list[SettingResult], title: str) -> str:
    head = "| Champ | " + " | ".join(r.name for r in results) + " |"
    sep = "|---|" + "---:|" * len(results)
    rows = [f"| {k} | " + " | ".join(f"{r.per_field[k]:.0%}" for r in results) + " |" for k in FIELDS]
    rows.append("| **facture 100 % exacte** | " + " | ".join(f"**{r.docs_all_correct}/{r.n}**" for r in results) + " |")
    rows.append("| temps OCR moyen / page | " + " | ".join(
        f"{r.seconds_per_page:.1f} s" if r.seconds_per_page else "—" for r in results) + " |")
    lines = [f"### {title}", "", head, sep, *rows, ""]
    for r in results:
        if r.errors:
            lines.append(f"Erreurs `{r.name}` :")
            for fname, k, got, exp in r.errors[:40]:
                if k == "lines":
                    got, exp = "(détail des lignes)", "(voir vérité terrain)"
                lines.append(f"- `{fname}` · **{k}** : lu `{got}`, attendu `{exp}`")
            lines.append("")
    return "\n".join(lines)
