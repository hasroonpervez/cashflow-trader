"""seed instruments from watchlist and radar universe

Revision ID: 0002_seed_instruments
Revises: 0001_initial_schema
Create Date: 2026-08-11

Seeds the `instruments` registry with the union of the current watchlist
(config.json) and the radar universe (modules/config.py). first_seen is the
seed date; name/sector/industry are left NULL until fetched.
"""
from __future__ import annotations

from datetime import date

import sqlalchemy as sa
import alembic.op as op

revision = "0002_seed_instruments"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

_SYMBOLS = (
    "ABCL", "ABSI", "ACHR", "AFRM", "AGX", "AIT",
    "APLD", "ARQT", "ASTS", "BBAI", "BEAM", "BIGC",
    "BMNR", "BRZE", "BTC-USD", "BYND", "CFLT", "CHPT",
    "CIFR", "CLSK", "COIN", "CORZ", "CUBI", "DAVE",
    "DLX", "DNA", "DNLI", "DT", "DUOL", "ECG",
    "EDIT", "ENPH", "ENVX", "ESTC", "ETH-USD", "FREY",
    "FSBC", "GPUS", "GSAT", "GTLB", "GVA", "HIMS",
    "HOOD", "HUT", "IBRX", "IONQ", "IOT", "IREN",
    "JOBY", "KEEL", "LAZR", "LCID", "LILM", "LMND",
    "LUNR", "MARA", "MNDY", "NIO", "NOVA", "NTLA",
    "NUVL", "OPEN", "OUST", "PAHC", "PATH", "PLTR",
    "POWL", "QQQ", "QS", "QUBT", "RELY", "RF",
    "RGTI", "RIOT", "RIVN", "RKLB", "ROOT", "RUN",
    "RXRX", "S", "SANA", "SATL", "SEDG", "SIDU",
    "SMCI", "SOFI", "SOUN", "SPY", "SRFM", "SSB",
    "STRL", "TOST", "TSLA", "UPST", "VERV", "ZETA",
)


def upgrade() -> None:
    instruments = sa.table(
        "instruments",
        sa.column("symbol", sa.Text),
        sa.column("is_active", sa.Boolean),
        sa.column("first_seen", sa.Date),
    )
    rows = [
        {"symbol": s, "is_active": True, "first_seen": date(2026, 8, 11)}
        for s in _SYMBOLS
    ]
    op.bulk_insert(instruments, rows)


def downgrade() -> None:
    instruments = sa.table("instruments", sa.column("symbol", sa.Text))
    op.execute(
        sa.delete(instruments).where(instruments.c.symbol.in_(_SYMBOLS))
    )
