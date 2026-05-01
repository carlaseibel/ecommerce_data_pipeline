CREATE TABLE IF NOT EXISTS customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT,
    email        TEXT NOT NULL,
    country      TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_country ON customers(country);

CREATE TABLE IF NOT EXISTS exchange_rates (
    currency     TEXT PRIMARY KEY,
    rate_to_usd  REAL NOT NULL,
    fetched_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id          TEXT PRIMARY KEY,
    customer_id       INTEGER NOT NULL,
    amount_original   REAL NOT NULL,
    currency_original TEXT NOT NULL,
    exchange_rate     REAL NOT NULL,
    amount_usd        REAL NOT NULL,
    status            TEXT NOT NULL,
    order_date        TEXT NOT NULL,
    FOREIGN KEY (customer_id)       REFERENCES customers(customer_id),
    FOREIGN KEY (currency_original) REFERENCES exchange_rates(currency)
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date     ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);

CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    customer_id     INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
CREATE INDEX IF NOT EXISTS idx_events_customer ON events(customer_id);
CREATE INDEX IF NOT EXISTS idx_events_type     ON events(event_type);

CREATE TABLE IF NOT EXISTS staging_orders (
    order_id          TEXT PRIMARY KEY,
    customer_id       INTEGER NOT NULL,
    amount_original   REAL NOT NULL,
    currency_original TEXT NOT NULL,
    status            TEXT NOT NULL,
    order_date        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_runs (
    run_id       TEXT NOT NULL,
    stage        TEXT NOT NULL,
    checkpoint   TEXT NOT NULL,
    success      INTEGER NOT NULL,
    evaluated    INTEGER NOT NULL,
    succeeded    INTEGER NOT NULL,
    started_at   TEXT NOT NULL,
    duration_ms  INTEGER NOT NULL,
    PRIMARY KEY (run_id, stage)
);
CREATE INDEX IF NOT EXISTS idx_dq_started ON data_quality_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS error_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    stage             TEXT NOT NULL,
    source_record_id  TEXT,
    reason            TEXT NOT NULL,
    raw_payload       TEXT,
    occurred_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_error_events_run    ON error_events(run_id);
CREATE INDEX IF NOT EXISTS idx_error_events_stage  ON error_events(stage);
CREATE INDEX IF NOT EXISTS idx_error_events_reason ON error_events(reason);
