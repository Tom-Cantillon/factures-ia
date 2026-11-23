"""Point d'entrée en ligne de commande : `uv run factures <commande>`."""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from factures import config


def cmd_fetch(args: argparse.Namespace) -> int:
    from factures.fetch import fetch

    res = fetch(bucket=args.bucket)
    for key in res.downloaded:
        print(f"  + {key}")
    print(f"{len(res.downloaded)} téléchargé(s), {len(res.skipped)} déjà présent(s) → {config.LANDING_DIR}")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    from factures.detect import inspect_pdf

    pdfs = sorted(config.LANDING_DIR.rglob("*.pdf"))
    if not pdfs:
        print("Aucun PDF dans la zone d'arrivée : lancez d'abord `factures fetch`.", file=sys.stderr)
        return 1

    infos = [inspect_pdf(p) for p in pdfs]
    rows = [
        {
            "fichier": i.path.relative_to(config.LANDING_DIR).as_posix(),
            "type": i.kind,
            "pages": i.pages,
            "caracteres": sum(i.chars_per_page),
            "images": i.images,
            "ocr": "oui" if i.needs_ocr else "non",
        }
        for i in infos
    ]

    if args.csv:
        writer = csv.DictWriter(sys.stdout, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    else:
        width = max(len(r["fichier"]) for r in rows)
        print(f"{'fichier':<{width}}  type    pages  caractères  images  OCR")
        for r in rows:
            print(f"{r['fichier']:<{width}}  {r['type']:<6}  {r['pages']:>5}  {r['caracteres']:>10}  {r['images']:>6}  {r['ocr']}")
    counts = Counter(r["type"] for r in rows)
    print(f"\n{len(rows)} PDF : " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())), file=sys.stderr)
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    import time

    from factures.ocr import get_engine, render_page

    path = Path(args.pdf)
    if not path.exists():
        path = config.LANDING_DIR / args.pdf
    engine = get_engine()

    t0 = time.perf_counter()
    png = render_page(path, args.page, args.longest_side)
    render_s = time.perf_counter() - t0
    if args.save_image:
        Path(args.save_image).write_bytes(png)

    res = engine.ocr_png(png)
    print(res.text)
    print(
        f"\n--- {path.name} p.{args.page} | {res.engine}/{res.model} | image {args.longest_side}px "
        f"({len(png) // 1024} Ko) | rendu {render_s:.2f}s | OCR {res.seconds:.2f}s | "
        f"tokens in/out {res.usage.get('prompt_tokens')}/{res.usage.get('completion_tokens')}",
        file=sys.stderr,
    )
    return 0


def _cached_engine():
    """Un seul client OCR partagé, créé seulement si un document a réellement besoin d'OCR."""
    import functools
    import threading

    from factures.ocr import get_engine

    lock = threading.Lock()

    @functools.cache
    def build():
        return get_engine()

    def factory():
        with lock:
            return build()

    return factory


def cmd_bronze(args: argparse.Namespace) -> int:
    from factures.bronze import ingest

    res = ingest(_cached_engine(), limit=args.limit, workers=args.workers, longest_side=args.longest_side)
    print(
        f"run {res.run_id} : {len(res.extracted)} extrait(s), {res.already_done} déjà en bronze, "
        f"{len(res.failed)} en échec (retentés au prochain run), {res.ocr_calls} appel(s) OCR"
    )
    return 0


def cmd_silver(args: argparse.Namespace) -> int:
    from factures.silver import build

    s = build()
    print(
        f"silver : {s['invoices']} facture(s) ({s['valides']} valide(s), {s['signalees']} signalée(s)), "
        f"{s['lines']} ligne(s), {s['quarantine']} en quarantaine → {config.SILVER_DIR}"
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cmd_fetch(args)
    cmd_bronze(args)
    cmd_silver(args)
    return cmd_warehouse(args)


def cmd_eval(args: argparse.Namespace) -> int:
    from factures.evaluate import (EVAL_DIR, fields_from_silver, format_report, load_truth, run_ocr_setting,
                                   score, synthetic_truth)

    truth = load_truth()
    engine = _cached_engine()()
    results = [score("silver", fields_from_silver(sorted(truth)), truth, None)]
    for side in args.sides:
        print(f"OCR des {len(truth)} scans réels à {side} px…", file=sys.stderr)
        results.append(run_ocr_setting(engine, truth, side, False, args.workers))
    report = [format_report(results, f"Scans réels — {len(truth)} factures, vérité terrain vérifiée à la main")]

    if args.synthetic:
        st = synthetic_truth()
        synth = []
        for side in args.sides:
            print(f"OCR des {len(st)} faux scans à {side} px…", file=sys.stderr)
            synth.append(run_ocr_setting(engine, st, side, True, args.workers))
        report.append(format_report(synth, f"Faux scans synthétiques — {len(st)} PDF natifs dégradés, vérité exacte"))

    text = "\n".join(report)
    print(text)
    if args.out:
        out = Path(args.out) if Path(args.out).is_absolute() else EVAL_DIR / args.out
        out.write_text(f"# Résultats de l'évaluation OCR\n\nCommande : `uv run factures eval "
                       f"--sides {' '.join(map(str, args.sides))}{' --synthetic' if args.synthetic else ''}`\n\n{text}")
        print(f"\n→ {out}", file=sys.stderr)
    return 0


def cmd_warehouse(args: argparse.Namespace) -> int:
    from factures.warehouse import build_file

    path = config.DATA_DIR / "warehouse.duckdb"
    skipped = build_file(path)
    print(f"Entrepôt (vues uniquement) → {path}")
    if skipped:
        print("Vues non créées (aucune donnée encore) : " + ", ".join(skipped))
    return 0


def cmd_sql(args: argparse.Namespace) -> int:
    from factures.warehouse import connect

    rel = connect().sql(args.query)
    if rel is None:
        return 0
    if args.csv:
        import csv as _csv

        w = _csv.writer(sys.stdout)
        w.writerow(rel.columns)
        w.writerows(rel.fetchall())
    else:
        rel.show(max_width=200, max_rows=args.max_rows)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import duckdb

    from factures.bronze import DOCUMENTS, ERRORS, _has_files, _table_glob

    b = config.BRONZE_DIR
    landing = len(list(config.LANDING_DIR.rglob("*.pdf")))
    print(f"landing : {landing} PDF")
    if not _has_files(b, DOCUMENTS):
        print("bronze  : vide")
        return 0
    docs = _table_glob(b, DOCUMENTS)
    print("bronze.documents :")
    for method, n, secs in duckdb.execute(
        "SELECT extraction_method, count(*), round(avg(ocr_seconds), 1) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
        [docs],
    ).fetchall():
        print(f"  {method:<9} {n:>4}" + (f"   (OCR moyen {secs} s/doc)" if secs else ""))
    if _has_files(b, ERRORS):
        pending = duckdb.execute(
            "SELECT count(DISTINCT e.doc_id) FROM read_parquet(?) e "
            "WHERE e.doc_id NOT IN (SELECT doc_id FROM read_parquet(?))",
            [_table_glob(b, ERRORS), docs],
        ).fetchone()[0]
        total = duckdb.execute("SELECT count(*) FROM read_parquet(?)", [_table_glob(b, ERRORS)]).fetchone()[0]
        print(f"bronze.extraction_errors : {total} échec(s) journalisé(s), {pending} document(s) encore à retraiter")
    return 0


def main(argv: list[str] | None = None) -> int:
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "openai", "botocore", "boto3", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="factures", description="Pipeline factures : S3 → OCR → bronze → silver")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="Télécharge les nouvelles factures du bucket S3 vers data/landing")
    p.add_argument("--bucket", default=config.S3_BUCKET)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("detect", help="Indique pour chaque PDF s'il est « texte » ou « image » (OCR nécessaire)")
    p.add_argument("--csv", action="store_true", help="Sortie CSV sur stdout")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("ocr", help="Envoie une page de PDF au modèle d'OCR et affiche le texte reconnu")
    p.add_argument("pdf", help="Chemin du PDF, ou nom d'un fichier de data/landing")
    p.add_argument("--page", type=int, default=0, help="Numéro de page (0 = première)")
    p.add_argument("--longest-side", type=int, default=1540, help="Plus grand côté de l'image envoyée, en pixels")
    p.add_argument("--save-image", metavar="PNG", help="Enregistre l'image envoyée au modèle")
    p.set_defaults(func=cmd_ocr)

    for name, func, help_ in (
        ("bronze", cmd_bronze, "Extrait le texte des PDF de data/landing vers la couche bronze (incrémental)"),
        ("run", cmd_run, "fetch + bronze + silver + warehouse"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--limit", type=int, help="Traiter au plus N nouveaux documents")
        p.add_argument("--workers", type=int, default=4, help="Appels OCR en parallèle")
        p.add_argument("--longest-side", type=int, default=1540, help="Taille des images envoyées à l'OCR")
        p.add_argument("--bucket", default=config.S3_BUCKET)
        p.set_defaults(func=func)

    p = sub.add_parser("silver", help="Reconstruit la couche silver (parsing, typage, contrôles, quarantaine)")
    p.set_defaults(func=cmd_silver)

    p = sub.add_parser("eval", help="Précision de l'OCR champ par champ contre la vérité terrain")
    p.add_argument("--sides", type=int, nargs="+", default=[768, 1540], help="Résolutions comparées (px)")
    p.add_argument("--synthetic", action="store_true", help="Ajoute le jeu de faux scans (PDF natifs dégradés)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--out", default="results.md", help="Fichier de résultats (dans eval/), vide pour ne pas écrire")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("warehouse", help="Génère data/warehouse.duckdb (vues SQL sur bronze/silver) pour DBeaver")
    p.set_defaults(func=cmd_warehouse)

    p = sub.add_parser("sql", help="Exécute une requête SQL sur l'entrepôt (bronze.*, silver.*)")
    p.add_argument("query")
    p.add_argument("--csv", action="store_true")
    p.add_argument("--max-rows", type=int, default=50)
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("status", help="Résumé de la zone d'arrivée et de la couche bronze")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("agent", help="Agent conversationnel (français) sur les factures, via le serveur MCP")
    p.add_argument("--llm", help="Profil LLM (llm_profiles.toml) ; défaut : LLM_PROFILE puis `default`")
    p.add_argument("-q", "--question", help="Pose une seule question puis quitte")
    p.add_argument("--max-steps", type=int, default=8, help="Nombre maximal d'appels LLM par question")
    p.set_defaults(func=lambda a: __import__("factures.agent", fromlist=["main"]).main(a.llm, a.question, a.max_steps))

    p = sub.add_parser("agent-bench", help="Mêmes questions posées à plusieurs LLM, chiffres vérifiés par SQL")
    p.add_argument("--llm", nargs="+", help="Profils à comparer (défaut : tous)")
    p.add_argument("--out", default="agent_results.md", help="Fichier de résultats (dans eval/)")
    p.set_defaults(func=lambda a: __import__("factures.agent_bench", fromlist=["main"]).main(a.llm, a.out))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
