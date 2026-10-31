from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


NEO4J_URI = env("NEO4J_URI")
NEO4J_USERNAME = env("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = env("NEO4J_PASSWORD")
NEO4J_DATABASE = env("NEO4J_DATABASE") or None

DAYTONA_API_KEY = env("DAYTONA_API_KEY")
DAYTONA_API_URL = env("DAYTONA_API_URL")
DAYTONA_TARGET = env("DAYTONA_TARGET")
# Off by default: the demo must prove execution happened in Daytona.
ALLOW_LOCAL_EXECUTION = env("ALLOW_LOCAL_EXECUTION", "false").lower() in ("1", "true", "yes")

NOSANA_LLM_URL = env("NOSANA_LLM_URL").rstrip("/")
NOSANA_LLM_MODEL = env("NOSANA_LLM_MODEL")
# Platform key (api.nosana.com) used only by scripts/nosana.py to manage the deployment.
# It is never sent to the model endpoint, which runs on a third-party GPU node.
NOSANA_API_KEY = env("NOSANA_API_KEY")
NOSANA_LLM_KEY = env("NOSANA_LLM_KEY")
