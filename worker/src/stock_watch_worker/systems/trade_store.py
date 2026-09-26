"""Disk-backed trade deduplication keeps large suites out of application memory."""
import sqlite3


def connect_trades(history):
    path=history.execute('PRAGMA database_list').fetchone()[2]+'.trades.db'
    db=sqlite3.connect(path)
    db.executescript('''PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS trades (cache_key TEXT,id TEXT,exit_at TEXT,pnl REAL,cost_basis REAL,
      PRIMARY KEY(cache_key,id));''')
    return db


def unique_stats(db,keys):
    db.execute('CREATE TEMP TABLE IF NOT EXISTS unique_trades (id TEXT PRIMARY KEY,pnl REAL)')
    db.execute('DELETE FROM unique_trades')
    for key in keys:
        db.execute('INSERT OR IGNORE INTO unique_trades SELECT id,pnl FROM trades WHERE cache_key=?',(key,))
    n,wins=db.execute('SELECT COUNT(*),COALESCE(SUM(pnl>0),0) FROM unique_trades').fetchone()
    db.commit()
    return n,wins
