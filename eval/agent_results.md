# Agent : mêmes questions, plusieurs LLM

Commande : `uv run factures agent-bench`. Chiffres attendus calculés par SQL direct sur l'entrepôt.

| Question | Attendu (SQL) | hyperfluid-gemma | hyperfluid-granite | hyperfluid-nemotron | ollama-ministral |
|---|---|---|---|---|---|
| Quel est le montant TTC des factures en retard en 2025 ? | 106886.43 | ✅ 3 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 2 s · invoice_totals | ✅ 9 s · invoice_totals |
| Combien de factures le fournisseur Aubry nous a-t-il envoyées ? | 11 | ✅ 2 s · invoice_totals | ✅ 2 s · invoice_totals | ✅ 1 s · invoice_totals | ✅ 5 s · invoice_totals |
| Et parmi elles, combien sont déjà payées ? | 5 | ✅ 2 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 1 s · invoice_totals | ✅ 6 s · invoice_totals |
| Quel est le total HT des factures de la catégorie Informatique émises en 2026 ? | 126167.46 | ✅ 2 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 2 s · invoice_totals | ✅ 7 s · invoice_totals |
| Quel fournisseur a le plus gros montant TTC cumulé, et combien ? | Aubry, 295611.58 | ✅ 3 s · invoice_totals | ✅ 3 s · invoice_totals | ✅ 1 s · invoice_totals | ✅ 12 s · invoice_totals |
| Quels sont le client et le montant TTC de la facture A-2025-0010 ? | Muller, 22195.44 | ✅ 3 s · get_invoice | ✅ 2 s · get_invoice | ✅ 2 s · get_invoice | ✅ 13 s · get_invoice |
| Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro. | V-2025-0001 | ✅ 2 s · list_invoices | ✅ 3 s · list_invoices | ✅ 1 s · list_invoices | ✅ 7 s · list_invoices |
| Combien devons-nous encore payer au fournisseur Chevalier, et combien de cette somme est déjà échue ? | 41645.27, 41645.27 | ✅ 3 s · supplier_balance | ✅ 4 s · supplier_balance | ✅ 2 s · supplier_balance | ✅ 16 s · supplier_balance |
| Quel mois de 2026 a eu la plus grosse dépense TTC, et de combien ? | mai|2026-05, 87719.57 | ✅ 2 s · monthly_spend | ✅ 3 s · monthly_spend | ✅ 1 s · monthly_spend | ✅ 20 s · monthly_spend |
| Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ? | Disque SSD externe 2 To, 229 | ✅ 4 s · describe_schema → run_sql | ✅ 5 s · describe_schema → run_sql | ❌ 1 s · aucun outil | ✅ 38 s · run_sql✗ → describe_schema → run_sql |
| Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime. | 86.67 | ✅ 4 s · describe_schema → run_sql | ✅ 4 s · describe_schema → run_sql | ❌ 2 s · aucun outil | ❌ 8 s · list_invoices |
| **Score** | | **11/11** · 30 s | **11/11** · 33 s | **9/11** · 16 s | **10/11** · 141 s |

✗ après un nom d'outil = appel en erreur (le LLM a dû se corriger). 🔁 corrigé = la première réponse contenait un chiffre absent des résultats d'outils, et la vérification automatique l'a fait corriger. ⚠ non sourcé = chiffre toujours introuvable après correction (signalé à l'utilisateur).

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

> Oui, il y a une facture avec une anomalie détectée :
> - V-2025-0001
> 
> Source : list_invoices

**Combien devons-nous encore payer au fournisseur Chevalier, et combien de cette somme est déjà échue ?** — exacte (attendu : 41645.27, 41645.27)

> Nous devons encore payer 41 645,27 € au fournisseur Chevalier, et la totalité de cette somme (41 645,27 €) est déjà échue.
> 
> Source : supplier_balance

**Quel mois de 2026 a eu la plus grosse dépense TTC, et de combien ?** — exacte (attendu : mai|2026-05, 87719.57)

> Le mois de 2026 ayant eu la plus grosse dépense TTC est mai 2026, avec un montant de 87 719,57 €.
> 
> Source : monthly_spend

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
> Source : invoice_totals

**Et parmi elles, combien sont déjà payées ?** — exacte (attendu : 5)

> Parmi les 11 factures du fournisseur Aubry, 5 sont déjà payées.
> 
> Source : invoice_totals

**Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?** — exacte (attendu : 126167.46)

> Le total HT des factures de la catégorie Informatique émises en 2026 est de 126 167,46 €.
> 
> Source : invoice_totals

**Quel fournisseur a le plus gros montant TTC cumulé, et combien ?** — exacte (attendu : Aubry, 295611.58)

> Le fournisseur ayant le plus gros montant TTC cumulé est Aubry, avec un total TTC de 295 611,58 €.
> 
> Source : invoice_totals

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> Client : Muller  
> Montant TTC : 22 195,44 €  
> 
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Oui, il y a une facture avec une anomalie détectée : le numéro est V-2025-0001.
> 
> Source : list_invoices

**Combien devons-nous encore payer au fournisseur Chevalier, et combien de cette somme est déjà échue ?** — exacte (attendu : 41645.27, 41645.27)

> Nous devons encore payer au fournisseur Chevalier une somme totale de **41 645,27 €** (montant TTC restant à payer).
> 
> Parmi cette somme, **41 645,27 €** est déjà échue (toute la dette restante est en retard, comme indiqué par `overdue_ttc` et les données d'âge).
> 
> Source : supplier_balance

**Quel mois de 2026 a eu la plus grosse dépense TTC, et de combien ?** — exacte (attendu : mai|2026-05, 87719.57)

> Le mois de 2026 ayant eu la plus grosse dépense TTC est le mai 2026, pour un montant de 87 719,57 €.
> 
> Source : monthly_spend

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — exacte (attendu : Disque SSD externe 2 To, 229)

> Le désignation d'article commandé en plus grande quantité au total est "Disque SSD externe 2 To", avec un total de 229 unités.
> 
> Source : run_sql

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — exacte (attendu : 86.67)

> Le prix unitaire HT moyen de l'article « Cartouche toner noir » est de 86,67 €.
> 
> Source : run_sql

### hyperfluid-nemotron
**Quel est le montant TTC des factures en retard en 2025 ?** — exacte (attendu : 106886.43)

> Le montant TTC des factures en retard en 2025 est 106 886,43 €.
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

> Le fournisseur avec le plus gros montant TTC cumulé est Aubry, avec un total de 295 611,58 €.
> Source : invoice_totals

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> Le client de la facture A-2025-0010 est Muller et le montant TTC est 22 195,44 €.
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Il y a une facture avec une anomalie détectée : V-2025-0001.
> Source : list_invoices

**Combien devons-nous encore payer au fournisseur Chevalier, et combien de cette somme est déjà échue ?** — exacte (attendu : 41645.27, 41645.27)

> Nous devons encore payer **41 645,27 €** au fournisseur Chevalier, dont **41 645,27 €** est déjà échue.
> Source : supplier_balance

**Quel mois de 2026 a eu la plus grosse dépense TTC, et de combien ?** — exacte (attendu : mai|2026-05, 87719.57)

> Le mois de 2026 avec la plus grosse dépense TTC est mai, avec un total de 87 719,57 €.
> Source : monthly_spend

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — INEXACTE (attendu : Disque SSD externe 2 To, 229)

> Je ne dispose pas d'un outil qui me permette de connaître la désignation des articles commandés ni la quantité totale par article. Les outils disponibles se concentrent sur les informations de facturation (montants, statuts, fournisseurs, dates) et non sur le détail des lignes de commande ou des produits.
> 
> Source : Aucun outil utilisé

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — INEXACTE (attendu : 86.67)

> Je ne dispose pas d'un outil permettant de calculer le prix unitaire HT moyen d'un article spécifique comme « Cartouche toner noir ». Les outils disponibles permettent de lister des factures, d'obtenir des totaux par filtre (fournisseur, statut, date, etc.), de voir l'encours fournisseur ou les dépenses mensuelles, mais pas d'analyser le détail des lignes d'articles pour un calcul unitaire moyen.
> 
> Source : Aucun outil utilisé

### ollama-ministral
**Quel est le montant TTC des factures en retard en 2025 ?** — exacte (attendu : 106886.43)

> Le montant TTC des factures en retard en 2025 est de **106 886,43 €**.
> 
> Source : **invoice_totals**

**Combien de factures le fournisseur Aubry nous a-t-il envoyées ?** — exacte (attendu : 11)

> Le fournisseur **Aubry** nous a envoyé **11 factures**.
> 
> Source : **invoice_totals**

**Et parmi elles, combien sont déjà payées ?** — exacte (attendu : 5)

> Parmi les **11 factures** de **Aubry**, **5 sont déjà payées**.
> 
> Source : **invoice_totals**

**Quel est le total HT des factures de la catégorie Informatique émises en 2026 ?** — exacte (attendu : 126167.46)

> Le total HT des factures de la catégorie **Informatique** émises en 2026 est de **126 167,46 €**.
> 
> Source : **invoice_totals**

**Quel fournisseur a le plus gros montant TTC cumulé, et combien ?** — exacte (attendu : Aubry, 295611.58)

> Le fournisseur avec le plus gros montant TTC cumulé est **Aubry**, avec un total de **295 611,58 €**.
> 
> Source : `invoice_totals`

**Quels sont le client et le montant TTC de la facture A-2025-0010 ?** — exacte (attendu : Muller, 22195.44)

> La facture **A-2025-0010** est émise pour le client **Muller** et son montant TTC est de **22 195,44 €**.
> 
> Source : get_invoice

**Y a-t-il des factures avec une anomalie détectée ? Donne leur numéro.** — exacte (attendu : V-2025-0001)

> Oui, il y a **1 facture signalée** avec une anomalie détectée :
> 
> - **Numéro de facture** : V-2025-0001
> 
> Source : list_invoices

**Combien devons-nous encore payer au fournisseur Chevalier, et combien de cette somme est déjà échue ?** — exacte (attendu : 41645.27, 41645.27)

> Nous devons encore **91 446,76 €** au fournisseur Chevalier, dont **41 645,27 €** est déjà échue (toutes les factures en attente sont en retard).
> 
> **Détail de la balance âgée** :
> - 2757,86 € en retard de 31 à 60 jours
> - 5764,70 € en retard de 61 à 90 jours
> - 33122,71 € en retard de plus de 90 jours
> 
> Source : supplier_balance

**Quel mois de 2026 a eu la plus grosse dépense TTC, et de combien ?** — exacte (attendu : mai|2026-05, 87719.57)

> Le mois de 2026 avec la plus grosse dépense TTC est **mai**, avec un montant de **87 719,57 €**.
> 
> Source : monthly_spend

**Quel article (désignation) a été commandé en plus grande quantité au total, et combien d'unités ?** — exacte (attendu : Disque SSD externe 2 To, 229)

> Voici les **3 articles les plus fréquemment facturés** (quantités cumulées) :
> 1. **Disque SSD externe 2 To** : 229 unités
> 2. **Ordinateur portable Pro 14 pouces** : 223 unités
> 3. **Station d'accueil USB-C** :

**Quel est le prix unitaire HT moyen de l'article « Cartouche toner noir » ? Arrondis au centime.** — INEXACTE (attendu : 86.67)

> Aucune facture trouvée pour un fournisseur ou article nommé « toner noir » ou « Cartouche toner noir ».
> Si vous avez une autre référence ou un nom exact, précisez-la.
> 
> Source : **list_invoices**
