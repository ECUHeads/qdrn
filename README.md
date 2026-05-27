# DRL Trading Agent — Production-Ready Data Pipeline

ระบบ ETL Pipeline สำหรับ Deep Reinforcement Learning Trading Agent ออกแบบตามมาตรฐาน Production-Grade ด้วย SOLID Principles, Design Patterns และ Enterprise Mechanisms

---

## 📋 สารบัญ

1. [สรุปการวิเคราะห์ขอบเขตระบบ](#1-สรุปการวิเคราะห์ขอบเขตระบบ)
2. [สถาปัตยกรรมระบบ](#2-สถาปัตยกรรมระบบ)
3. [โครงสร้างโปรเจกต์](#3-โครงสร้างโปรเจกต์)
4. [Database Schema](#4-database-schema)
5. [การติดตั้ง](#5-การติดตั้ง)
6. [การใช้งาน](#6-การใช้งาน)
7. [API Reference](#7-api-reference)
8. [การทดสอบ](#8-การทดสอบ)
9. [แนวทางการบำรุงรักษา](#9-แนวทางการบำรุงรักษา)

---

## 1. สรุปการวิเคราะห์ขอบเขตระบบ

### 1.1 Entities หลัก

| Entity | คำอธิบาย | ตารางฐานข้อมูล |
|--------|---------|---------------|
| **Ticker** | ข้อมูลหลักทรัพย์ที่ติดตาม | `tickers` |
| **MarketData** | ข้อมูล OHLCV แบบ时序 | `market_data` |
| **Feature** | ฟีเจอร์วิศวกรรมสำหรับ RL State | `features` |
| **PipelineRun** | ประวัติการรัน ETL Pipeline | `pipeline_runs` |
| **PipelineEvent** | Event log จาก Observer Pattern | `pipeline_events` |
| **TradingSignal** | สัญญาณซื้อขายจาก Signal Engine | `trading_signals` |
| **Position** | ตำแหน่งการลงทุนที่เปิด/ปิด | `positions` |
| **RiskMetric** | ตัวชี้วัดความเสี่ยงรายวัน | `risk_metrics` |
| **AuditLog** | บันทึกการตรวจสอบระบบ | `audit_log` |
| **ModelVersion** | เวอร์ชันโมเดล RL ที่ฝึก | `model_versions` |
| **Experiment** | การทดลอง Hyperparameter | `experiments` |

### 1.2 ความสัมพันธ์ (Relationships)

```
tickers 1──N market_data ──N 1 features
  │                              │
  ├──N trading_signals ──N┐
  │                        ├──N positions
  └──N positions ◄─────────┘

pipeline_runs ──N pipeline_events
model_versions ──N experiments
```

### 1.3 ข้อสมมติฐาน

- ข้อมูล OHLCV จาก Yahoo Finance (`yfinance`) มีความสมบูรณ์เพียงพอสำหรับการฝึก Policy เบื้องต้น
- ระยะแรกเน้น timeframe ระดับนาทีถึงรายวัน (ไม่รองรับ HFT)
- ใช้ SQLite เป็นฐานข้อมูลหลัก (รองรับการย้ายสู่ PostgreSQL/MySQL ในอนาคตผ่าน Repository Pattern)
- Signal Engine ใช้ Rule-based baseline ก่อนเปลี่ยนเป็น RL Agent

---

## 2. สถาปัตยกรรมระบบ

### 2.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Orchestration Layer                       │
│                    (main.py / Prefect)                        │
└──────────┬─────────────────────────────────┬──────────────────┘
           │                                 │
           ▼                                 ▼
┌─────────────────────┐          ┌──────────────────────────────┐
│    Extract Layer    │          │      Configuration Store      │
│  SourceFactory      │          │  (YAML → PipelineConfig)     │
│  ├─ YahooFinance    │          └──────────┬───────────────────┘
│  ├─ CSVSource       │                     │
│  └─ SQLSource       │                     ▼
└──────────┬──────────┐          ┌──────────────────────────────┐
           │          │          │      Transform Layer          │
           ▼          │          │  TransformerChain (Strategy)  │
           │     ┌────┴────┐     │  ├─ MissingValueCleaner       │
           │     │ Observer│     │  ├─ TechnicalFeatureEngineer  │
           │     │   Bus   │     │  ├─ MinMaxNormalizer          │
           │     └─────────┘     │  └─ SequenceAligner           │
           │                     └──────────┬───────────────────┘
           ▼                                │
┌─────────────────────┐                     ▼
│      Load Layer     │          ┌──────────────────────────────┐
│ ├─ ParquetSink      │          │    Database Layer (SQLite)   │
│ ├─ SQLiteSink       │          │  Repository Pattern:          │
│ └─ RedisCacheSink   │          │  ├─ TickerRepository          │
└─────────────────────┘          │  ├─ MarketDataRepository      │
                                 │  ├─ PipelineRunRepository     │
                                 │  └─ TradingSignalRepository   │
                                 └──────────┬───────────────────┘
                                             ▼
                                  ┌──────────────────────────────┐
                                  │    Trading Module            │
                                  │  ├─ SignalEngine             │
                                  │  ├─ RiskManager              │
                                  │  └─ PositionTracker          │
                                  └──────────────────────────────┘
```

### 2.2 Design Patterns ที่ใช้

| Pattern | ตำแหน่งการใช้งาน | จุดประสงค์ |
|---------|----------------|-----------|
| **Strategy** | `TransformerChain` | เปลี่ยน Transformation Logic ได้ Runtime |
| **Factory** | `SourceFactory` + `@register` decorator | สร้าง Source จาก Config String |
| **Observer** | `ObserverBus` + `PipelineObserver` | Decouple Event Emission |
| **Repository** | `*Repository` classes | แยก Data Access Logic |
| **Dependency Injection** | `DataPipeline.__init__()` | Testability + Loose Coupling |

### 2.3 SOLID Compliance

| Principle | กลไกการบังคับใช้ |
|-----------|-----------------|
| **S**ingle Responsibility | แต่ละ Class ดูแล Concern เดียว (extract/transform/load/log/retry) |
| **O**pen/Closed | `AbstractDataSource` ABC — เพิ่ม Source ใหม่โดยไม่แก้ไขโค้ดเดิม |
| **L**iskov Substitution | ทุก Subclass คืน DataFrame Schema เดียวกัน |
| **I**nterface Segregation | Protocol แยก: `Extractable`, `Transformable`, `Loadable` |
| **D**ependency Inversion | `DataPipeline` ขึ้นกับ ABCs, Concretions ถูก Inject |

---

## 3. โครงสร้างโปรเจกต์

```
qdrn/
├── schema.sql                          # SQL สร้างฐานข้อมูล (Production-Ready)
├── main.py                             # Entry Point + CLI
├── config/
│   └── pipeline.yaml                   # YAML Configuration
├── data/                               # Output directory (gitignored)
│   ├── processed/                      # Parquet output
│   └── drl_trading.db                  # SQLite database
├── pipeline/
│   ├── __init__.py
│   ├── config.py                       # Dataclass configurations
│   ├── logging.py                      # JSON Structured Logger
│   ├── errors.py                       # Exception hierarchy
│   ├── retry.py                        # Exponential backoff retry
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py               # SQLite connection manager
│   │   └── repository.py               # Repository pattern CRUD
│   ├── events/
│   │   ├── __init__.py
│   │   └── bus.py                      # ObserverBus + built-in observers
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── factory.py                  # SourceFactory with @register
│   │   └── sources/
│   │       ├── __init__.py
│   │       ├── base.py                 # AbstractDataSource ABC
│   │       └── yahoo_finance.py        # YahooFinanceSource
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── base.py                     # AbstractTransformer + Chain
│   │   └── transformers/
│   │       ├── __init__.py
│   │       ├── cleaner.py              # MissingValueCleaner
│   │       ├── feature_engineer.py     # TechnicalFeatureEngineer
│   │       ├── normalizer.py           # MinMaxNormalizer
│   │       └── aligner.py              # SequenceAligner
│   ├── load/
│   │   ├── __init__.py
│   │   └── sinks/
│   │       ├── __init__.py
│   │       ├── base.py                 # AbstractSink ABC + LoadResult
│   │       ├── parquet.py              # ParquetSink
│   │       └── sqlite_sink.py          # SQLiteSink
│   ├── core/
│   │   ├── __init__.py
│   │   ├── pipeline.py                 # DataPipeline orchestrator
│   │   └── pipeline_result.py          # PipelineResult dataclass
│   └── trading/
│       ├── __init__.py
│       ├── signal_engine.py            # Rule-based signal generator
│       ├── risk_manager.py             # Risk limit enforcement
│       └── position_tracker.py         # Position lifecycle management
├── tests/
│   ├── __init__.py
│   ├── conftest.py                     # Shared pytest fixtures
│   ├── test_config.py                  # Config validation tests
│   ├── test_errors.py                  # Exception hierarchy tests
│   ├── test_retry.py                   # Retry mechanism tests
│   ├── test_transformers.py            # Transformer unit tests
│   ├── test_database.py                # Repository integration tests
│   └── test_events.py                  # Observer bus tests
├── requirements.txt
└── README.md
```

---

## 4. Database Schema

### 4.1 ตารางหลัก (11 Tables + 4 Views)

| Table | Records | Primary Key | Foreign Keys | Indexes |
|-------|---------|-------------|--------------|---------|
| `tickers` | ข้อมูลหลักทรัพย์ | `id` AUTOINCREMENT | — | symbol, is_active, asset_class |
| `market_data` | OHLCV data | `id` AUTOINCREMENT | ticker_id → tickers | ticker+time, timestamp, timeframe |
| `features` | Engineered features | `id` AUTOINCREMENT | market_data_id → market_data | market_data_id |
| `pipeline_runs` | ETL run history | `id` AUTOINCREMENT | — | status, started_at, source_type |
| `pipeline_events` | Event log | `id` AUTOINCREMENT | run_id → pipeline_runs | run_id, event_type |
| `trading_signals` | Trading signals | `id` AUTOINCREMENT | ticker_id → tickers | ticker+time, status, signal_type |
| `positions` | Open/closed positions | `id` AUTOINCREMENT | ticker_id, signal_id | ticker, status, opened_at |
| `risk_metrics` | Daily risk stats | `id` AUTOINCREMENT | — | date (UNIQUE) |
| `audit_log` | Audit trail | `id` AUTOINCREMENT | — | entity, created_at, action |
| `model_versions` | RL model registry | `id` AUTOINCREMENT | — | name+version, status |
| `experiments` | Hyperparameter tracking | `id` AUTOINCREMENT | model_version_id | status, model_version_id |

### 4.2 Views

- **`v_active_tickers`** — Active tickers only
- **`v_latest_market_data`** — Latest OHLCV per ticker/timeframe
- **`v_open_positions`** — Open positions with ticker info
- **`v_pipeline_summary`** — Recent pipeline runs summary

### 4.3 Security Features

- **Parameterized Queries** ทุก query ใช้ `?` placeholder ป้องกัน SQL Injection
- **Foreign Key Constraints** บังคับ Referential Integrity
- **WAL Mode** รองรับ Concurrent Reads
- **CHECK Constraints** ตรวจสอบค่าที่ถูกต้องในระดับ Schema

---

## 5. การติดตั้ง

### 5.1 ข้อกำหนดระบบ

- Python >= 3.12
- pip (package manager)

### 5.2 ติดตั้ง Dependencies

```bash
cd /src-code/qdrn
pip install -r requirements.txt --break-system-packages
```

### 5.3 Dependencies หลัก

| Package | Version | จุดประสงค์ |
|---------|---------|-----------|
| pandas | >= 2.0.0 | Data manipulation |
| numpy | >= 1.24.0 | Numerical computing |
| pyarrow | >= 14.0.0 | Parquet I/O |
| yfinance | >= 0.2.30 | Yahoo Finance API |
| pyyaml | >= 6.0 | YAML config parsing |
| pytest | >= 7.4.0 | Testing framework |

---

## 6. การใช้งาน

### 6.1 รัน Pipeline แบบเต็ม (ETL + Trading)

```bash
python3 main.py --config config/pipeline.yaml
```

### 6.2 CLI Arguments

| Argument | Short | Description | Example |
|----------|-------|-------------|---------|
| `--config` | `-c` | Path to YAML config | `--config config/pipeline.yaml` |
| `--tickers` | `-t` | Override tickers | `-t AAPL GOOGL MSFT` |
| `--start` | `-s` | Override start date | `-s 2024-01-01` |
| `--end` | `-e` | Override end date | `-e 2024-12-31` |
| `--timeframe` | `-tf` | Override timeframe | `-tf 1h` |
| `--trading-only` | — | Skip ETL, run trading only | `--trading-only` |

### 6.3 ตัวอย่างการใช้งาน

```bash
# รันกับ tickers เฉพาะ + timeframe รายชั่วโมง
python3 main.py -t AAPL TSLA -s 2024-06-01 -e 2024-06-30 -tf 60m

# รันเฉพาะ Trading Workflow (ใช้ข้อมูลที่มีในฐานข้อมูล)
python3 main.py --trading-only

# ใช้ config file อื่น
python3 main.py -c /path/to/custom_config.yaml
```

### 6.4 การปรับแต่ง Configuration

แก้ไข [`config/pipeline.yaml`](config/pipeline.yaml):

```yaml
source:
  tickers: [AAPL, GOOGL, MSFT, TSLA, AMZN]
  timeframe: "1d"          # 1m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo

transform:
  transformers:
    - missing_value_cleaner
    - feature_engineer
    - min_max_normalizer
  feature_window: 60       # Rolling window size

risk:
  max_drawdown_limit: 0.15  # 15% max drawdown
  max_position_size: 0.10   # 10% of equity per position
  stop_loss_pct: 0.05       # 5% stop loss
```

---

## 7. API Reference

### 7.1 DataPipeline

```python
from pipeline.core.pipeline import DataPipeline

pipeline = DataPipeline(
    source=yahoo_source,
    transformer=transformer_chain,
    sink=sqlite_sink,
    observer_bus=observer_bus,
    db_connection=db,
)

result = pipeline.run(
    tickers=["AAPL", "GOOGL"],
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
)

print(result.summary())
# ✅ [run_abc123] COMPLETED | Extracted: 504, Transformed: 504, Loaded: 504 rows, Total: 1234ms
```

### 7.2 SignalEngine

```python
from pipeline.trading.signal_engine import SignalEngine

engine = SignalEngine(db_connection)
signals = engine.generate_signals(["AAPL", "GOOGL"])

for s in signals:
    print(f"{s.ticker}: {s.signal_type} (confidence={s.confidence:.2f})")
# AAPL: BUY (confidence=0.65)
# GOOGL: HOLD (confidence=0.55)
```

### 7.3 RiskManager

```python
from pipeline.trading.risk_manager import RiskManager

risk = RiskManager(db_connection)

# ตรวจสอบก่อนเปิด Position ใหม่
risk.validate_new_position(
    ticker_id=1, side="LONG", quantity=100,
    entry_price=150.0, current_equity=100_000
)

# ดู Risk Summary
summary = risk.get_risk_summary()
```

---

## 8. การทดสอบ

### 8.1 รัน Tests ทั้งหมด

```bash
python3 -m pytest tests/ -v --tb=short
```

### 8.2 รันพร้อม Coverage Report

```bash
python3 -m pytest tests/ --cov=pipeline --cov-report=html
```

### 8.3 Test Matrix

| Module | Test File | Tests | Coverage |
|--------|-----------|-------|----------|
| Config | `test_config.py` | 12 | Configuration validation, YAML loading |
| Errors | `test_errors.py` | 13 | Exception hierarchy, attributes |
| Retry | `test_retry.py` | 6 | Exponential backoff, jitter, caps |
| Transformers | `test_transformers.py` | 17 | Cleaner, Engineer, Normalizer, Chain |
| Database | `test_database.py` | 20 | All repositories CRUD operations |
| Events | `test_events.py` | 14 | ObserverBus, built-in observers |

**รวม: 72 tests — ทั้งหมด PASS ✅**

---

## 9. แนวทางการบำรุงรักษา

### 9.1 ความปลอดภัยของข้อมูล

| มาตรการ | การนำไปใช้ |
|---------|------------|
| **SQL Injection Prevention** | ทุก query ใช้ Parameterized Queries (`?` placeholder) |
| **Input Validation** | `SourceConfig.__post_init__` ตรวจสอบค่าที่ถูกต้อง |
| **Secrets Management** | API Keys ผ่าน Environment Variables (ไม่ hardcode) |
| **Audit Logging** | ทุกการเปลี่ยนแปลงถูกบันทึกใน `audit_log` table |

### 9.2 การขยายตัว (Scalability)

- **เพิ่ม Data Source ใหม่:** สร้าง Class สืบทอด `AbstractDataSource` + ใช้ `@SourceFactory.register("name")`
- **เพิ่ม Transformer ใหม่:** สร้าง Class สืบทอด `AbstractTransformer` + เพิ่มชื่อใน YAML config
- **เปลี่ยนฐานข้อมูล:** Implement Repository Interface ใหม่ (ไม่ต้องแก้ไข Business Logic)
- **เพิ่ม Sink ใหม่:** สร้าง Class สืบทอด `AbstractSink`

### 9.3 Monitoring & Observability

- **Structured JSON Logging** — ทุก log entry เป็น JSON parseable
- **Observer Events** — Pipeline emits events ที่สามารถ subscribe ได้
- **Pipeline Run Tracking** — บันทึก metrics ทุกการรันในฐานข้อมูล
- **Risk Metrics Dashboard** — ตัวชี้วัดความเสี่ยงรายวัน

### 9.4 Deployment Checklist

- [ ] ตั้งค่า `config/pipeline.yaml` สำหรับ Production
- [ ] ตรวจสอบ API Rate Limits (Yahoo Finance: ~1 req/sec)
- [ ] ตั้งค่า Cron Job หรือ Scheduler (Prefect/Airflow)
- [ ] เปิด WAL Mode + Backup SQLite เป็นประจำ
- [ ] Monitor Disk Space (Parquet files + DB growth)
- [ ] ตั้งค่า Alert สำหรับ Pipeline Failures

---

*Document Version: 1.0 | Last Updated: 2026-05-27*
