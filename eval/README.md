# Évaluation de l'OCR (étape 5)

```bash
uv run factures eval --sides 512 768 1540 --synthetic   # → eval/results.md
```

Les sorties OCR sont mises en cache dans `data/eval/`. Relancer la commande recalcule les scores sans
refaire aucun appel. Pour refaire les appels, supprimer `data/eval/`.

## Deux vérités terrain complémentaires

### 1. Scans réels — `ground_truth.json` (20 factures)

- **Échantillon** : 20 scans sur 50, tirés au sort avec une graine fixe (42). Le tirage est réparti
  entre les 8 fournisseurs, dont chacun a sa propre mise en page de valeurs (`sample_scans`).
- **Méthode** : pré-remplissage avec la sortie du pipeline, puis vérification visuelle de **chaque
  champ** sur l'image du scan rendue à 120–130 dpi. Désaccords trouvés : 0.
- **Contrôles indépendants** : sur ces 20 factures, l'IBAN passe la clé mod 97, et
  HT + TVA = TTC comme somme des lignes = HT. Une erreur de transcription casserait ces égalités.
- **Limite assumée** : le pré-remplissage peut biaiser le vérificateur vers l'acceptation. C'est la
  raison d'être du jeu synthétique, dont la vérité ne doit rien à l'OCR.

### 2. Faux scans synthétiques (50 factures)

Les 50 PDF **natifs** sont rendus en image puis dégradés pour ressembler à un scan : niveaux de gris,
rotation de ±1,5°, flou, bruit, compression JPEG (`evaluate.degrade`, graine fixe par fichier). Leur
vérité terrain est la couche texte du PDF : elle est **exacte, gratuite et indépendante de l'OCR**. Cette
méthode répond à la question « comment obtenir une vérité terrain fiable sans y passer des heures ? ».
Elle passe à l'échelle : on peut générer autant de faux scans qu'on veut.

## Champs mesurés

`invoice_number`, `issue_date`, `due_date`, `supplier_name`, `supplier_siret`, `supplier_vat_number`,
`client_name`, `client_siret`, `category`, `status`, `payment_method`, `iban`, `total_ht`, `total_tva`,
`total_ttc`, `line_count`, et `lines` (toutes les lignes exactes : désignation, quantité, PU, taux, total).

La comparaison est **exacte** après normalisation (espaces, montants en `Decimal`, dates ISO). Un
centime ou un chiffre faux compte comme une erreur. On mesure aussi la part de factures dont **tous**
les champs sont exacts, ce qui compte en pratique : une facture avec un seul champ faux doit être
reprise à la main.

## Taille d'échantillon

Avec n = 20, un taux observé de 100 % donne un intervalle de confiance à 95 % de [83 %, 100 %]
(règle de trois : 3/n ≈ 15 %). On ne peut donc pas distinguer 98 % de 100 % sur 20 factures. Avec
les 50 faux scans, la borne basse remonte à environ 94 %. Pour détecter des écarts de l'ordre de 1 %
entre deux réglages, il faudrait plusieurs centaines de documents, d'où l'intérêt du générateur
synthétique.

## Résultats (23/11/2026) — détail complet dans [results.md](results.md)

| Facture 100 % exacte | 512 px | 768 px | **1540 px** (production) |
|---|---:|---:|---:|
| Scans réels (n = 20) | 0/20 | 18/20 | **20/20** |
| Faux scans synthétiques (n = 50) | 0/50 | 4/50 | **50/50** |
| Temps OCR moyen / page | 5,5–7,8 s | 5,3–5,5 s | 7,4–8,2 s |

La couche silver (pipeline de production, 1540 px) est exacte sur **100 % des champs des 20 scans
réels**. Le ré-OCR à 1540 px donne le même résultat : malgré `temperature=0.2`, la sortie est stable
sur ce jeu.

## Analyse

**La résolution recommandée par la fiche du modèle n'est pas un détail.** À 512 px, le modèle
« lit » encore une facture, mais invente des chiffres (`A-2035-0010` pour `A-2025-0010`, SIRET
`77395260208050`) et des mots plausibles (`Financières` pour `Fournitures`, `Faury` pour `Fleury`).
Aucune facture n'est exacte. À 768 px, les scans réels passent presque tous, mais les faux scans,
plus dégradés (flou, bruit, JPEG), tombent à 4/50. À 1540 px, tout est exact sur les deux jeux.
Le gain de vitesse à 768 px (environ 30 %) ne vaut pas le risque.

**Les champs les plus fragiles** (à 768 px, sur les faux scans) :
- **les longues suites de chiffres** : IBAN 48 %, n° de TVA 64 %, SIRET 74–82 %. Un seul chiffre
  confondu (6↔8, 3↔2, 0↔9) rend le champ faux, et rien dans le contexte ne permet au modèle de
  le deviner ;
- **les noms propres** : client 74 % (`Chauvin` → `Chacuin`, `Torres` → `Tomes`). Ce ne sont pas
  des mots du dictionnaire, donc le modèle de langue n'aide pas ;
- **la structure du tableau** : lignes exactes 46 %, nombre de lignes 60 %, total HT 60 %. Quand le
  modèle rate la structure du tableau, le parseur ne retrouve plus les cellules. C'est une erreur de
  mise en page plus que de caractères.

**Les champs robustes** : statut, catégorie, mode de paiement (vocabulaire fermé, que le modèle
« complète » juste), date d'émission, et **total TTC** (en gras et plus gros : 100 % même à 768 px).

**Les contrôles qualité rattrapent la plupart des erreurs d'OCR.** Sur les factures fausses à
768 px (faux scans), 39 sur 46 sont **signalées** par la silver (clé IBAN invalide, HT + TVA ≠ TTC,
total HT illisible…). Seules 7 passent inaperçues. Ce sont des erreurs sur des champs sans clé de
contrôle : nom, SIRET d'un jeu fictif, n° de facture. À 512 px, 62 sur 70 sont même **rejetées**.
D'où deux leçons :
1. les contrôles arithmétiques et les clés de contrôle (IBAN) sont un filet de sécurité efficace
   contre l'OCR. Il faudrait activer la clé de Luhn du SIRET sur des données réelles ;
2. noms et identifiants sans clé restent le point aveugle. Pistes : un référentiel fournisseurs /
   clients (SIRET connu ↔ nom), ou un second OCR en cas de désaccord.

**Le jeu synthétique est plus dur que le réel.** La dégradation choisie (flou, bruit, JPEG
qualité 55–75) est plus forte que celle des vrais scans. C'est voulu : un réglage qui passe le
synthétique passe a fortiori le réel. Sa vérité terrain ne doit rien à l'OCR, ce qui corrige le biais
possible du pré-remplissage du jeu réel.
