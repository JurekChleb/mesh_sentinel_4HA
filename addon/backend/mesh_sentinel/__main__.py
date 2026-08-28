"""Entry point: ``python -m mesh_sentinel``."""

from __future__ import annotations

import logging
import sys

import uvicorn

from . import __version__
from .api import create_app
from .config import load_settings


def main() -> int:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger(__name__).info(
        "Mesh Sentinel %s starting (edition=%s, retention=%sd, db=%s)",
        __version__,
        settings.edition,
        settings.effective_retention_days,
        settings.db_path,
    )
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
