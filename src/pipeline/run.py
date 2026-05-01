"""Pipeline orchestrator: runs the five stages in order, aborts on the first failure."""

from __future__ import annotations

import sys
import uuid

from src.common import config, db
from src.common.exchange_rate_client import ExchangeRateClient
from src.common.logging import get_logger
from src.pipeline import (
    enrich_exchange_rates,
    ingest_customers,
    ingest_events,
    ingest_orders,
    load_warehouse,
)


def main() -> int:
    cfg = config.load()
    log = get_logger("pipeline")
    run_id = uuid.uuid4().hex[:12]
    log.info("Pipeline starting", extra={"run_id": run_id})

    conn = db.connect(cfg.warehouse_path)
    try:
        db.bootstrap(conn, cfg.schema_path)
        client = ExchangeRateClient(
            base_url=cfg.exchange_rate_api_url,
            api_key=cfg.exchange_rate_api_key,
        )

        ingest_customers.run(conn, cfg.raw_data_dir, cfg.validations_dir, run_id)
        ingest_orders.run(conn, cfg.raw_data_dir, cfg.validations_dir, run_id)
        ingest_events.run(conn, cfg.raw_data_dir, cfg.validations_dir, run_id)
        enrich_exchange_rates.run(conn, client, cfg.validations_dir, run_id)
        load_warehouse.run(conn, run_id)
    except Exception:
        log.exception("Pipeline failed", extra={"run_id": run_id})
        return 1
    finally:
        conn.close()

    log.info("Pipeline complete", extra={"run_id": run_id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
