"""Validated transformations from provider models into durable SQLite rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .providers.alpaca import AlpacaAsset, MarketBar, NewsArticle
from .sentiment import MODEL_VERSION, calculate_news_sentiment


class DataConflictError(RuntimeError):
    """A provider attempted to silently change an immutable stored observation."""


@dataclass(frozen=True, slots=True)
class PersistResult:
    inserted: int
    unchanged: int
    skipped_unknown_symbols: tuple[str, ...] = ()
    revised: int = 0


@dataclass(frozen=True, slots=True)
class AssetRefreshResult:
    updated: int
    unchanged: int
    missing_symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompanyFactsPersistResult:
    document_id: int
    inserted: bool
    content_sha256: str


def persist_company_facts(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    captured_at: str,
    company_facts: Mapping[str, object],
    ingestion_id: int | None = None,
) -> CompanyFactsPersistResult:
    normalized_symbol = symbol.strip().upper()
    instrument = connection.execute(
        "SELECT id FROM instruments WHERE symbol = ?", (normalized_symbol,)
    ).fetchone()
    if instrument is None:
        raise ValueError(f"unknown instrument: {normalized_symbol}")
    canonical = json.dumps(
        company_facts,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = connection.execute(
        """
        SELECT id, content_sha256 FROM company_fact_documents
        WHERE instrument_id = ? AND captured_at = ? AND provider = 'sec'
        """,
        (instrument["id"], captured_at),
    ).fetchone()
    if existing:
        if existing["content_sha256"] != digest:
            raise DataConflictError(
                f"immutable CompanyFacts changed for {normalized_symbol} at {captured_at}"
            )
        return CompanyFactsPersistResult(int(existing["id"]), False, digest)
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO company_fact_documents(
                instrument_id, captured_at, content_sha256,
                facts_json, ingestion_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (instrument["id"], captured_at, digest, canonical, ingestion_id),
        )
    return CompanyFactsPersistResult(int(cursor.lastrowid), True, digest)


def refresh_asset_metadata(
    connection: sqlite3.Connection,
    assets: Iterable[AlpacaAsset],
    *,
    universe_snapshot_id: int,
) -> AssetRefreshResult:
    """Refresh tradability metadata only for members of an approved snapshot."""

    members = {
        str(row["symbol"]): row
        for row in connection.execute(
            """
            SELECT instruments.id, instruments.symbol, instruments.name,
                   instruments.exchange, instruments.alpaca_asset_id,
                   instruments.active, instruments.fractionable
            FROM universe_memberships
            JOIN instruments ON instruments.id = universe_memberships.instrument_id
            WHERE universe_memberships.snapshot_id = ?
            """,
            (universe_snapshot_id,),
        )
    }
    if not members:
        raise ValueError("universe snapshot has no members")
    by_symbol = {asset.symbol: asset for asset in assets if asset.symbol in members}
    updated = 0
    unchanged = 0
    with connection:
        for symbol, asset in by_symbol.items():
            stored = members[symbol]
            active = int(asset.status == "active" and asset.tradable)
            fractionable = int(asset.fractionable)
            desired = (
                asset.name or stored["name"],
                asset.exchange or stored["exchange"],
                asset.id,
                active,
                fractionable,
            )
            existing = (
                stored["name"],
                stored["exchange"],
                stored["alpaca_asset_id"],
                stored["active"],
                stored["fractionable"],
            )
            if desired == existing:
                unchanged += 1
                continue
            connection.execute(
                """
                UPDATE instruments
                SET name = ?, exchange = ?, alpaca_asset_id = ?,
                    active = ?, fractionable = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*desired, stored["id"]),
            )
            updated += 1
    return AssetRefreshResult(
        updated=updated,
        unchanged=unchanged,
        missing_symbols=tuple(sorted(set(members) - set(by_symbol))),
    )


def persist_market_bars(
    connection: sqlite3.Connection,
    bars: Iterable[MarketBar],
    *,
    timeframe: str,
    adjustment: str,
    provider: str,
    ingestion_id: int | None = None,
    allow_revisions: bool = False,
) -> PersistResult:
    values = tuple(bars)
    symbol_ids = _instrument_ids(connection, {bar.symbol for bar in values})
    unknown = sorted({bar.symbol for bar in values} - set(symbol_ids))
    if unknown:
        raise ValueError(f"market bars contain unknown instruments: {', '.join(unknown)}")

    inserted = 0
    unchanged = 0
    revised = 0
    with connection:
        for bar in values:
            _validate_bar(bar)
            row = (
                symbol_ids[bar.symbol],
                bar.timestamp,
                timeframe,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.trade_count,
                bar.vwap,
                adjustment,
                provider,
                ingestion_id,
            )
            cursor = connection.execute(
                """
                INSERT INTO market_bars(
                    instrument_id, timestamp, timeframe, open, high, low, close,
                    volume, trade_count, vwap, adjustment, provider, ingestion_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                row,
            )
            if cursor.rowcount == 1:
                inserted += 1
                continue

            stored = connection.execute(
                """
                SELECT open, high, low, close, volume, trade_count, vwap, ingestion_id
                FROM market_bars
                WHERE instrument_id = ? AND timestamp = ? AND timeframe = ?
                  AND adjustment = ? AND provider = ?
                """,
                (
                    symbol_ids[bar.symbol],
                    bar.timestamp,
                    timeframe,
                    adjustment,
                    provider,
                ),
            ).fetchone()
            observed = (
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.trade_count,
                bar.vwap,
            )
            existing = tuple(stored)[:7] if stored else None
            if existing != observed:
                if not allow_revisions or stored is None:
                    raise DataConflictError(
                        f"immutable bar changed for {bar.symbol} at {bar.timestamp}"
                    )
                key = (symbol_ids[bar.symbol], bar.timestamp, timeframe, adjustment, provider)
                fields = ("open", "high", "low", "close", "volume", "trade_count", "vwap")
                connection.execute(
                    """INSERT INTO market_bar_revisions(
                        instrument_id, timestamp, timeframe, adjustment, provider,
                        ingestion_id, previous_ingestion_id, previous_json, revised_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*key, ingestion_id, stored["ingestion_id"],
                     json.dumps(dict(zip(fields, existing))),
                     json.dumps(dict(zip(fields, observed)))),
                )
                connection.execute(
                    """UPDATE market_bars SET open=?, high=?, low=?, close=?,
                        volume=?, trade_count=?, vwap=?, ingestion_id=?
                        WHERE instrument_id=? AND timestamp=? AND timeframe=?
                          AND adjustment=? AND provider=?""",
                    (*observed, ingestion_id, *key),
                )
                revised += 1
                continue
            unchanged += 1

        # The request start is a conservative lower bound on observation time.
        # Refresh this even when prices did not change; an old partial bar can
        # legitimately have the same close as the finished session.
        if ingestion_id is not None:
            connection.executemany(
                """UPDATE market_bars SET last_observed_at = (
                    SELECT started_at FROM data_ingestions WHERE id = ?)
                    WHERE instrument_id=? AND timestamp=? AND timeframe=?
                      AND adjustment=? AND provider=?""",
                ((ingestion_id, symbol_ids[bar.symbol], bar.timestamp,
                  timeframe, adjustment, provider) for bar in values),
            )

    return PersistResult(inserted=inserted, unchanged=unchanged, revised=revised)


def persist_news_articles(
    connection: sqlite3.Connection,
    articles: Iterable[NewsArticle],
    *,
    provider: str = "alpaca",
    ingestion_id: int | None = None,
) -> PersistResult:
    values = tuple(articles)
    all_symbols = {symbol for article in values for symbol in article.symbols}
    symbol_ids = _instrument_ids(connection, all_symbols)
    unknown_symbols = tuple(sorted(all_symbols - set(symbol_ids)))
    inserted = 0
    unchanged = 0
    revised = 0
    observed_at = datetime.now(timezone.utc).isoformat()

    with connection:
        for article in values:
            article_id = f"{provider}:{article.id}"
            canonical = json.dumps(
                article.raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            cursor = connection.execute(
                """
                INSERT INTO news_articles(
                    id, provider, published_at, updated_at, headline, summary,
                    source, url, content_hash, raw_json, ingestion_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    article_id,
                    provider,
                    article.created_at,
                    article.updated_at,
                    article.headline,
                    article.summary,
                    article.source,
                    article.url,
                    content_hash,
                    canonical,
                    ingestion_id,
                ),
            )
            original_inserted = cursor.rowcount == 1
            available_at = article.updated_at or article.created_at
            # A changed payload without a provider update timestamp must never
            # masquerade as text available at its original publication time.
            if not original_inserted and article.updated_at is None:
                available_at = observed_at
            same_timestamp = connection.execute(
                "SELECT 1 FROM news_revisions WHERE article_id=? AND julianday(available_at)=julianday(?) "
                "AND content_hash!=? LIMIT 1", (article_id,available_at,content_hash),
            ).fetchone()
            if same_timestamp:
                available_at = observed_at
            revision = connection.execute(
                """INSERT INTO news_revisions(article_id,content_hash,published_at,
                    available_at,first_observed_at,headline,summary,raw_json)
                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(article_id,content_hash) DO NOTHING""",
                (article_id,content_hash,article.created_at,available_at,observed_at,
                 article.headline,article.summary,canonical),
            )
            revision_inserted = revision.rowcount == 1
            revision_id = connection.execute(
                "SELECT id FROM news_revisions WHERE article_id=? AND content_hash=?",
                (article_id,content_hash),
            ).fetchone()[0]
            if original_inserted:
                inserted += 1
            elif revision_inserted:
                revised += 1
            else:
                unchanged += 1
            if ingestion_id is not None:
                connection.execute("INSERT INTO news_revision_observations VALUES (?,?) ON CONFLICT DO NOTHING",
                                   (ingestion_id,revision_id))

            for symbol in article.symbols:
                instrument_id = symbol_ids.get(symbol)
                if instrument_id is None:
                    continue
                if original_inserted:
                    connection.execute(
                        """
                        INSERT INTO news_instruments(
                            news_id, instrument_id, sentiment, sentiment_model
                        ) VALUES (?, ?, ?, ?)
                        ON CONFLICT(news_id, instrument_id) DO NOTHING
                        """,
                        (
                            article_id,
                            instrument_id,
                            calculate_news_sentiment(article.headline, article.summary),
                            MODEL_VERSION,
                        ),
                    )
                if revision_inserted:
                    connection.execute(
                        "INSERT INTO news_revision_instruments VALUES (?,?,?,?)",
                        (revision_id,instrument_id,
                         calculate_news_sentiment(article.headline,article.summary),MODEL_VERSION),
                    )


    return PersistResult(
        inserted=inserted,
        unchanged=unchanged,
        skipped_unknown_symbols=unknown_symbols,
        revised=revised,
    )


def _instrument_ids(
    connection: sqlite3.Connection,
    symbols: set[str],
) -> Mapping[str, int]:
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    rows = connection.execute(
        f"SELECT id, symbol FROM instruments WHERE symbol IN ({placeholders})",
        tuple(sorted(symbols)),
    ).fetchall()
    return {row["symbol"]: int(row["id"]) for row in rows}


def _validate_bar(bar: MarketBar) -> None:
    if not bar.timestamp:
        raise ValueError("market bar timestamp is required")
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        raise ValueError("market bar prices must be positive")
    if bar.volume < 0:
        raise ValueError("market bar volume cannot be negative")
    if bar.low > min(bar.open, bar.close, bar.high):
        raise ValueError("market bar low is inconsistent with OHLC values")
    if bar.high < max(bar.open, bar.close, bar.low):
        raise ValueError("market bar high is inconsistent with OHLC values")
