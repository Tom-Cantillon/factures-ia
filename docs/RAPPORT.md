# De la facture scannée à l'agent IA

**Rapport de projet — MLOps (S9)** · Auteur(s) : _à compléter_ · 23 novembre 2026  
Dépôt : `factures-ia` — lancement : `README.md` · détails techniques : `docs/`, `eval/`

## 1. Objectif et résultat

L'entreprise reçoit des factures fournisseurs en PDF. La moitié sont des scans, sans couche texte, et
elles sont aujourd'hui ressaisies à la main. Nous avons construit une chaîne reproductible qui récupère
les PDF sur S3, les lit (couche texte ou OCR LightOnOCR-3), les range en couches **bronze** puis
**silver** contrôlées, les expose en **SQL**, puis à une IA via un **serveur MCP**. Un **agent** répond
ensuite en français aux questions métier, et le LLM qui l'anime se change par simple configuration.

Sur les 100 factures fournies :
- 50 ont été lues par OCR, 50 par leur couche texte ;
- 100 factures et 271 lignes sont en silver ;
- 1 anomalie volontaire du jeu a été détectée ;
- la question de l'énoncé, « montant TTC des factures en retard en 2025 », reçoit la réponse
  **106 886,43 €** (12 factures), identique avec un LLM hébergé et un LLM local, et vérifiée par SQL.

L'historique Git compte un commit par étape, et 38 tests automatisés sont lancés par la CI. Tout se
pilote avec des commandes `uv run factures …`, ou avec `docker compose`.

## 2. Architecture et choix techniques

```
 S3 "factures" ─ fetch ─► landing ─ detect ─┬─ couche texte (PyMuPDF) ─┐
 (Hyperfluid)  incrémental   (texte/image)   └─ OCR LightOnOCR-3 ──────┤  AI Gateway Hyperfluid (vLLM)
                                                                       ▼
                       bronze (Parquet, append-only, SHA-256, run_id, paramètres OCR, erreurs)
                                                                       │ parseur unique + contrôles
                       silver : invoices · invoice_lines · quarantine (DECIMAL, DATE, statut qualité)
                                                                       │ vues SQL, aucune copie
                       entrepôt DuckDB (vues sur Parquet) ◄── DBeaver (fichier de vues, lecture seule)
                                                                       │
                       serveur MCP (5 outils, lecture seule, SQL renvoyé) ── stdio / HTTP
                                    │                     │
               agent (LLM choisi par config)    Claude Code / Desktop      interface web (Streamlit)
```

| Brique | Choix | Justification |
|---|---|---|
| Langage, environnement | Python 3.13, **uv** (`uv.lock`) | écosystème données et IA ; environnement **reproductible** à l'octet près, installé en une commande. Python 3.15, installé sur le poste, n'avait pas encore les paquets compilés de plusieurs dépendances, d'où une version fixée (`.python-version`). |
| Accès S3 | boto3, variables `AWS_*` standard | lues sans code par boto3 et la CLI `aws` ; clé **en lecture seule** limitée au bucket |
| Texte / image, rendu | PyMuPDF | une seule bibliothèque pour lire la couche texte, compter les images et rendre les pages en PNG |
| OCR | LightOnOCR-3 via client OpenAI | API compatible OpenAI. Le code ne dépend que d'une interface `OcrEngine` (PNG → texte) : changer de moteur revient à écrire une classe |
| Stockage | **Parquet** | colonnaire, typé (`DECIMAL`, `DATE`, listes), immuable, lisible par tous les moteurs SQL ; fichiers ajoutés, jamais modifiés |
| Calcul SQL | **DuckDB** | moteur analytique embarqué, sans serveur, qui lit Parquet nativement ; pilote DBeaver ; bac à sable de sécurité intégré |
| MCP | SDK officiel `mcp` (2.x) | protocole standard, transports stdio et HTTP, erreurs typées pour le LLM |
| Agent | boucle maison sur l'API « chat completions » | format d'appel d'outils compris par vLLM, Ollama, OpenAI, Mistral… : le LLM devient un **profil** dans `llm_profiles.toml`, pas du code |
| Interface | Streamlit | uniquement du Python ; chat, tableaux et filtres, en réutilisant l'agent et l'entrepôt |

**Bronze.** Un document est identifié par le **SHA-256 de son contenu**, pas par son nom : un fichier
renommé n'est pas retraité, un fichier remplacé l'est. Chaque ligne garde l'URI S3, l'ETag, la méthode
par page, le texte brut, le modèle et les paramètres OCR exacts, les tokens, les durées, le `run_id` et
la version du pipeline. On peut ainsi remonter de n'importe quel montant au PDF et à l'appel qui l'a
produit. La bronze n'est **jamais modifiée** : elle est la preuve de ce qui a été lu. Si le parseur
évolue, on la relit sans refaire d'OCR, qui est coûteux et ne donne pas toujours le même résultat.

Les échecs sont gérés ainsi : 3 tentatives avec un délai croissant ; pas de nouvel essai pour une
erreur d'authentification ; un **coupe-circuit** arrête les appels après 3 échecs consécutifs ; chaque
échec est journalisé dans `extraction_errors`, et le document est retraité au run suivant.
Vérifications :
- une panne simulée de l'OCR n'a fait perdre aucun PDF texte, et les scans ont été rattrapés ;
- un second run n'ajoute rien et ne fait **aucun appel OCR**.

**Silver.** Le texte natif (une valeur par ligne) et la sortie OCR (markdown, tableaux HTML, totaux
tantôt en lignes, tantôt en tableau) sont d'abord **normalisés** en un même flux de lignes, puis lus par
**un seul parseur**. Résultat : aucun champ manquant sur 100 factures. Les montants sont des
**`Decimal` / `DECIMAL(14,2)`**, jamais des flottants : un flottant binaire ne représente pas 0,10
exactement, et les comparaisons au centime échouent.

Les contrôles distinguent deux issues :
- **le rejet** (table `quarantine`) : la facture est inexploitable (numéro, client, date ou TTC
  manquant ou illisible) ou c'est un **doublon**. Une facture comptée deux fois fausse les totaux ;
- **le signalement** (`quality_status = 'signalee'`) : la facture est gardée, avec ses anomalies. Les
  règles portent sur HT + TVA ≠ TTC, la somme des lignes, quantité × prix, la TVA par taux, la clé
  IBAN, l'échéance antérieure à l'émission et les valeurs inconnues.

**Rien n'est corrigé automatiquement.** Un montant recalculé ressemble à une donnée vraie mais n'en est
pas une : il masquerait l'erreur et pourrait conduire à un mauvais paiement. Un humain tranche.

Sur le jeu fourni, le contrôle a trouvé l'anomalie glissée par l'enseignant : `V-2025-0001` affiche
un TTC de 99 999,99 € pour HT 148,26 € + TVA 29,65 €. Nous avons vérifié sur l'image que l'erreur est
dans le document, pas dans l'OCR. Nous avons aussi cherché d'autres anomalies (doublons déguisés,
changements d'IBAN, numérotation, dates, valeurs aberrantes) sans en trouver.

**Entrepôt.** L'entrepôt ne contient que des **vues** sur les Parquet : stockage et calcul sont
séparés, et les données n'existent qu'en un exemplaire. Un fichier DuckDB ouvert en écriture est
**verrouillé** par son processus, ce que nous avons vérifié. C'est pourquoi les programmes ouvrent
chacun une base DuckDB **en mémoire** (aucun verrou partagé), tandis que DBeaver ouvre un petit fichier
de vues généré par `factures warehouse`. Les chemins sont calculés à partir de `DATA_DIR` au moment de
la connexion ou de la génération. Le cas réel l'a confirmé : un fichier généré dans un conteneur
pointe vers `/data` et ne vaut que là. On le régénère là où on le consulte.

**Serveur MCP.** Il expose cinq outils : `list_invoices`, `invoice_totals`, `get_invoice`,
`describe_schema` et `run_sql`. Chaque réponse contient le **SQL réellement exécuté et ses
paramètres**.

Les descriptions disent *quand* utiliser chaque outil, avec les valeurs et formats attendus.

Les arguments venant d'un LLM ne sont pas fiables : les filtres sont passés en **paramètres liés**, et
les colonnes de tri viennent d'une liste fermée. Testé : `x' OR '1'='1` est traité comme un simple
texte.

`run_sql` empile **quatre barrières** :
1. une seule instruction, de type `SELECT`, selon l'analyseur de DuckDB lui-même ;
2. une connexion jetable à chaque appel ;
3. le bac à sable de DuckDB : fichiers limités à l'entrepôt, pas d'extension, configuration verrouillée ;
4. un plafond de lignes et un délai maximal.

La barrière 1 est indispensable : en test, le bac à sable seul a laissé un `COPY` écrire dans
`data/silver`. Le script de test appelle chaque outil sur un vrai client MCP en stdio, puis tente
12 attaques : toutes sont refusées et aucun fichier n'est modifié.

Les erreurs contiennent un indice (valeurs permises, numéros proches, colonnes candidates) pour que le
LLM se corrige. Le serveur a été branché sur Claude Code via `.mcp.json`.

## 3. Évaluation de l'OCR

**Vérité terrain.** Nous en avons constitué deux, complémentaires :
- **20 scans réels**, tirés au sort avec une graine fixe et répartis entre les 8 fournisseurs. Chaque
  champ a été vérifié sur l'image : 0 désaccord. La cohérence arithmétique et la clé IBAN servent de
  contrôles indépendants ;
- **50 faux scans** : les PDF natifs rendus en image puis dégradés (gris, rotation, flou, bruit, JPEG).
  Leur vérité, la couche texte, est **exacte, gratuite et indépendante de l'OCR**. C'est notre réponse
  à « une vérité terrain fiable sans y passer des heures », et cela passe à l'échelle.

On mesure 17 champs, comparés exactement après normalisation, dont l'ensemble des lignes de la
facture. On compte aussi les factures exactes à 100 %, qui seules évitent une reprise manuelle.
La commande `uv run factures eval --sides 512 768 1540 --synthetic` reproduit tout, avec un cache des
sorties OCR.

| Factures 100 % exactes | 512 px | 768 px | **1540 px** (recommandé, production) |
|---|---:|---:|---:|
| Scans réels (n = 20) | 0/20 | 18/20 | **20/20** |
| Faux scans (n = 50) | 0/50 | 4/50 | **50/50** |
| Temps OCR moyen par page | 5,5–7,8 s | 5,3–5,5 s | 7,4–8,2 s |

| Champ (faux scans, 768 px) | IBAN | n° TVA | SIRET | client | lignes | total HT | statut, catégorie | **total TTC** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Exactitude | 48 % | 64 % | 74–82 % | 74 % | 46 % | 60 % | 98–100 % | **100 %** |

**Analyse.**
1. **La résolution de la fiche du modèle (1540 px) est décisive.** À 512 px, le modèle invente des
   valeurs plausibles (`A-2035-0010` au lieu de `A-2025-0010`, `Financières` au lieu de
   `Fournitures`). À 768 px, il casse dès que le scan est dégradé. Le temps est dominé par la
   génération, pas par l'image : 768 px ne fait gagner qu'environ 30 %. Au-delà de 1540 px, le serveur
   réduit l'image, qui coûte toujours 2 157 tokens.
2. **Les champs fragiles** sont les longues suites de chiffres sans contexte (un 6 lu 8 suffit), les
   noms propres (`Chauvin` → `Chacuin`, hors dictionnaire) et la **structure du tableau** : quand elle
   est ratée, le parseur ne retrouve plus les cellules. Les champs robustes ont un vocabulaire fermé,
   ou sont mis en valeur comme le TTC en gras.
3. **Les contrôles silver rattrapent la plupart des erreurs d'OCR.** À 768 px, 39 des 46 factures
   fausses sont signalées (IBAN invalide, totaux incohérents…) et seules 7 passent inaperçues. Le
   point aveugle reste les noms et identifiants sans clé de contrôle.
4. **Taille d'échantillon.** 20/20 ne prouve qu'un taux d'au moins 83 % environ, avec un intervalle à
   95 %. Les 50 faux scans portent la borne à environ 94 %. Comparer finement deux réglages
   demanderait des centaines de documents, d'où l'intérêt du générateur.

## 4. Agent et LLM interchangeables

L'agent lance le serveur MCP et **n'a accès aux données que par ses outils**. Pour chaque étape, il
affiche l'outil, les arguments, le SQL et un aperçu du résultat. Il garde l'historique, borne sa
boucle à 8 appels au LLM par question et annule proprement un tour si le LLM ne répond pas.

Pour l'empêcher d'**inventer des chiffres** :
- le prompt système impose de recopier les chiffres renvoyés par les outils et interdit tout calcul
  de tête ;
- les calculs sont faits en SQL par le serveur ;
- la réponse cite sa source.

La même question a été posée à quatre LLM **sans changer le code** (`--llm`). Les réponses attendues
sont calculées par une requête SQL directe sur l'entrepôt (`uv run factures agent-bench`) :

| 9 questions | Gemma 4 12B | Granite 4.2 8B | Nemotron E4B | Ministral 3 8B (local) |
|---|---:|---:|---:|---:|
| 7 couvertes par un outil (dont une qui fait appel à la mémoire) | 7/7 | 7/7 | 7/7 | 7/7 |
| 2 demandant du SQL libre | 2/2 | 2/2 | 0/2 | 0/2 |
| Temps total | 26 s | 28 s | 14 s | 92 s |

Les trois premiers modèles sont hébergés sur l'AI Gateway Hyperfluid ; Ministral tourne sur le Mac.

**Observations.**
- **Avec des outils métier, un modèle de 8B suffit.** La difficulté est déplacée vers le serveur.
  Exemple : les quatre modèles écrivaient `en retard` au lieu de `En retard`, et le serveur accepte
  maintenant cette variante.
- **Le SQL libre sépare les modèles.** Nemotron refuse honnêtement. Ministral répond à une **autre
  question** (« toner noir » pris pour un fournisseur) : c'est le cas le plus dangereux, car la
  réponse paraît sérieuse. **Aucun modèle n'a inventé de chiffre.**
- **Le modèle local est 4 à 15 fois plus lent**, et sa latence augmente avec l'historique.
- Nous avons aussi dû vérifier notre propre vérificateur : il comptait « 229,000 unités » (une
  quantité `DECIMAL(14,3)`) comme fausse.

## 5. Industrialisation (résumé de `docs/INDUSTRIALISATION.md`)

5 000 factures par mois ne représentent qu'environ 1 h 30 d'OCR : **le volume n'est pas le
problème.** Les vrais risques sont la sécurité, la fiabilité et l'exploitation. Nos priorités, dans
l'ordre :

1. **Sécurité.**
   - Secrets dans un gestionnaire avec rotation, clés au moindre privilège.
   - Authentification OAuth sur le MCP HTTP, avec un journal d'audit du SQL par utilisateur.
   - Défense contre l'injection de prompt : le texte des factures vient de tiers, donc l'agent ne lit
     que des données structurées et n'a aucun outil à effet de bord.
   - Alerte bloquante sur un changement d'IBAN fournisseur.
2. **Automatisation.**
   - Notification S3, file de messages, workers en conteneur.
   - C'est sûr parce que le pipeline est déjà **idempotent** (SHA-256, append-only, écritures
     atomiques).
   - File de revue humaine pour la quarantaine, qui alimente la vérité terrain.
3. **Montée en charge.**
   - Réplicas vLLM avec autoscaling sur la file d'attente.
   - Parquet → **Iceberg** sur S3 (ACID, *time travel* pour l'audit), silver incrémentale.
   - DuckDB, puis Trino si la concurrence l'exige.
4. **Non-régression.** `factures eval` et `factures agent-bench` deviennent des seuils bloquants en
   CI lors d'un changement de modèle OCR ou LLM ; on ajoute des tests de contrat par mise en page de
   fournisseur.
5. **Supervision.** Fraîcheur, latence et erreurs OCR, et surtout **taux de signalement par
   fournisseur**, qui révèle une nouvelle mise en page ou un OCR dégradé.
6. **Coûts.** Les PDF natifs ne coûtent rien grâce à la détection texte / image. Côté LLM, un petit
   modèle traite les questions courantes et un grand est réservé au SQL libre.

**Implémenté** :
- un `Dockerfile` (non-root, sans secret) et un `compose.yaml` avec trois services : pipeline, MCP
  HTTP sur un conteneur en lecture seule, interface. Tout a été vérifié de bout en bout en conteneur ;
- une CI GitHub Actions (tests et construction de l'image) ;
- le serveur MCP en HTTP, partageable entre plusieurs utilisateurs ;
- une **interface web locale** : chat avec la trace des outils et du SQL, exploration des factures,
  page qualité.

## 6. Difficultés, limites et pistes

**Difficultés rencontrées.**
- La **clé d'API** au scope `model:inference` était refusée (403) sur les modèles partagés ; il a fallu
  `model:*`.
- Le jeton de session de la console expire en quelques minutes et n'est pas une clé d'API.
- **Python 3.15** n'avait pas encore les paquets compilés de plusieurs dépendances : version fixée à 3.13.
- Le **SDK MCP 2.x** a renommé son API (`FastMCP` → `MCPServer`), et **DuckDB 2.0** a retiré
  `fetchone()` sur les relations.
- Le **bac à sable DuckDB seul ne suffit pas** à garantir la lecture seule : le `COPY` est passé.
- Les **SIRET du jeu sont fictifs** : 7 % seulement respectent la clé de Luhn (14 sur 200). L'exiger aurait signalé
  100 % des factures, d'où un contrôle limité au format.
- Gemma laisse passer ses jetons de « réflexion » ; nous les filtrons.
- La passerelle a eu une coupure pendant un banc d'essai, gérée sans plantage.

**Limites.**
- Le parseur suppose la mise en page des 8 fournisseurs du jeu. Une nouvelle mise en page donnerait
  des quarantaines, visibles mais à traiter.
- La vérité terrain réelle a été pré-remplie par l'OCR, puis vérifiée : un biais vers l'acceptation
  est possible. C'est ce que compense le jeu synthétique.
- 20 scans réels donnent une précision statistique limitée.
- Le serveur MCP HTTP n'a pas d'authentification : il est exposé seulement en local.
- La silver est recalculée entièrement à chaque fois, ce qui convient jusqu'à environ 100 000 factures.
- Aucun contrôle ne relie un nom à un SIRET de référence.

**Pistes.**
- Un parseur fondé sur la sortie *grounding* de LightOnOCR (blocs étiquetés), ou une extraction par
  LLM avec schéma, plus robuste aux nouvelles mises en page.
- Un référentiel fournisseurs (nom ↔ SIRET ↔ IBAN) pour les contrôles et la détection de fraude.
- Une couche **gold** (chiffre d'affaires mensuel, encours par fournisseur) et ses outils MCP.
- La comparaison de LightOnOCR à un second moteur d'OCR, rendue facile par l'interface `OcrEngine`.
- Un second OCR en cas de désaccord avec les contrôles.
