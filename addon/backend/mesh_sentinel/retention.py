"""Retention. Free keeps 7 days; the cap lives in Settings."""

from __future__ import annotations

import logging

from .config import Settings
from .storage import Repository

_LOGGER = logging.getLogger(__name__)


def purge(repo: Repository, settings: Settings, now: float) -> dict[str, int]:
    cutoff = now - settings.effective_retention_days * 86400.0
    deleted = repo.purge_before(cutoff)
    total = sum(deleted.values())
    if total:
        _LOGGER.info(
            "Retention: removed %s rows older than %s days",
            total,
            settings.effective_retention_days,
        )
    return deleted
