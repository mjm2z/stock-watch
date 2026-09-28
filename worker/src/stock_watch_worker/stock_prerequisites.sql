-- Shared read-only diagnostic for Python workers and the Next.js request gate.
-- Session close is the decision timestamp; start inclusive, end exclusive.
-- Preserve provider ambiguity rather than silently choosing a different series.
WITH members AS MATERIALIZED (
    SELECT i.id, i.symbol, c.sector
    FROM universe_memberships u JOIN instruments i ON i.id=u.instrument_id
    LEFT JOIN instrument_context c ON c.instrument_id=i.id
    WHERE u.snapshot_id=(SELECT MAX(id) FROM universe_snapshots) AND i.symbol!='SPY'
), raw AS MATERIALIZED (
    SELECT b.instrument_id, b.timestamp, b.provider, m.sector,
           s.closes_at, substr(b.timestamp,1,10) AS day
    FROM members m JOIN market_bars b ON b.instrument_id=m.id
    LEFT JOIN market_sessions s ON s.trading_date=substr(b.timestamp,1,10)
    WHERE b.timeframe='1Day' AND b.adjustment='raw'
), usable AS MATERIALIZED (
    SELECT * FROM raw WHERE sector IS NOT NULL AND trim(sector)!=''
    AND julianday(closes_at)>=julianday(:start) AND julianday(closes_at)<julianday(:end)
)
SELECT (SELECT MAX(id) FROM universe_snapshots) AS universeId,
       (SELECT COUNT(*) FROM members) AS instruments,
       (SELECT COUNT(*) FROM members WHERE sector IS NULL OR trim(sector)='') AS missingSectors,
       (SELECT COUNT(*) FROM market_sessions WHERE julianday(closes_at)>=julianday(:start)
           AND julianday(closes_at)<julianday(:end)) AS requestedSessions,
       (SELECT COUNT(*) FROM raw) AS rawBars,
       (SELECT COUNT(*) FROM raw WHERE closes_at IS NULL) AS barsWithoutCalendar,
       (SELECT COUNT(*) FROM usable) AS usableBars,
       (SELECT COUNT(DISTINCT instrument_id) FROM usable) AS usableInstruments,
       (SELECT MIN(closes_at) FROM usable) AS coveredStart,
       (SELECT MAX(closes_at) FROM usable) AS coveredEnd,
       (SELECT COUNT(*) FROM (SELECT instrument_id,day FROM usable GROUP BY instrument_id,day HAVING COUNT(*)>1)) AS ambiguousSessions,
       (SELECT COUNT(*) FROM market_bars b JOIN instruments i ON i.id=b.instrument_id
           JOIN market_sessions s ON s.trading_date=substr(b.timestamp,1,10)
           WHERE i.symbol='SPY' AND b.timeframe='1Day' AND b.adjustment='raw'
           AND julianday(s.closes_at)>=julianday(:start) AND julianday(s.closes_at)<julianday(:end)) AS benchmarkBars;
