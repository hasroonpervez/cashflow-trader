"""SQLAlchemy 2.0 typed models for the section-5 schema.

Mirrors db/migrations/versions/*_initial_schema.py exactly. Partitioned
tables (bars_daily, options_snapshot) are declared with their partition key;
partitions themselves are created by the migration's raw DDL.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    exchange: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    first_seen: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BarDaily(Base):
    __tablename__ = "bars_daily"
    __table_args__ = (
        CheckConstraint("price_basis IN ('adjusted','unadjusted')", name="ck_bars_daily_price_basis"),
        Index("ix_bars_daily_as_of_brin", "as_of", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (as_of)"},
    )

    symbol: Mapped[str] = mapped_column(
        Text, ForeignKey("instruments.symbol"), primary_key=True
    )
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    price_basis: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class FundamentalsSnapshot(Base):
    __tablename__ = "fundamentals_snapshot"

    symbol: Mapped[str] = mapped_column(
        Text, ForeignKey("instruments.symbol"), primary_key=True
    )
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric)
    float_shares: Mapped[Decimal | None] = mapped_column(Numeric)
    short_interest_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    revenue_ttm: Mapped[Decimal | None] = mapped_column(Numeric)
    gross_margin: Mapped[Decimal | None] = mapped_column(Numeric)
    fcf_ttm: Mapped[Decimal | None] = mapped_column(Numeric)
    enterprise_value: Mapped[Decimal | None] = mapped_column(Numeric)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class OptionsSnapshot(Base):
    __tablename__ = "options_snapshot"
    __table_args__ = (
        CheckConstraint('"right" IN (\'C\',\'P\')', name="ck_options_snapshot_right"),
        {"postgresql_partition_by": "RANGE (as_of)"},
    )

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 6), primary_key=True)
    right: Mapped[str] = mapped_column("right", String(1), primary_key=True)
    bid: Mapped[Decimal | None] = mapped_column(Numeric)
    ask: Mapped[Decimal | None] = mapped_column(Numeric)
    last: Mapped[Decimal | None] = mapped_column(Numeric)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    open_interest: Mapped[int | None] = mapped_column(BigInteger)
    implied_vol: Mapped[Decimal | None] = mapped_column(Numeric)


class SentimentSnapshot(Base):
    __tablename__ = "sentiment_snapshot"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    velocity: Mapped[Decimal | None] = mapped_column(Numeric)
    wilson: Mapped[Decimal | None] = mapped_column(Numeric)
    volume_z: Mapped[Decimal | None] = mapped_column(Numeric)
    trends_ratio: Mapped[Decimal | None] = mapped_column(Numeric)
    mentions: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))


class CreatorMention(Base):
    __tablename__ = "creator_mentions"
    __table_args__ = (
        UniqueConstraint("source_id", "url", "symbol", name="uq_creator_mentions_src_url_sym"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    direction: Mapped[str | None] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    universe: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    code_version: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "signal_type", name="uq_signals_run_symbol_type"),
        Index("ix_signals_symbol_asof", "symbol", text("as_of DESC")),
        Index("ix_signals_type_asof", "signal_type", text("as_of DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("scan_runs.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_type: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    convexity_ratio: Mapped[Decimal | None] = mapped_column(Numeric)
    entry: Mapped[Decimal | None] = mapped_column(Numeric)
    stop: Mapped[Decimal | None] = mapped_column(Numeric)
    target: Mapped[Decimal | None] = mapped_column(Numeric)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("signals.id"), primary_key=True
    )
    horizon_days: Mapped[int] = mapped_column(Integer, primary_key=True)
    forward_return: Mapped[Decimal | None] = mapped_column(Numeric)
    max_gain: Mapped[Decimal | None] = mapped_column(Numeric)
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric)
    hit_2x: Mapped[bool | None] = mapped_column(Boolean)
    hit_5x: Mapped[bool | None] = mapped_column(Boolean)
    hit_10x: Mapped[bool | None] = mapped_column(Boolean)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric)
    strike: Mapped[Decimal | None] = mapped_column(Numeric)
    expiry: Mapped[date | None] = mapped_column(Date)
    premium_per_share: Mapped[Decimal | None] = mapped_column(Numeric)
    close_convention: Mapped[str | None] = mapped_column(Text)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric)
    signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("signals.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("ix_job_runs_name_started", "job_name", text("started_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    rows_written: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)


class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    symbol: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB)
