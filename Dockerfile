# Image unique du projet : pipeline (factures …), serveur MCP (factures-mcp) et interface web.
# Les secrets ne sont JAMAIS copiés dans l'image : ils arrivent par variables d'environnement à
# l'exécution (env_file en local, gestionnaire de secrets en production).
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 1) Dépendances seules (couche mise en cache tant que uv.lock ne change pas)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

# 2) Code du projet
COPY src ./src
COPY llm_profiles.toml ./
RUN uv sync --frozen

# Utilisateur non root ; les données vivent dans un volume, hors de l'image
RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME ["/data"]

ENTRYPOINT ["factures"]
CMD ["status"]
