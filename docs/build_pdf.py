"""Génère RAPPORT.pdf (racine du dépôt) à partir de docs/RAPPORT.md (Markdown → HTML mis en page → PDF via Chrome).

    uv run --with markdown python docs/build_pdf.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
CSS = """
@page { size: A4; margin: 17mm 18mm 16mm 18mm; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 10pt; line-height: 1.55; color: #1f2328; }
h1 { font-size: 21pt; line-height: 1.15; margin: 0 0 4pt; color: #0b3d62; }
.meta { color: #57606a; font-size: 9.5pt; margin: 0 0 12pt; text-align: left; }
h2 { font-size: 13.5pt; color: #0b3d62; border-bottom: 1.5px solid #0b3d62; padding-bottom: 3pt; margin: 22pt 0 9pt; page-break-after: avoid; }
h3 { font-size: 11pt; color: #0b3d62; margin: 14pt 0 5pt; page-break-after: avoid; }
p { margin: 6pt 0; }
ul, ol { margin: 5pt 0 7pt 18pt; padding: 0; } li { margin: 3.5pt 0; }
li > ul { margin: 2pt 0 2pt 14pt; }
table { border-collapse: collapse; width: 100%; margin: 9pt 0 11pt; font-size: 9pt; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: 4.5pt 7pt; vertical-align: top; text-align: left; }
th { background: #eef3f8; }
code { font-family: "SF Mono", Menlo, monospace; font-size: 8.6pt; background: #f3f4f6; padding: 0 2.5pt; border-radius: 2pt; }
pre { background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 4pt; padding: 9pt 10pt; margin: 8pt 0 10pt;
      font-size: 8pt; line-height: 1.35; overflow: hidden; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8pt; }
strong, b { color: #111; }
.callout { background: #eef6f8; border-left: 3.5pt solid #0f6c7a; border-radius: 3pt; padding: 8pt 12pt; margin: 10pt 0 12pt;
           page-break-inside: avoid; }
.callout ul { margin: 4pt 0 0 16pt; } .callout li { margin: 2.5pt 0; }
.figs { display: flex; gap: 12pt; margin: 12pt 0 6pt; page-break-inside: avoid; }
.figs figure { margin: 0; flex: 1; min-width: 0; }
.figs img { width: 100%; border: 1px solid #d0d7de; border-radius: 3pt; display: block; }
.figs.single figure { flex: 0 0 78%; margin: 0 auto; }
figcaption { font-size: 8.5pt; color: #57606a; margin-top: 4pt; }
"""


def chrome() -> str:
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chrome"):
        if Path(c).exists() or shutil.which(c):
            return c
    sys.exit("Chrome / Chromium introuvable pour l'export PDF.")


def prepare(md: str) -> str:
    """Python-Markdown exige une ligne vide avant une liste (GitHub, non) : on l'ajoute."""
    import re

    out, prev = [], ""
    for line in md.splitlines():
        line = re.sub(r"^ {2,3}(?=[-*] |\d+\. )", "    ", line)  # sous-listes : 4 espaces attendus
        is_item = re.match(r"^(- |\d+\. )", line)
        prev_item = re.match(r"^(- |\d+\. |\s{2,}\S)", prev)
        if is_item and prev.strip() and not prev_item:
            out.append("")
        out.append(line)
        prev = line
    return "\n".join(out)


def main() -> None:
    md = prepare((DOCS / "RAPPORT.md").read_text())
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
    html = DOCS / "RAPPORT.html"
    html.write_text(f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Rapport</title>'
                    f"<style>{CSS}</style></head><body>{body}</body></html>")
    pdf = DOCS.parent / "RAPPORT.pdf"  # à la racine du dépôt, bien visible pour le correcteur
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html.as_uri()], check=True, capture_output=True)
    html.unlink()
    print(f"→ {pdf}")


if __name__ == "__main__":
    main()
