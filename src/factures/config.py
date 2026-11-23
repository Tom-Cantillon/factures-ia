"""Configuration centralisée, lue depuis l'environnement (et le fichier .env, jamais commité)."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Chemins relatifs à DATA_DIR : le même code marche sur la machine, en conteneur et chez un collègue.
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
LANDING_DIR = DATA_DIR / "landing"

# S3 : les identifiants (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL,
# AWS_DEFAULT_REGION) sont lus directement par boto3 depuis l'environnement.
S3_BUCKET = os.getenv("S3_BUCKET", "factures")
