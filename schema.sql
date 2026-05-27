-- =============================================================================
-- DRL Trading Agent — SQLite Database Schema
-- Version: 1.0
-- Date: 2026-05-27
-- Description: Production-ready schema for Data Pipeline metadata catalog,
--              ticker registry, pipeline run history, market data storage,
--              trading signals, and audit logging.
-- =============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- =============================================================================
-- 1. TICKER REGISTRY
-- Master list of all tracked financial instruments.
-- =============================================================================
CREATE TABLE IF NOT EXISTS tickers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    name            TEXT    NOT NULL DEFAULT '',
    exchange        TEXT    NOT NULL DEFAULT '',
    asset_class     TEXT    NOT NULL DEFAULT 'equity'
                    CHECK (asset_class IN ('equity', 'forex', 'crypto', 'commodity', 'index', 'etf')),
    currency        TEXT    NOT NULL DEFAULT 'USD',
    is_active       INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
    delisted_date   DATE    DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_tickers_symbol ON tickers(symbol);
CREATE INDEX IF NOT EXISTS idx_tickers_active ON tickers(is_active, symbol);
CREATE INDEX IF NOT EXISTS idx_tickers_asset_class ON tickers(asset_class);

-- =============================================================================
-- 2. MARKET DATA (OHLCV)
-- Raw and processed OHLCV data per ticker and timeframe.
-- =============================================================================
CREATE TABLE IF NOT EXISTS market_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id       INTEGER NOT NULL
                    REFERENCES tickers(id) ON DELETE CASCADE ON UPDATE CASCADE,
    timestamp       DATETIME NOT NULL,
    timeframe       TEXT    NOT NULL DEFAULT '1d'
                    CHECK (timeframe IN ('1m', '5m', '15m', '30m', '60m', '1d', '1wk', '1mo')),
    open            REAL    NOT NULL,
    high            REAL    NOT NULL,
    low             REAL    NOT NULL,
    close           REAL    NOT NULL,
    volume          REAL    NOT NULL DEFAULT 0.0,
    adjusted_close  REAL    DEFAULT NULL,
    dividends       REAL    DEFAULT 0.0,
    splits          REAL    DEFAULT 1.0,
    data_source     TEXT    NOT NULL DEFAULT 'yahoo_finance',
    is_processed    INTEGER NOT NULL DEFAULT 0
                    CHECK (is_processed IN (0, 1)),
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(ticker_id, timestamp, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_market_data_ticker_time ON market_data(ticker_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_market_data_timestamp ON market_data(timestamp);
CREATE INDEX IF NOT EXISTS idx_market_data_timeframe ON market_data(timeframe);
CREATE INDEX IF NOT EXISTS idx_market_data_processed ON market_data(is_processed, ticker_id);

-- =============================================================================
-- 3. FEATURES
-- Engineered features derived from market data for RL state input.
-- =============================================================================
CREATE TABLE IF NOT EXISTS features (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_data_id  INTEGER NOT NULL
                    REFERENCES market_data(id) ON DELETE CASCADE ON UPDATE CASCADE,
    rsi_14          REAL    DEFAULT NULL,
    macd_12_26      REAL    DEFAULT NULL,
    macd_signal     REAL    DEFAULT NULL,
    macd_histogram  REAL    DEFAULT NULL,
    bb_upper        REAL    DEFAULT NULL,
    bb_lower        REAL    DEFAULT NULL,
    bb_middle       REAL    DEFAULT NULL,
    atr_14          REAL    DEFAULT NULL,
    rolling_return_5 REAL   DEFAULT NULL,
    rolling_return_20 REAL  DEFAULT NULL,
    rolling_vol_20  REAL    DEFAULT NULL,
    volume_sma_20   REAL    DEFAULT NULL,
    volume_ratio    REAL    DEFAULT NULL,
    normalized_open REAL    DEFAULT NULL,
    normalized_high REAL    DEFAULT NULL,
    normalized_low  REAL    DEFAULT NULL,
    normalized_close REAL   DEFAULT NULL,
    normalized_volume REAL  DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_features_market_data ON features(market_data_id);

-- =============================================================================
-- 4. PIPELINE RUNS
-- Tracks each ETL pipeline execution for audit and monitoring.
-- =============================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL UNIQUE,
    status          TEXT    NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    source_type     TEXT    NOT NULL,
    tickers_json    TEXT    NOT NULL DEFAULT '[]',
    start_date      DATETIME NOT NULL,
    end_date        DATETIME NOT NULL,
    timeframe       TEXT    NOT NULL DEFAULT '1d',
    rows_extracted  INTEGER NOT NULL DEFAULT 0,
    rows_transformed INTEGER NOT NULL DEFAULT 0,
    rows_loaded     INTEGER NOT NULL DEFAULT 0,
    bytes_written   INTEGER NOT NULL DEFAULT 0,
    duration_ms     REAL    DEFAULT NULL,
    error_message   TEXT    DEFAULT NULL,
    config_json     TEXT    DEFAULT NULL,
    started_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at    DATETIME DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source ON pipeline_runs(source_type);

-- =============================================================================
-- 5. PIPELINE EVENTS
-- Detailed event log for each pipeline run (Observer pattern persistence).
-- =============================================================================
CREATE TABLE IF NOT EXISTS pipeline_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL
                    REFERENCES pipeline_runs(run_id) ON DELETE CASCADE ON UPDATE CASCADE,
    event_type      TEXT    NOT NULL,
    payload_json    TEXT    DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_run ON pipeline_events(run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_type ON pipeline_events(event_type);

-- =============================================================================
-- 6. TRADING SIGNALS
-- Generated trading signals from the RL agent or rule-based engine.
-- =============================================================================
CREATE TABLE IF NOT EXISTS trading_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id       INTEGER NOT NULL
                    REFERENCES tickers(id) ON DELETE CASCADE ON UPDATE CASCADE,
    timestamp       DATETIME NOT NULL,
    signal_type     TEXT    NOT NULL
                    CHECK (signal_type IN ('BUY', 'SELL', 'HOLD')),
    confidence      REAL    NOT NULL DEFAULT 0.0
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    position_size   REAL    DEFAULT NULL
                    CHECK (position_size >= 0.0),
    entry_price     REAL    DEFAULT NULL,
    stop_loss       REAL    DEFAULT NULL,
    take_profit     REAL    DEFAULT NULL,
    features_json   TEXT    DEFAULT NULL,
    model_version   TEXT    DEFAULT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'executed', 'cancelled', 'expired')),
    executed_at     DATETIME DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_trading_signals_ticker ON trading_signals(ticker_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trading_signals_status ON trading_signals(status);
CREATE INDEX IF NOT EXISTS idx_trading_signals_type ON trading_signals(signal_type);

-- =============================================================================
-- 7. POSITIONS
-- Current and historical positions tracked by the system.
-- =============================================================================
CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id       INTEGER NOT NULL
                    REFERENCES tickers(id) ON DELETE CASCADE ON UPDATE CASCADE,
    signal_id       INTEGER DEFAULT NULL
                    REFERENCES trading_signals(id) ON DELETE SET NULL ON UPDATE CASCADE,
    side            TEXT    NOT NULL
                    CHECK (side IN ('LONG', 'SHORT')),
    quantity         REAL    NOT NULL
                    CHECK (quantity > 0),
    entry_price     REAL    NOT NULL,
    current_price   REAL    DEFAULT NULL,
    unrealized_pnl  REAL    DEFAULT 0.0,
    realized_pnl    REAL    DEFAULT 0.0,
    status          TEXT    NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'closed', 'partially_closed')),
    opened_at       DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    closed_at       DATETIME DEFAULT NULL,
    exit_price      REAL    DEFAULT NULL,
    commission      REAL    DEFAULT 0.0,
    slippage        REAL    DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_positions_ticker ON positions(ticker_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_opened ON positions(opened_at DESC);

-- =============================================================================
-- 8. RISK METRICS
-- Daily risk metrics and portfolio-level statistics.
-- =============================================================================
CREATE TABLE IF NOT EXISTS risk_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE    NOT NULL UNIQUE,
    total_equity    REAL    NOT NULL DEFAULT 0.0,
    daily_return    REAL    DEFAULT 0.0,
    sharpe_ratio    REAL    DEFAULT NULL,
    sortino_ratio   REAL    DEFAULT NULL,
    max_drawdown    REAL    DEFAULT 0.0,
    current_drawdown REAL   DEFAULT 0.0,
    win_rate        REAL    DEFAULT 0.0,
    profit_factor   REAL    DEFAULT NULL,
    total_trades    INTEGER NOT NULL DEFAULT 0,
    winning_trades  INTEGER NOT NULL DEFAULT 0,
    losing_trades   INTEGER NOT NULL DEFAULT 0,
    avg_win         REAL    DEFAULT 0.0,
    avg_loss        REAL    DEFAULT 0.0,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_risk_metrics_date ON risk_metrics(date DESC);

-- =============================================================================
-- 9. AUDIT LOG
-- Comprehensive audit trail for all system operations.
-- =============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action          TEXT    NOT NULL,
    entity_type     TEXT    NOT NULL,
    entity_id       INTEGER DEFAULT NULL,
    user            TEXT    DEFAULT NULL,
    details_json    TEXT    DEFAULT NULL,
    ip_address      TEXT    DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);

-- =============================================================================
-- 10. MODEL VERSIONS
-- Track trained RL model versions and their performance metrics.
-- =============================================================================
CREATE TABLE IF NOT EXISTS model_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name      TEXT    NOT NULL,
    version         TEXT    NOT NULL UNIQUE,
    algorithm       TEXT    NOT NULL DEFAULT 'DQN',
    parameters_json TEXT    DEFAULT NULL,
    training_start  DATETIME DEFAULT NULL,
    training_end    DATETIME DEFAULT NULL,
    train_sharpe    REAL    DEFAULT NULL,
    train_drawdown  REAL    DEFAULT NULL,
    test_sharpe     REAL    DEFAULT NULL,
    test_drawdown   REAL    DEFAULT NULL,
    status          TEXT    NOT NULL DEFAULT 'training'
                    CHECK (status IN ('training', 'ready', 'deployed', 'archived', 'failed')),
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_model_versions_name ON model_versions(model_name, version);
CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions(status);

-- =============================================================================
-- 11. HYPERPARAMETER EXPERIMENTS
-- Track RL training experiments for reproducibility.
-- =============================================================================
CREATE TABLE IF NOT EXISTS experiments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT    NOT NULL UNIQUE,
    model_version_id INTEGER DEFAULT NULL
                    REFERENCES model_versions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    config_json     TEXT    DEFAULT NULL,
    learning_rate   REAL    DEFAULT 0.001,
    discount_factor REAL    DEFAULT 0.99,
    epsilon         REAL    DEFAULT 1.0,
    buffer_size     INTEGER DEFAULT 10000,
    batch_size      INTEGER DEFAULT 64,
    epochs          INTEGER DEFAULT 10,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    loss_final      REAL    DEFAULT NULL,
    q_value_stability REAL  DEFAULT NULL,
    started_at      DATETIME DEFAULT NULL,
    completed_at    DATETIME DEFAULT NULL,
    created_at      DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_experiments_model ON experiments(model_version_id);

-- =============================================================================
-- VIEW: Active Tickers
-- =============================================================================
CREATE VIEW IF NOT EXISTS v_active_tickers AS
    SELECT id, symbol, name, exchange, asset_class, currency, created_at
    FROM tickers
    WHERE is_active = 1;

-- =============================================================================
-- VIEW: Latest Market Data per Ticker
-- =============================================================================
CREATE VIEW IF NOT EXISTS v_latest_market_data AS
    SELECT m.id, m.ticker_id, t.symbol, m.timestamp, m.timeframe,
           m.open, m.high, m.low, m.close, m.volume, m.adjusted_close
    FROM market_data m
    INNER JOIN tickers t ON m.ticker_id = t.id
    WHERE m.id IN (
        SELECT MAX(id) FROM market_data GROUP BY ticker_id, timeframe
    );

-- =============================================================================
-- VIEW: Open Positions Summary
-- =============================================================================
CREATE VIEW IF NOT EXISTS v_open_positions AS
    SELECT p.id, p.ticker_id, t.symbol, p.side, p.quantity,
           p.entry_price, p.current_price, p.unrealized_pnl,
           p.commission, p.slippage, p.opened_at
    FROM positions p
    INNER JOIN tickers t ON p.ticker_id = t.id
    WHERE p.status = 'open';

-- =============================================================================
-- VIEW: Pipeline Run Summary
-- =============================================================================
CREATE VIEW IF NOT EXISTS v_pipeline_summary AS
    SELECT pr.id, pr.run_id, pr.status, pr.source_type,
           pr.tickers_json, pr.start_date, pr.end_date, pr.timeframe,
           pr.rows_extracted, pr.rows_transformed, pr.rows_loaded,
           pr.duration_ms, pr.started_at, pr.completed_at,
           strftime('%H:%M:%S', 'now', started_at) AS elapsed
    FROM pipeline_runs pr
    ORDER BY pr.started_at DESC;
