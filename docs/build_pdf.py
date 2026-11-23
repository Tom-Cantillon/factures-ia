"""Génère docs/RAPPORT.pdf à partir de docs/RAPPORT.md (Markdown → HTML mis en page → PDF via Chrome).

    uv run --with markdown python docs/build_pdf.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
CSS = """
@page { size: A4; margin: 15mm 15mm 14mm 15mm; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 9.6pt; line-height: 1.38; color: #1d1d1f; }
h1 { font-size: 18pt; margin: 0 0 2pt; color: #0b3d62; }
h2 { font-size: 12.5pt; color: #0b3d62; border-bottom: 1.5px solid #0b3d62; padding-bottom: 2pt; margin: 13pt 0 5pt; }
p { margin: 4pt 0; text-align: justify; }
ul, ol { margin: 3pt 0 3pt 16pt; padding: 0; } li { margin: 1.5pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8.6pt; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #c8ccd2; padding: 2.5pt 5pt; vertical-align: top; }
th { background: #eef3f8; text-align: left; }
td:not(:first-child) { text-align: left; }
code { font-family: "SF Mono", Menlo, monospace; font-size: 8.3pt; background: #f3f4f6; padding: 0 2pt; border-radius: 2pt; }
pre { background: #f6f8fa; border: 1px solid #e1e4e8; padding: 6pt; font-size: 7.4pt; line-height: 1.3; overflow: hidden; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 7.4pt; }
strong { color: #111; }
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
    pdf = DOCS / "RAPPORT.pdf"
    subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html.as_uri()], check=True, capture_output=True)
    html.unlink()
    print(f"→ {pdf}")


if __name__ == "__main__":
    main()
