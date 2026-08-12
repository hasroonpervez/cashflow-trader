"""Database connection configuration.

The connection string is read from the CASHFLOW_DATABASE_URL environment
variable. No default DSN with credentials is embedded in code; the box runbook
(ops/README.md) documents what to export.
"""
from __future__ import annotations

import os

ENV_URL = "CASHFLOW_DATABASE_URL"


def database_url() -> str:
    url = os.environ.get(ENV_URL, "").strip()
    if not url:
        raise RuntimeError(
            f"{ENV_URL} is not set. Example: "
            "postgresql+asyncpg://cft:password@127.0.0.1:5432/cft"
        )
    return url
