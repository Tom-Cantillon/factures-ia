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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factures", description="Pipeline factures : S3 → OCR → bronze → silver")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="Télécharge les nouvelles factures du bucket S3 vers data/landing")
    p.add_argument("--bucket", default=config.S3_BUCKET)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("detect", help="Indique pour chaque PDF s'il est « texte » ou « image » (OCR nécessaire)")
    p.add_argument("--csv", action="store_true", help="Sortie CSV sur stdout")
    p.set_defaults(func=cmd_detect)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
