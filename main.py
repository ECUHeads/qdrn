#!/usr/bin/env python3
"""
DRL Trading Agent — Main Entry Point.

Demonstrates full pipeline instantiation with Dependency Injection:
1. Load configuration from YAML
2. Initialize database and schema
3. Build pipeline components (Source → Transformer → Sink)
4. Execute ETL pipeline
5. Generate trading signals
6. Apply risk management
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from pipeline.config import PipelineConfig
from pipeline.core.pipeline import DataPipeline
from pipeline.database.connection import DatabaseConnection
from pipeline.events.bus import AlertObserver, LoggingObserver, ObserverBus
from pipeline.extract.factory import SourceFactory
from pipeline.extract.sources.yahoo_finance import YahooFinanceSource  # noqa: F401 triggers registration
from pipeline.load.sinks.parquet import ParquetSink
from pipeline.load.sinks.sqlite_sink import SQLiteSink
from pipeline.logging import get_logger, setup_logging
from pipeline.secure_config import get_yahoo_finance_proxy, load_dotenv, validate_secrets
from pipeline.trading.position_tracker import PositionTracker
from pipeline.trading.risk_manager import RiskManager
from pipeline.trading.signal_engine import SignalEngine
from pipeline.transform.base import TransformerChain
from pipeline.transform.transformers.aligner import SequenceAligner
from pipeline.transform.transformers.cleaner import MissingValueCleaner
from pipeline.transform.transformers.feature_engineer import TechnicalFeatureEngineer
from pipeline.transform.transformers.normalizer import MinMaxNormalizer


def register_sources() -> None:
    """Register all available data sources with the factory."""
    SourceFactory.register("yahoo_finance")(YahooFinanceSource)


def build_pipeline(config: PipelineConfig) -> DataPipeline:
    """Assemble full pipeline with Dependency Injection."""
    observer_bus = ObserverBus()

    # Register built-in observers
    observer_bus.subscribe("*", LoggingObserver())
    observer_bus.subscribe("PIPELINE_FAILED", AlertObserver())
    observer_bus.subscribe("EXTRACT_FAILED", AlertObserver())

    # Build source via factory with proxy from environment
    proxy = get_yahoo_finance_proxy()
    if proxy:
        logger.info("Using Yahoo Finance proxy from environment")

    source = SourceFactory.create_source(config.source, proxy=proxy)

    # Build transformer chain
    transformers = []
    for name in config.transform.transformers:
        match name:
            case "missing_value_cleaner":
                transformers.append(MissingValueCleaner(config=config.transform))
            case "feature_engineer":
                transformers.append(TechnicalFeatureEngineer(config=config.transform))
            case "min_max_normalizer":
                transformers.append(MinMaxNormalizer(config=config.transform))
            case "sequence_aligner":
                transformers.append(SequenceAligner(config=config.transform))

    transformer_chain = TransformerChain(
        transformers=transformers,
        config=config.transform,
        observer_bus=observer_bus,
    )

    # Build sink based on configuration
    if config.sink.sink_type == "parquet":
        sink = ParquetSink(config=config.sink, observer_bus=observer_bus)
    else:
        sink = SQLiteSink(config=config.sink, observer_bus=observer_bus)

    # Initialize database
    db = DatabaseConnection(config.database)
    db.connect()
    db.initialize_schema()

    return DataPipeline(
        source=source,
        transformer=transformer_chain,
        sink=sink,
        observer_bus=observer_bus,
        db_connection=db,
    )


def run_trading_workflow(pipeline: DataPipeline, config: PipelineConfig) -> None:
    """Execute trading workflow: signals → risk check → position management."""
    db = pipeline.db_connection
    logger = get_logger(__name__, component="TradingWorkflow")

    # Initialize trading components
    signal_engine = SignalEngine(db, config.risk)
    risk_manager = RiskManager(db, config.risk)
    position_tracker = PositionTracker(db)

    # Generate signals
    logger.info("Generating trading signals...")
    signals = signal_engine.generate_signals(config.source.tickers)

    for signal in signals:
        logger.info(
            "Signal: %s → %s (confidence=%.2f)",
            signal.ticker,
            signal.signal_type,
            signal.confidence,
        )

    # Risk summary
    risk_summary = risk_manager.get_risk_summary()
    logger.info("Risk summary: %s", risk_summary)

    # Position summary
    pos_summary = position_tracker.get_position_summary()
    logger.info("Position summary: %s", pos_summary)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="DRL Trading Agent Pipeline")
    parser.add_argument(
        "--config", "-c",
        default="config/pipeline.yaml",
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--tickers", "-t",
        nargs="+",
        help="Override tickers from config",
    )
    parser.add_argument(
        "--start", "-s",
        help="Override start date (ISO format)",
    )
    parser.add_argument(
        "--end", "-e",
        help="Override end date (ISO format)",
    )
    parser.add_argument(
        "--timeframe", "-tf",
        choices=["1m", "5m", "15m", "30m", "60m", "1d", "1wk", "1mo"],
        help="Override timeframe",
    )
    parser.add_argument(
        "--trading-only",
        action="store_true",
        help="Skip ETL pipeline, run trading workflow only",
    )

    args = parser.parse_args()

    # Load .env file for secure configuration (if present)
    loaded = load_dotenv(".env")
    if loaded:
        print(f"Loaded {loaded} variable(s) from .env")

    # Validate required secrets
    missing_secrets = validate_secrets()
    if missing_secrets:
        print(f"Warning: Missing environment variables: {missing_secrets}")

    # Setup logging
    setup_logging(level="INFO", json_format=False)
    logger = get_logger(__name__, component="Main")

    # Load configuration
    logger.info("Loading configuration from %s", args.config)
    config = PipelineConfig.from_yaml(args.config)

    # Apply CLI overrides
    if args.tickers:
        from pipeline.config import SourceConfig
        config = PipelineConfig(
            source=SourceConfig(
                source_type=config.source.source_type,
                tickers=args.tickers,
                start_date=config.source.start_date,
                end_date=config.source.end_date,
                timeframe=config.source.timeframe,
            ),
            transform=config.transform,
            sink=config.sink,
            database=config.database,
            risk=config.risk,
            log_level=config.log_level,
            enable_metrics=config.enable_metrics,
        )
    # Apply date/timeframe overrides by rebuilding the frozen SourceConfig
    start_date = config.source.start_date
    end_date = config.source.end_date
    timeframe = config.source.timeframe
    if args.start:
        start_date = datetime.fromisoformat(args.start)
    if args.end:
        end_date = datetime.fromisoformat(args.end)
    if args.timeframe:
        timeframe = args.timeframe

    if start_date != config.source.start_date or end_date != config.source.end_date or timeframe != config.source.timeframe:
        from pipeline.config import SourceConfig
        config = PipelineConfig(
            source=SourceConfig(
                source_type=config.source.source_type,
                tickers=config.source.tickers,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
            ),
            transform=config.transform,
            sink=config.sink,
            database=config.database,
            risk=config.risk,
            log_level=config.log_level,
            enable_metrics=config.enable_metrics,
        )

    # Register sources
    register_sources()

    try:
        if not args.trading_only:
            # Build and run ETL pipeline
            logger.info("Building pipeline...")
            pipeline = build_pipeline(config)

            logger.info(
                "Running pipeline for tickers=%s, range=%s to %s, timeframe=%s",
                config.source.tickers,
                config.source.start_date,
                config.source.end_date,
                config.source.timeframe,
            )

            result = pipeline.run(
                tickers=config.source.tickers,
                start=config.source.start_date,
                end=config.source.end_date,
                partition_key=f"{config.source.start_date.date()}_{config.source.end_date.date()}",
            )

            logger.info(result.summary())

            # Run trading workflow after data is loaded
            run_trading_workflow(pipeline, config)
        else:
            # Trading-only mode
            db = DatabaseConnection(config.database)
            db.connect()
            db.initialize_schema()

            pipeline = DataPipeline(
                source=SourceFactory.create_source(config.source),
                transformer=TransformerChain(),
                sink=SQLiteSink(config=config.sink),
                observer_bus=ObserverBus(),
                db_connection=db,
            )
            run_trading_workflow(pipeline, config)

        logger.info("Pipeline execution completed successfully")

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
