"""initial section-5 schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-11

Creates the full data model from ARCHITECTURE.md section 5:
12 tables, the materialized view, indexes, and year partitions for the
two range-partitioned tables so inserts can land.

DDL validated on the box inside a rollback transaction before this
migration was written.
"""
from __future__ import annotations

import alembic.op as op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

_SCHEMA = """
-- Ticker registry -----------------------------------------------------------
CREATE TABLE instruments (
  symbol            text PRIMARY KEY,
  name              text,
  exchange          text,
  sector            text,
  industry          text,
  is_active         boolean NOT NULL DEFAULT true,
  first_seen        date,
  created_at        timestamptz NOT NULL DEFAULT now()
);

-- Daily bars. Partition by year; BRIN index because inserts are time-ordered.
CREATE TABLE bars_daily (
  symbol            text NOT NULL REFERENCES instruments(symbol),
  as_of             date NOT NULL,
  open              numeric(18,6) NOT NULL,
  high              numeric(18,6) NOT NULL,
  low               numeric(18,6) NOT NULL,
  close             numeric(18,6) NOT NULL,
  volume            bigint,
  price_basis       text NOT NULL CHECK (price_basis IN ('adjusted','unadjusted')),
  source            text NOT NULL,
  ingested_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, as_of, price_basis)
) PARTITION BY RANGE (as_of);

CREATE INDEX ON bars_daily USING brin (as_of);

-- Point-in-time fundamentals. Never overwritten; a new snapshot is a new row.
CREATE TABLE fundamentals_snapshot (
  symbol            text NOT NULL REFERENCES instruments(symbol),
  as_of             date NOT NULL,
  market_cap        numeric,
  float_shares      numeric,
  short_interest_pct numeric,
  revenue_ttm       numeric,
  gross_margin      numeric,
  fcf_ttm           numeric,
  enterprise_value  numeric,
  payload           jsonb NOT NULL,
  source            text NOT NULL,
  ingested_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, as_of, source)
);

-- Options chains, one row per contract per snapshot.
CREATE TABLE options_snapshot (
  symbol            text NOT NULL,
  as_of             timestamptz NOT NULL,
  expiry            date NOT NULL,
  strike            numeric(18,6) NOT NULL,
  "right"           char(1) NOT NULL CHECK ("right" IN ('C','P')),
  bid               numeric, ask numeric, last numeric,
  volume            bigint, open_interest bigint,
  implied_vol       numeric,
  PRIMARY KEY (symbol, as_of, expiry, strike, "right")
) PARTITION BY RANGE (as_of);

-- Attention, stored over time so you can chart the cascade.
CREATE TABLE sentiment_snapshot (
  symbol            text NOT NULL,
  as_of             timestamptz NOT NULL,
  score             numeric,
  velocity          numeric,
  wilson            numeric,
  volume_z          numeric,
  trends_ratio      numeric,
  mentions          integer,
  stage             text,
  flags             text[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (symbol, as_of)
);

CREATE TABLE creator_mentions (
  id                bigserial PRIMARY KEY,
  symbol            text NOT NULL,
  source_id         text NOT NULL,
  source_name       text,
  published_at      timestamptz,
  direction         text,
  tier              text NOT NULL,
  title             text,
  url               text,
  ingested_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, url, symbol)
);

-- Every execution of a scan, successful or not.
CREATE TABLE scan_runs (
  id                bigserial PRIMARY KEY,
  kind              text NOT NULL,
  universe          text[] NOT NULL,
  config_hash       text NOT NULL,
  code_version      text NOT NULL,
  started_at        timestamptz NOT NULL,
  finished_at       timestamptz,
  status            text NOT NULL,
  error             text
);

-- Every signal ever fired. Append only.
CREATE TABLE signals (
  id                bigserial PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES scan_runs(id),
  symbol            text NOT NULL,
  as_of             timestamptz NOT NULL,
  signal_type       text NOT NULL,
  score             numeric,
  confidence        numeric,
  convexity_ratio   numeric,
  entry             numeric, stop numeric, target numeric,
  flags             text[] NOT NULL DEFAULT '{}',
  payload           jsonb NOT NULL,
  UNIQUE (run_id, symbol, signal_type)
);
CREATE INDEX ON signals (symbol, as_of DESC);
CREATE INDEX ON signals (signal_type, as_of DESC);

-- STAGE 2. This table is what turns "unvalidated" into a real claim.
CREATE TABLE signal_outcomes (
  signal_id         bigint NOT NULL REFERENCES signals(id),
  horizon_days      integer NOT NULL,
  forward_return    numeric,
  max_gain          numeric,
  max_drawdown      numeric,
  hit_2x            boolean,
  hit_5x            boolean,
  hit_10x           boolean,
  resolved_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (signal_id, horizon_days)
);

-- Positions and journal, replacing trade_journal.json.
CREATE TABLE positions (
  id                bigserial PRIMARY KEY,
  symbol            text NOT NULL,
  kind              text NOT NULL,
  opened_at         timestamptz NOT NULL,
  closed_at         timestamptz,
  quantity          numeric NOT NULL,
  entry_price       numeric NOT NULL,
  exit_price        numeric,
  strike            numeric, expiry date,
  premium_per_share numeric,
  close_convention  text,
  realized_pnl      numeric,
  signal_id         bigint REFERENCES signals(id),
  notes             text
);

-- Operational logs. This is the "logs" you asked for.
CREATE TABLE job_runs (
  id                bigserial PRIMARY KEY,
  job_name          text NOT NULL,
  started_at        timestamptz NOT NULL,
  finished_at       timestamptz,
  status            text NOT NULL,
  rows_written      integer,
  duration_ms       integer,
  error             text,
  detail            jsonb
);
CREATE INDEX ON job_runs (job_name, started_at DESC);

-- The honesty layer, carried forward from the audit.
CREATE TABLE data_quality_events (
  id                bigserial PRIMARY KEY,
  occurred_at       timestamptz NOT NULL DEFAULT now(),
  symbol            text,
  source            text NOT NULL,
  kind              text NOT NULL,
  detail            jsonb
);
"""

_MATVIEW = """
CREATE MATERIALIZED VIEW mv_dashboard_latest AS
SELECT DISTINCT ON (s.symbol, s.signal_type)
       s.symbol, s.signal_type, s.score, s.confidence, s.convexity_ratio,
       s.entry, s.stop, s.target, s.flags, s.payload, s.as_of,
       i.name, i.sector, f.market_cap, f.float_shares, f.short_interest_pct
FROM signals s
JOIN instruments i USING (symbol)
LEFT JOIN LATERAL (
  SELECT * FROM fundamentals_snapshot fs
  WHERE fs.symbol = s.symbol AND fs.as_of <= s.as_of::date
  ORDER BY fs.as_of DESC LIMIT 1
) f ON true
ORDER BY s.symbol, s.signal_type, s.as_of DESC;

CREATE UNIQUE INDEX ON mv_dashboard_latest (symbol, signal_type);
"""

# Year partitions for the range-partitioned tables. The whole universe is
# backfilled for two years (step 3); this window covers that plus headroom.
_PARTITIONS = """
CREATE TABLE bars_daily_y2024 PARTITION OF bars_daily
  FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE bars_daily_y2025 PARTITION OF bars_daily
  FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE bars_daily_y2026 PARTITION OF bars_daily
  FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
CREATE TABLE bars_daily_y2027 PARTITION OF bars_daily
  FOR VALUES FROM ('2027-01-01') TO ('2028-01-01');
CREATE TABLE options_p2024 PARTITION OF options_snapshot
  FOR VALUES FROM ('2024-01-01 00:00:00+00') TO ('2025-01-01 00:00:00+00');
CREATE TABLE options_p2025 PARTITION OF options_snapshot
  FOR VALUES FROM ('2025-01-01 00:00:00+00') TO ('2026-01-01 00:00:00+00');
CREATE TABLE options_p2026 PARTITION OF options_snapshot
  FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');
CREATE TABLE options_p2027 PARTITION OF options_snapshot
  FOR VALUES FROM ('2027-01-01 00:00:00+00') TO ('2028-01-01 00:00:00+00');
"""


def _exec(sql: str) -> None:
    """Run a DDL block statement by statement.

    asyncpg does not allow multiple commands in one prepared statement, so a
    whole-block op.execute fails. Split on ';' (the schema contains no
    semicolons inside string literals, verified during rollback validation).
    """
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt + ";")


def upgrade() -> None:
    _exec(_SCHEMA)
    _exec(_PARTITIONS)
    _exec(_MATVIEW)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dashboard_latest CASCADE;")
    for t in (
        "data_quality_events",
        "job_runs",
        "positions",
        "signal_outcomes",
        "signals",
        "scan_runs",
        "creator_mentions",
        "sentiment_snapshot",
        "options_snapshot",
        "fundamentals_snapshot",
        "bars_daily",
        "instruments",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")