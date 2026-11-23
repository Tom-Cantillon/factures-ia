# Résultats de l'évaluation OCR

Commande : `uv run factures eval --sides 512 768 1540 --synthetic`

### Scans réels — 20 factures, vérité terrain vérifiée à la main

| Champ | silver | ocr-512px | ocr-768px | ocr-1540px |
|---|---:|---:|---:|---:|
| invoice_number | 100% | 25% | 95% | 100% |
| issue_date | 100% | 30% | 100% | 100% |
| due_date | 100% | 55% | 100% | 100% |
| supplier_name | 100% | 55% | 100% | 100% |
| supplier_siret | 100% | 0% | 100% | 100% |
| supplier_vat_number | 100% | 0% | 100% | 100% |
| client_name | 100% | 30% | 100% | 100% |
| client_siret | 100% | 30% | 95% | 100% |
| category | 100% | 65% | 100% | 100% |
| status | 100% | 70% | 100% | 100% |
| payment_method | 100% | 70% | 100% | 100% |
| iban | 100% | 0% | 100% | 100% |
| total_ht | 100% | 10% | 100% | 100% |
| total_tva | 100% | 70% | 100% | 100% |
| total_ttc | 100% | 70% | 100% | 100% |
| line_count | 100% | 0% | 100% | 100% |
| lines | 100% | 0% | 100% | 100% |
| **facture 100 % exacte** | **20/20** | **0/20** | **18/20** | **20/20** |
| temps OCR moyen / page | — | 5.5 s | 5.3 s | 8.2 s |

Erreurs `ocr-512px` :
- `facture_A-2025-0010_scan.pdf` · **invoice_number** : lu `A-2035-0010`, attendu `A-2025-0010`
- `facture_A-2025-0010_scan.pdf` · **due_date** : lu `None`, attendu `2025-06-16`
- `facture_A-2025-0010_scan.pdf` · **supplier_siret** : lu `77395260208050`, attendu `77360260298050`
- `facture_A-2025-0010_scan.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2025-0010_scan.pdf` · **client_name** : lu `None`, attendu `Muller`
- `facture_A-2025-0010_scan.pdf` · **iban** : lu `None`, attendu `FR1578820812191361939909169`
- `facture_A-2025-0010_scan.pdf` · **total_ht** : lu `None`, attendu `18496.2`
- `facture_A-2025-0010_scan.pdf` · **line_count** : lu `0`, attendu `None`
- `facture_A-2025-0010_scan.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2026-0004_scan.pdf` · **invoice_number** : lu `A-2035-0004`, attendu `A-2026-0004`
- `facture_A-2026-0004_scan.pdf` · **issue_date** : lu `2020-03-23`, attendu `2026-03-23`
- `facture_A-2026-0004_scan.pdf` · **due_date** : lu `None`, attendu `2026-04-07`
- `facture_A-2026-0004_scan.pdf` · **supplier_siret** : lu `77300360298000`, attendu `77360260298050`
- `facture_A-2026-0004_scan.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2026-0004_scan.pdf` · **client_name** : lu `Faury`, attendu `Fleury`
- `facture_A-2026-0004_scan.pdf` · **client_siret** : lu `67480071955977`, attendu `67468071585977`
- `facture_A-2026-0004_scan.pdf` · **iban** : lu `None`, attendu `FR1578820812191361939909169`
- `facture_A-2026-0004_scan.pdf` · **total_ht** : lu `None`, attendu `10911.61`
- `facture_A-2026-0004_scan.pdf` · **total_tva** : lu `2162.32`, attendu `2182.32`
- `facture_A-2026-0004_scan.pdf` · **line_count** : lu `0`, attendu `None`
- `facture_A-2026-0004_scan.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2026-0007_scan.pdf` · **invoice_number** : lu `A-2036-0007`, attendu `A-2026-0007`
- `facture_A-2026-0007_scan.pdf` · **supplier_name** : lu `Actry`, attendu `Aubry`
- `facture_A-2026-0007_scan.pdf` · **supplier_siret** : lu `77360280286055`, attendu `77360260298050`
- `facture_A-2026-0007_scan.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2026-0007_scan.pdf` · **client_name** : lu `None`, attendu `Grondin Pinto et Fils`
- `facture_A-2026-0007_scan.pdf` · **status** : lu `Paye`, attendu `Payée`
- `facture_A-2026-0007_scan.pdf` · **iban** : lu `None`, attendu `FR1578820812191361939909169`
- `facture_A-2026-0007_scan.pdf` · **total_ht** : lu `None`, attendu `25113.14`
- `facture_A-2026-0007_scan.pdf` · **line_count** : lu `0`, attendu `None`
- `facture_A-2026-0007_scan.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_BS-2025-0002_scan.pdf` · **invoice_number** : lu `85-2025-0932`, attendu `BS-2025-0002`
- `facture_BS-2025-0002_scan.pdf` · **due_date** : lu `2025-10-29`, attendu `2025-10-26`
- `facture_BS-2025-0002_scan.pdf` · **supplier_siret** : lu `4574164485826`, attendu `48740164859826`
- `facture_BS-2025-0002_scan.pdf` · **supplier_vat_number** : lu `None`, attendu `FR20487401648`
- `facture_BS-2025-0002_scan.pdf` · **client_name** : lu `Dello-Barbe S.A.R.L.`, attendu `Diallo Barbe S.A.R.L.`
- `facture_BS-2025-0002_scan.pdf` · **category** : lu `Financières`, attendu `Fournitures`
- `facture_BS-2025-0002_scan.pdf` · **payment_method** : lu `None`, attendu `Prélèvement SEPA`
- `facture_BS-2025-0002_scan.pdf` · **iban** : lu `None`, attendu `FR4545053315869232260256342`
- `facture_BS-2025-0002_scan.pdf` · **total_ht** : lu `None`, attendu `453.3`

Erreurs `ocr-768px` :
- `facture_LG-2026-0009_scan.pdf` · **invoice_number** : lu `LO-2026-0009`, attendu `LG-2026-0009`
- `facture_MS-2026-0005_scan.pdf` · **client_siret** : lu `4527111204945`, attendu `45271111204945`

### Faux scans synthétiques — 50 PDF natifs dégradés, vérité exacte

| Champ | synth-512px | synth-768px | synth-1540px |
|---|---:|---:|---:|
| invoice_number | 2% | 90% | 100% |
| issue_date | 0% | 100% | 100% |
| due_date | 0% | 90% | 100% |
| supplier_name | 12% | 100% | 100% |
| supplier_siret | 0% | 74% | 100% |
| supplier_vat_number | 0% | 64% | 100% |
| client_name | 4% | 74% | 100% |
| client_siret | 0% | 82% | 100% |
| category | 10% | 98% | 100% |
| status | 12% | 100% | 100% |
| payment_method | 58% | 96% | 100% |
| iban | 0% | 48% | 100% |
| total_ht | 6% | 60% | 100% |
| total_tva | 8% | 94% | 100% |
| total_ttc | 2% | 100% | 100% |
| line_count | 0% | 60% | 100% |
| lines | 0% | 46% | 100% |
| **facture 100 % exacte** | **0/50** | **4/50** | **50/50** |
| temps OCR moyen / page | 7.8 s | 5.5 s | 7.4 s |

Erreurs `synth-512px` :
- `facture_A-2025-0001_texte.pdf` · **invoice_number** : lu `None`, attendu `A-2025-0001`
- `facture_A-2025-0001_texte.pdf` · **issue_date** : lu `None`, attendu `2025-01-10`
- `facture_A-2025-0001_texte.pdf` · **due_date** : lu `None`, attendu `2025-03-11`
- `facture_A-2025-0001_texte.pdf` · **supplier_name** : lu `None`, attendu `Aubry`
- `facture_A-2025-0001_texte.pdf` · **supplier_siret** : lu `None`, attendu `77360260298050`
- `facture_A-2025-0001_texte.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2025-0001_texte.pdf` · **client_name** : lu `Lumbard`, attendu `Lombard`
- `facture_A-2025-0001_texte.pdf` · **client_siret** : lu `None`, attendu `20037917087083`
- `facture_A-2025-0001_texte.pdf` · **status** : lu `Payeur`, attendu `Payée`
- `facture_A-2025-0001_texte.pdf` · **iban** : lu `None`, attendu `FR1578820812191361939909169`
- `facture_A-2025-0001_texte.pdf` · **total_ht** : lu `None`, attendu `30811.5`
- `facture_A-2025-0001_texte.pdf` · **total_tva** : lu `6162`, attendu `6162.3`
- `facture_A-2025-0001_texte.pdf` · **total_ttc** : lu `36573`, attendu `36973.8`
- `facture_A-2025-0001_texte.pdf` · **line_count** : lu `0`, attendu `3`
- `facture_A-2025-0001_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2026-0002_texte.pdf` · **invoice_number** : lu `None`, attendu `A-2026-0002`
- `facture_A-2026-0002_texte.pdf` · **issue_date** : lu `None`, attendu `2026-11-17`
- `facture_A-2026-0002_texte.pdf` · **due_date** : lu `None`, attendu `2026-12-17`
- `facture_A-2026-0002_texte.pdf` · **supplier_siret** : lu `77343010000000`, attendu `77360260298050`
- `facture_A-2026-0002_texte.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2026-0002_texte.pdf` · **client_name** : lu `None`, attendu `Grondin Pinto et Fils`
- `facture_A-2026-0002_texte.pdf` · **client_siret** : lu `25196807164742`, attendu `22196937164743`
- `facture_A-2026-0002_texte.pdf` · **iban** : lu `None`, attendu `FR1578820812191361939909169`
- `facture_A-2026-0002_texte.pdf` · **total_ht** : lu `None`, attendu `20354.95`
- `facture_A-2026-0002_texte.pdf` · **total_tva** : lu `None`, attendu `4070.99`
- `facture_A-2026-0002_texte.pdf` · **total_ttc** : lu `20354.95`, attendu `24425.94`
- `facture_A-2026-0002_texte.pdf` · **line_count** : lu `0`, attendu `2`
- `facture_A-2026-0002_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2025-0005_texte.pdf` · **invoice_number** : lu `None`, attendu `A-2025-0005`
- `facture_A-2025-0005_texte.pdf` · **issue_date** : lu `None`, attendu `2025-03-13`
- `facture_A-2025-0005_texte.pdf` · **due_date** : lu `None`, attendu `2025-04-27`
- `facture_A-2025-0005_texte.pdf` · **supplier_name** : lu `None`, attendu `Aubry`
- `facture_A-2025-0005_texte.pdf` · **supplier_siret** : lu `None`, attendu `77360260298050`
- `facture_A-2025-0005_texte.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2025-0005_texte.pdf` · **client_name** : lu `None`, attendu `Grondin Pinto et Fils`
- `facture_A-2025-0005_texte.pdf` · **client_siret** : lu `None`, attendu `22196937164743`
- `facture_A-2025-0005_texte.pdf` · **category** : lu `None`, attendu `Conseil`
- `facture_A-2025-0005_texte.pdf` · **status** : lu `None`, attendu `Payée`
- `facture_A-2025-0005_texte.pdf` · **payment_method** : lu `None`, attendu `Prélèvement SEPA`
- `facture_A-2025-0005_texte.pdf` · **iban** : lu `None`, attendu `FR1578820812191361939909169`

Erreurs `synth-768px` :
- `facture_A-2026-0002_texte.pdf` · **invoice_number** : lu `A-2026-0082`, attendu `A-2026-0002`
- `facture_A-2026-0002_texte.pdf` · **total_ht** : lu `None`, attendu `20354.95`
- `facture_A-2026-0002_texte.pdf` · **line_count** : lu `0`, attendu `2`
- `facture_A-2026-0002_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2025-0005_texte.pdf` · **due_date** : lu `None`, attendu `2025-04-27`
- `facture_A-2025-0005_texte.pdf` · **supplier_vat_number** : lu `None`, attendu `FR09773602602`
- `facture_A-2025-0005_texte.pdf` · **client_name** : lu `Grandin Plots et Fils`, attendu `Grondin Pinto et Fils`
- `facture_A-2025-0005_texte.pdf` · **client_siret** : lu `22196807164743`, attendu `22196937164743`
- `facture_A-2025-0005_texte.pdf` · **total_ht** : lu `None`, attendu `38157.77`
- `facture_A-2025-0005_texte.pdf` · **line_count** : lu `0`, attendu `3`
- `facture_A-2025-0005_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2026-0006_texte.pdf` · **supplier_siret** : lu `77360260298000`, attendu `77360260298050`
- `facture_A-2026-0006_texte.pdf` · **client_name** : lu `Chacuin`, attendu `Chauvin`
- `facture_A-2026-0006_texte.pdf` · **iban** : lu `FR1578820812191381939909169`, attendu `FR1578820812191361939909169`
- `facture_A-2026-0006_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_A-2026-0008_texte.pdf` · **client_name** : lu `Tomes`, attendu `Torres`
- `facture_A-2026-0008_texte.pdf` · **iban** : lu `FR1578820812191361939909189`, attendu `FR1578820812191361939909169`
- `facture_A-2026-0011_texte.pdf` · **total_ht** : lu `None`, attendu `8768.34`
- `facture_A-2026-0011_texte.pdf` · **line_count** : lu `0`, attendu `2`
- `facture_A-2026-0011_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_BS-2025-0003_texte.pdf` · **due_date** : lu `2026-03-10`, attendu `2026-02-10`
- `facture_BS-2025-0003_texte.pdf` · **supplier_siret** : lu `48740164859626`, attendu `48740164859826`
- `facture_BS-2025-0003_texte.pdf` · **supplier_vat_number** : lu `FR20467401648`, attendu `FR20487401648`
- `facture_BS-2025-0003_texte.pdf` · **client_name** : lu `Dunas`, attendu `Dumas`
- `facture_BS-2025-0003_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_BS-2026-0004_texte.pdf` · **supplier_siret** : lu `48740164859626`, attendu `48740164859826`
- `facture_BS-2026-0004_texte.pdf` · **supplier_vat_number** : lu `None`, attendu `FR20487401648`
- `facture_BS-2026-0004_texte.pdf` · **client_name** : lu `Toines`, attendu `Torres`
- `facture_BS-2026-0004_texte.pdf` · **iban** : lu `FR4545052315869232260256342`, attendu `FR4545053315869232260256342`
- `facture_BS-2026-0004_texte.pdf` · **total_tva** : lu `56.86`, attendu `86.86`
- `facture_BS-2026-0006_texte.pdf` · **invoice_number** : lu `BS-2026-0008`, attendu `BS-2026-0006`
- `facture_BS-2026-0008_texte.pdf` · **invoice_number** : lu `SS-2026-0008`, attendu `BS-2026-0008`
- `facture_BS-2026-0008_texte.pdf` · **supplier_siret** : lu `48740164850626`, attendu `48740164859826`
- `facture_C-2025-0002_texte.pdf` · **supplier_vat_number** : lu `None`, attendu `FR32495931032`
- `facture_C-2025-0002_texte.pdf` · **total_ht** : lu `None`, attendu `12696.16`
- `facture_C-2025-0002_texte.pdf` · **line_count** : lu `0`, attendu `3`
- `facture_C-2025-0002_texte.pdf` · **lines** : lu `(détail des lignes)`, attendu `(voir vérité terrain)`
- `facture_C-2025-0005_texte.pdf` · **supplier_siret** : lu `49593103241826`, attendu `49593103241928`
- `facture_C-2025-0005_texte.pdf` · **client_name** : lu `Peresia`, attendu `Pereira`
- `facture_C-2025-0005_texte.pdf` · **iban** : lu `FR54764835030506413953767242`, attendu `FR5476483503056413953767242`
