# Agent : mêmes questions, plusieurs LLM

Commande : `uv run factures agent-bench`. Chiffres attendus calculés par SQL direct sur l'entrepôt.

| Question | Attendu (SQL) | hyperfluid-gemma | hyperfluid-granite | hyperfluid-nemotron | ollama-ministral |
|---|---|---|---|---|---|
| Quel est le montant TTC des factures en retard en 2025 ? | 106886.43 | ✅ 2 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 2 s · invoice_totals | ✅ 6 s · invoice_totals |
| Combien de factures le fournisseur Aubry nous a-t-il envoyées ? | 11 | ✅ 2 s · invoice_totals | ✅ 2 s · list_invoices | ✅ 1 s · invoice_totals | ✅ 4 s · invoice_totals |
| Et parmi elles, combien sont déjà payées ? | 5 | ✅ 2 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 1 s · invoice_totals | ✅ 6 s · invoice_totals |
| Quel est le total HT des factures de la catégorie Informatique émises en 2026 ? | 126167.46 | ✅ 3 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 1 s · invoice_totals | ✅ 7 s · invoice_totals |
| Quel fournisseur a le plus gros montant TTC cumulé, et combien ? | Aubry, 295611.58 | ✅ 3 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 1 s · invoice_totals | ✅ 12 s · invoice_totals |
| Quels sont le client et le montant TTC de la facture A-2025-0010 ? | Muller, 22195.44 | ✅ 4 s · get_invoice | ✅ 2 s · get_invoice | ✅ 2 s · get_invoice | ✅ 12 s · get_invoice |
| Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro. | V-2025-0001 | ✅ 2 s · list_invoices | ✅ 2 s · list_invoices | ✅ 1 s · list_invoices | ✅ 8 s · list_invoices |
| Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ? | Disque SSD externe 2 To, 229 | ✅ 4 s · describe_schema → run_sql | ✅ 5 s · describe_schema → run_sql | ❌ 2 s · aucun outil | ❌ 30 s · invoice_totals → describe_schema → run_sql |
| Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime. | 86.67 | ✅ 4 s · describe_schema → run_sql | ✅ 5 s · describe_schema → run_sql | ❌ 2 s · aucun outil | ❌ 7 s · list_invoices |
| **Score** | | **9/9** · 26 s | **9/9** · 28 s | **7/9** · 14 s | **7/9** · 92 s |

✗ après un nom d'outil = appel en erreur (le LLM a dû se corriger).

## Réponses complètes

### hyperfluid-gemma
**Quel est le montant TTC des factures en retard en 2025 ?** — exacte (attendu : 106886.43)

> Le montant TTC des factures en retard en 2025 est de 106 886,43 €.
> 
> Source : invoice_totals

**Combien de factures le fournisseur Aubry nous a-t-il envoyées ?** — exacte (attendu : 11)

> Le fournisseur Aubry nous a envoyé 11 factures.
> 
> Source : invoice_totals

**Et parmi elles, combien sont déjà payées ?** — exacte (attendu : 5)

> Parmi les factures du fournisseur Aubry, 5 sont déjà payées.
> 
> Source : invoice_totals

**Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?** — exacte (attendu : 126167.46)

> Le total HT des factures de la catégorie Informatique émises en 2026 est de 126 167,46 €.
> 
> Source : invoice_totals

**Quel fournisseur a le plus gros montant TTC cumulé, et combien ?** — exacte (attendu : Aubry, 295611.58)

> Le fournisseur ayant le plus gros montant TTC cumulé est Aubry, avec un total de 295 611,58 €.
> 
> Source : invoice_totals

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> Le client de la facture A-2025-0010 est Muller et le montant TTC est de 22 195,44 €.
> 
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Oui, il y a une facture avec une anomalie détectée : V-2025-0001.
> 
> Source : list_invoices

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — exacte (attendu : Disque SSD externe 2 To, 229)

> L'article commandé en plus grande quantité au total est le « Disque SSD externe 2 To », avec un total de 229,000 unités.
> 
> Source : run_sql

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — exacte (attendu : 86.67)

> Le prix unitaire HT moyen de l'article « Cartouche toner noir » est de 86,67 €.
> 
> Source : run_sql

### hyperfluid-granite
**Quel est le montant TTC des factures en retard en 2025 ?** — exacte (attendu : 106886.43)

> Le montant TTC des factures en retard en 2025 est de 106 886,43 €.
> 
> Source : invoice_totals

**Combien de factures le fournisseur Aubry nous a-t-il envoyées ?** — exacte (attendu : 11)

> Le fournisseur Aubry nous a envoyé 11 factures.
> 
> Source : list_invoices

**Et parmi elles, combien sont déjà payées ?** — exacte (attendu : 5)

> Parmi les 11 factures du fournisseur Aubry, 5 sont déjà payées.
> 
> Source : invoice_totals

**Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?** — exacte (attendu : 126167.46)

> Le total HT des factures de la catégorie Informatique émises en 2026 est de 126 167,46 €.
> 
> Source : invoice_totals

**Quel fournisseur a le plus gros montant TTC cumulé, et combien ?** — exacte (attendu : Aubry, 295611.58)

> Le fournisseur avec le plus gros montant TTC cumulé est Aubry avec 295 611,58 €.
> 
> Source : invoice_totals

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> Client : Muller  
> Montant TTC : 22 195,44 €  
> 
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Oui, il y a une facture avec une anomalie détectée : V-2025-0001.
> 
> Source : list_invoices

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — exacte (attendu : Disque SSD externe 2 To, 229)

> L'article ayant été commandé en plus grande quantité au total est « Disque SSD externe 2 To », avec une quantité totale de 229 unités.
> 
> Source : run_sql

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — exacte (attendu : 86.67)

> Le prix unitaire HT moyen de l'article « Cartouche toner noir » est de 86,67 €.
> 
> Source : run_sql
> 
> (Arrondi au centime comme demandé.)

### hyperfluid-nemotron
**Quel est le montant TTC des factures en retard en 2025 ?** — exacte (attendu : 106886.43)

> Le montant TTC des factures en retard en 2025 est 106 886,43 €. Il y a 12 factures.
> Source : invoice_totals

**Combien de factures le fournisseur Aubry nous a-t-il envoyées ?** — exacte (attendu : 11)

> 11 factures ont été envoyées par le fournisseur Aubry.
> Source : invoice_totals

**Et parmi elles, combien sont déjà payées ?** — exacte (attendu : 5)

> 5 factures ont été payées par le fournisseur Aubry.
> Source : invoice_totals

**Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?** — exacte (attendu : 126167.46)

> Le total HT des factures de la catégorie Informatique émises en 2026 est 126 167,46 €.
> Source : invoice_totals

**Quel fournisseur a le plus gros montant TTC cumulé, et combien ?** — exacte (attendu : Aubry, 295611.58)

> Le fournisseur avec le plus gros montant TTC cumulé est Aubry, avec un montant de 295 611,58 €.
> Source : invoice_totals

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> Le client de la facture A-2025-0010 est Muller et le montant TTC est 22 195,44 €.
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Oui, il y a une facture avec une anomalie détectée. Son numéro est V-2025-0001.
> Source : list_invoices

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — INEXACTE (attendu : Disque SSD externe 2 To, 229)

> Je ne peux pas répondre à cette question car les outils disponibles (list_invoices, invoice_totals, get_invoice, describe_schema, run_sql) ne permettent pas de faire une agrégation des quantités par désignation d'article sur l'ensemble des factures fournisseurs. L'outil `get_invoice` donne le détail d'une facture spécifique, mais il n'y a pas d'outil pour agréger les lignes de plusieurs factures par désignation.
> 
> Source : Aucun outil utilisé

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — INEXACTE (attendu : 86.67)

> Je ne peux pas répondre à cette question car aucun outil ne permet de calculer un prix unitaire moyen par article. Les outils disponibles permettent de lister des factures, d'obtenir des totaux globaux (TTC, HT, TVA) par filtres, ou de voir le détail d'une facture spécifique, mais pas d'analyser les lignes de produits pour un calcul de prix unitaire moyen.
> 
> Source : Aucun outil utilisé

### ollama-ministral
**Quel est le montant TTC des factures en retard en 2025 ?** — exacte (attendu : 106886.43)

> Le montant TTC des factures en retard en 2025 est de **106 886,43 €**.
> 
> Source : invoice_totals

**Combien de factures le fournisseur Aubry nous a-t-il envoyées ?** — exacte (attendu : 11)

> Le fournisseur Aubry nous a envoyé **11 factures**.
> 
> Source : invoice_totals

**Et parmi elles, combien sont déjà payées ?** — exacte (attendu : 5)

> Parmi les **11 factures** de Aubry, **5 sont déjà payées**.
> 
> Source : invoice_totals

**Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?** — exacte (attendu : 126167.46)

> Le total HT des factures de la catégorie **Informatique** émises en 2026 est de **126 167,46 €**.
> 
> Source : invoice_totals

**Quel fournisseur a le plus gros montant TTC cumulé, et combien ?** — exacte (attendu : Aubry, 295611.58)

> Le fournisseur **Aubry** a le plus gros montant TTC cumulé avec **295 611,58 €**.
> 
> Source : invoice_totals

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> La facture **A-2025-0010** est émise pour le client **Muller** et son montant TTC est de **22 195,44 €**.
> 
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Oui, il y a **1 facture signalée** avec une anomalie :
> - **V-2025-0001** (Fournitures, Vasseur → Lecomte, payée).
> 
> *Source : list_invoices*

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — INEXACTE (attendu : Disque SSD externe 2 To, 229)

> Voici les 10 factures avec le plus grand nombre total d'articles (quantités cumulées) :
> 1. **MS-2025-0009** : 46,000 unités
> 2. **LG-2025-0003** : 42,000 unités
> 3. **LG-2026-0007** : 41,000 unités
> 4. **P-2025-0001** : 37,000 unités
> 5. **P-2025-0005**

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — INEXACTE (attendu : 86.67)

> Je n'ai pas trouvé de facture avec le fournisseur « toner noir » dans les données disponibles. Vérifiez l'orthographe ou précisez le nom exact du fournisseur ou de l'article.
> 
> Source : list_invoices
