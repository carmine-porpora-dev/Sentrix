import os
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.data.paths import REPO_ROOT

DEFAULT_FRONTEND_DIR = REPO_ROOT / "frontend" / "dist"
HASHED_DIR = "assets"  # la cartella dei file con l'hash nel nome (Vite)
CACHE_HASHED = "public, max-age=31536000, immutable"
CACHE_REVALIDATE = "no-cache"  # si può tenere, ma va riconfermata a ogni visita


class _Frontend(StaticFiles):
    async def check_config(self) -> None:
        """Starlette, alla prima richiesta, solleva un errore (500) se la cartella non c'è. Qui
        non è un errore: senza `dist` ogni percorso non-API è un 404."""

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        hashed = Path(full_path).parent.name == HASHED_DIR
        response.headers["Cache-Control"] = CACHE_HASHED if hashed else CACHE_REVALIDATE
        return response


def mount_frontend(app: FastAPI, directory: Path) -> None:
    """`check_dir=False`: nessun accesso al disco qui (`create_app` non ne fa)."""
    app.router.default = _Frontend(directory=directory, html=True, check_dir=False)
