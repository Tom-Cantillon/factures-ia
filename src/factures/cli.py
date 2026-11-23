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


def main(argv: list[str] | None = None) -> int:
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
