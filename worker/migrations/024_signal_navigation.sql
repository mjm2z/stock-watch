-- Match scan-specific rejection links and stable paginated ranking.
CREATE INDEX signals_scan_ranked ON signals(
    scan_run_id, as_of DESC, opportunity_score DESC, horizon_trading_days, id
);
