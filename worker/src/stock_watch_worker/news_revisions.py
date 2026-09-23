"""Freeze provider-time eligible revisions; later captures cannot alter a scan."""
from datetime import datetime, timedelta
import sqlite3

POLICY = "provider-update-cutoff-frozen-revisions-v1"


def freeze_scan_news(connection: sqlite3.Connection, *, scan_run_id: str,
                     cutoff: datetime, lookback: timedelta) -> None:
    with connection:
        inserted = connection.execute(
            "INSERT INTO scan_news_snapshots(scan_run_id,cutoff_policy) VALUES (?,?) "
            "ON CONFLICT DO NOTHING", (scan_run_id, POLICY),
        )
        if not inserted.rowcount:
            return
        # Rank before joining instrument links: a revision can remove a symbol.
        connection.execute(
            """INSERT INTO scan_news_revisions
            SELECT ?,id FROM (
                SELECT r.id,ROW_NUMBER() OVER (PARTITION BY r.article_id
                    ORDER BY julianday(r.available_at) DESC,r.id DESC) AS priority
                FROM news_revisions r JOIN news_articles a ON a.id=r.article_id
                WHERE a.provider='alpaca'
                    AND julianday(r.published_at)>=julianday(?)
                    AND julianday(r.published_at)<=julianday(?)
                    AND julianday(r.available_at)<=julianday(?)
            ) WHERE priority=1""",
            (scan_run_id,(cutoff-lookback).isoformat(),cutoff.isoformat(),cutoff.isoformat()),
        )
