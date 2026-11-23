"""Étape 4 : du texte brut (bronze) à une facture structurée.

Le texte d'un PDF natif et celui de l'OCR n'ont pas la même forme :
- natif : une valeur par ligne, cellules du tableau à la suite, aucun balisage ;
- OCR : markdown (`# FACTURE`, `**Libellé** : valeur`, `---`), tableaux en HTML, totaux tantôt en
  lignes `**Total HT** 6 306,05 €`, tantôt dans un second tableau HTML.

Plutôt que deux parseurs, on **normalise** d'abord les deux formes vers un même flux de lignes
(une cellule ou un « libellé : valeur » par ligne), puis un seul parseur lit ce flux. Le parseur
n'invente ni ne corrige rien : une valeur illisible reste vide, et c'est aux contrôles qualité
(silver.py) de décider.
"""

import html
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

PARSER_VERSION = "1.0"

_TOTAL_LABEL = r"(?:Total HT|Total TVA|Total TTC|TVA \d+(?:[.,]\d+)? ?%)"
_AMOUNT = r"-?\d[\d .,]*\s?€?"
_KV_LABELS = {
    "Numéro de facture": "invoice_number",
    "Date d'émission": "issue_date",
    "Date d'échéance": "due_date",
    "Catégorie": "category",
    "Statut": "status",
    "Client": "client_name",
    "SIRET client": "client_siret",
    "SIRET": "supplier_siret",
    "TVA intracom.": "supplier_vat_number",
    "Mode de paiement": "payment_method",
    "IBAN": "iban",
}
_KV_RE = re.compile(r"^(" + "|".join(sorted(map(re.escape, _KV_LABELS), key=len, reverse=True)) + r")\s*:\s*(.*)$")
_ITEM_HEADER = ["Désignation", "Qté", "Prix unitaire HT", "TVA", "Total HT"]


# --------------------------------------------------------------------------- normalisation

def to_lines(text: str) -> list[str]:
    """Ramène texte natif et markdown/HTML d'OCR à une liste de lignes homogène."""
    text = text.replace("\xa0", " ").replace(" ", " ").replace("’", "'")
    # Tableaux HTML : chaque cellule devient une ligne, comme dans la couche texte native.
    text = re.sub(r"<t[hd][^>]*>(.*?)</t[hd]>", lambda m: "\n" + m.group(1) + "\n", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)

    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.replace("**", "").replace("__", "").strip()
        line = re.sub(r"^#+\s*", "", line)          # titres markdown
        line = re.sub(r"\s+", " ", line).strip()
        if not line or re.fullmatch(r"[-*_=|: ]{3,}", line):  # séparateurs
            continue
        # « Total HT 6 306,05 € » (OCR) → « Total HT » puis « 6 306,05 € » (comme le natif)
        m = re.fullmatch(rf"({_TOTAL_LABEL})\s*:?\s*({_AMOUNT})", line)
        if m:
            lines += [m.group(1), m.group(2).strip()]
            continue
        lines.append(line)
    return lines


# --------------------------------------------------------------------------- valeurs typées

def parse_amount(s: str | None) -> Decimal | None:
    """'1 261,21 €' → Decimal('1261.21'). Decimal et non float : 0,1 + 0,2 doit faire 0,3 au centime près."""
    if s is None:
        return None
    t = re.sub(r"[€\s]", "", s.replace("EUR", ""))
    if not re.fullmatch(r"-?[\d.,]+", t):
        return None
    if "," in t and "." in t:            # 1.261,21 → séparateur de milliers « . »
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:                       # 1261,21
        if t.count(",") > 1:
            return None
        t = t.replace(",", ".")
    elif t.count(".") > 1:               # 1.261.210 : ambigu
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def parse_rate(s: str | None) -> Decimal | None:
    if s is None:
        return None
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*%", s.strip())
    return Decimal(m.group(1).replace(",", ".")) if m else None


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


# --------------------------------------------------------------------------- parseur

@dataclass
class ParsedLine:
    line_no: int
    description: str
    quantity: Decimal | None
    unit_price_ht: Decimal | None
    vat_rate: Decimal | None
    line_total_ht: Decimal | None
    raw: list[str]


@dataclass
class ParsedInvoice:
    fields: dict = field(default_factory=dict)        # valeurs brutes (chaînes) par champ
    lines: list[ParsedLine] = field(default_factory=list)
    vat_breakdown: dict = field(default_factory=dict)  # taux → montant
    problems: list[str] = field(default_factory=list)  # anomalies de lecture


def parse_invoice(text: str) -> ParsedInvoice:
    lines = to_lines(text)
    inv = ParsedInvoice()
    f = inv.fields

    # Libellé : valeur
    for i, line in enumerate(lines):
        m = _KV_RE.match(line)
        if m:
            key = _KV_LABELS[m.group(1)]
            f.setdefault(key, m.group(2).strip() or None)
            if key == "client_name":
                f["_client_idx"] = i

    # Fournisseur : bloc « nom / rue / CP ville » juste avant le premier « SIRET : ».
    siret_idx = next((i for i, l in enumerate(lines) if l.startswith("SIRET :")), None)
    if siret_idx is not None and siret_idx >= 3:
        f["supplier_name"] = lines[siret_idx - 3]
        f["supplier_address"] = ", ".join(lines[siret_idx - 2:siret_idx])
    # Adresse client : lignes entre « Client : » et « SIRET client : ».
    ci = f.pop("_client_idx", None)
    if ci is not None:
        end = next((j for j in range(ci + 1, len(lines)) if lines[j].startswith("SIRET client")), None)
        if end is not None:
            f["client_address"] = ", ".join(lines[ci + 1:end])

    # Lignes de facture : groupes de 5 cellules après l'en-tête, jusqu'au bloc des totaux.
    start = next((i for i in range(len(lines) - 4) if lines[i:i + 5] == _ITEM_HEADER), None)
    if start is None:
        inv.problems.append("tableau des lignes introuvable")
        i = 0
    else:
        i = start + 5
        while i < len(lines) and not re.fullmatch(_TOTAL_LABEL, lines[i]):
            cells = lines[i:i + 5]
            if len(cells) < 5:
                inv.problems.append(f"ligne {len(inv.lines) + 1} incomplète")
                break
            item = ParsedLine(
                line_no=len(inv.lines) + 1,
                description=cells[0],
                quantity=parse_amount(cells[1]),
                unit_price_ht=parse_amount(cells[2]),
                vat_rate=parse_rate(cells[3]),
                line_total_ht=parse_amount(cells[4]),
                raw=cells,
            )
            if None in (item.quantity, item.unit_price_ht, item.vat_rate, item.line_total_ht):
                inv.problems.append(f"ligne {item.line_no} illisible : {' | '.join(cells)}")
            inv.lines.append(item)
            i += 5

    # Totaux : « libellé » puis « montant » sur la ligne suivante.
    while i < len(lines) - 1:
        label, value = lines[i], lines[i + 1]
        if re.fullmatch(_TOTAL_LABEL, label):
            if label == "Total HT":
                f.setdefault("total_ht", value)
            elif label == "Total TVA":
                f.setdefault("total_tva", value)
            elif label == "Total TTC":
                f.setdefault("total_ttc", value)
            else:
                inv.vat_breakdown[label] = value
            i += 2
        else:
            i += 1
    return inv
