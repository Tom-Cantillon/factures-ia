# Journal de mesures — OCR (étape 2)

Mesures du 23/11/2026, modèle `lightonocr-3-1b-test` (LightOnOCR-3-1B servi par vLLM, AI Gateway Hyperfluid).

## Format de requête (fiche du modèle)

- Un seul message `user`, contenant **uniquement** l'image (`image_url` en data-URI PNG base64), sans texte.
  Un prompt texte vide déclenche la transcription. Tout autre texte est hors distribution : un premier
  essai avec « Hello » et sans image a produit une phrase sans rapport.
- Paramètres recommandés : `temperature=0.2`, `top_p=0.9`, `max_tokens=4096`.
- Rendu recommandé : plus grand côté ≈ **1540 px**, ratio conservé.

## Format de sortie

- **Markdown** : `# FACTURE`, champs en `**gras**` (`**Numéro de facture** : A-2025-0003`), séparateurs `---`.
- **Tableaux en HTML** (`<table><thead><tr><th>…`), pas en markdown.
- Le texte d'un PDF natif (couche texte PyMuPDF) a une tout autre forme : une valeur par ligne, sans
  balisage, avec les cellules du tableau à la suite. Le parseur silver (étape 4) devra gérer les deux.
- Exemple complet de sortie : `uv run factures ocr facture_A-2025-0003_scan.pdf`.

## Temps de traitement selon la taille de l'image

Même page (`facture_A-2025-0003_scan.pdf`, A4), un appel par taille :

| Plus grand côté | PNG envoyé | Tokens image | Tokens produits | Temps OCR |
|---:|---:|---:|---:|---:|
| 768 px  |  242 Ko |  572 | 462 | 4,2 s |
| 1024 px |  480 Ko |  974 | 492 | 5,0 s |
| **1540 px** | 1108 Ko | 2157 | 465–492 | **5,6–6,6 s** |
| 2048 px | 1964 Ko | 2157 | 492 | 7,4 s |

Observations :
- Le temps est dominé par la **génération** (~470–490 tokens produits) : il varie peu avec la taille d'image.
- Au-delà de 1540 px, le nombre de tokens image **plafonne à 2157** : le serveur redimensionne. Envoyer
  plus grand ne coûte que du transfert réseau (2 Mo) sans rien apporter au modèle.
- À 1540 px, deux appels identiques ont produit 465 et 492 tokens : avec `temperature=0.2`, la sortie
  n'est **pas strictement déterministe**. À garder en tête pour l'évaluation (étape 5).
- La qualité selon la taille sera mesurée champ par champ à l'étape 5 (768 vs 1540 px).
- Ordre de grandeur : **~6 s par page**, soit ~5 min pour les 50 scans en séquentiel.
