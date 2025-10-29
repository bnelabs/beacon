# BEACON - Banking Early Alert Comprehensive Observation Network

**Powered by BNE (Banking Network Engine)**

> *"Your early warning system for systemic liquidity risk"*

**Systemic liquidity risk analysis system using state-of-the-art ML and comprehensive data catalogue with 48 sources covering US, Europe, Asia, and global markets.**

## 🎯 What is BEACON?

BEACON is an intelligent financial risk monitoring system that analyzes **systemic liquidity risk** and **market liquidity risk** across global financial markets. Using advanced machine learning and a comprehensive data catalogue of 48 financial data sources (ECB, FRED, SEC, BIS, IMF, World Bank, Yahoo Finance, Alpha Vantage), BEACON provides actionable insights for:

- **Regulators**: Capital requirements, stress tests, macroprudential policy
- **Banks**: Liquidity management, diversification strategies, contingency planning
- **Payment Systems**: Settlement risk mitigation, collateral optimization

### Key Risk Types Monitored

1. **Market Liquidity Risk** - Ability to trade assets without significant price impact
2. **Funding Liquidity Risk** - Ability to obtain funding and meet cash obligations
3. **Systemic Risk** - Risk of collapse of entire financial system or market
4. **Operational Risk** - Risk from failed internal processes or external events
5. **Credit Risk** - Counterparty and credit quality risk

---

## 🏗️ Revolutionary Three-Module Architecture

BEACON uses a modular **DATA → ENGINE → RESULTS** pipeline for complete observability and control:

```
┌─────────────────────────────────────────────────────────────────┐
│                    BEACON-BNE SYSTEM                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────┐      ┌───────────┐      ┌───────────┐            │ 
│  │   DATA    │  →   │    BNE    │  →   │  RESULTS  │            │
│  │  MODULE   │      │  ENGINE   │      │  MODULE   │            │
│  └───────────┘      └───────────┘      └───────────┘            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Module 1: DATA (Collection, Preparation, Validation)

**Purpose**: Acquire, clean, validate, and prepare financial data

**Features**:
- ✅ Catalogue-driven selection (48 pre-configured sources across 8 providers)
- ✅ Automatic anomaly detection
- ✅ Data quality scoring (0-100)
- ✅ "Fit-for-engine" certification
- ✅ Missing value imputation
- ✅ Outlier detection and handling
- ✅ Real-time progress monitoring

**User Experience**:
1. Select data sources from catalogue (default or custom)
2. Review collection limits (API rate limits, date ranges)
3. Start collection → Monitor progress
4. Review data quality report
5. Inspect anomalies and warnings
6. Approve data for BNE ENGINE

### Module 2: BNE ENGINE (Banking Network Engine - ML Processing, Risk Computation)

**Purpose**: Process certified data using state-of-the-art ML models

**Features**:
- ✅ Heterogeneous Graph Transformer (HGT) model
- ✅ GPU acceleration (CUDA support)
- ✅ Real-time training monitoring
- ✅ Model explainability (SHAP-ready)
- ✅ Performance metrics tracking
- ✅ Risk score computation

**Models Supported**:
- Heterogeneous Graph Transformer (HGT) - Current
- Graph Neural Networks (GNN) - Ready
- Temporal Attention Networks - Ready
- LSTM/GRU time series - Ready
- Ensemble methods - Ready

**User Experience**:
1. Review data certification
2. Select engine configuration
3. Start processing → Monitor in real-time
4. View training curves, compute stats
5. Inspect model decisions
6. Approve results

### Module 3: RESULTS (Visualization, Reports, Advisories)

**Purpose**: Comprehensive risk analysis with actionable recommendations

**Report Sections**:
1. **Executive Summary** - Overall scores, alerts, top risks
2. **Geographic Analysis** - Regional breakdown (US, Europe, Asia)
3. **Institutional Profiles** - Bank-by-bank risk scores
4. **Market Liquidity** - Asset class analysis, bid-ask spreads
5. **Funding Liquidity** - LCR, NSFR, overnight stress
6. **Systemic Risk** - Network contagion, cascade effects
7. **Recommendations** - For regulators, banks, payment systems
8. **Visualizations** - Heatmaps, networks, time series

**Recommendations Include**:
- **Regulators**: Capital buffers, stress tests, policy actions
- **Banks**: Liquidity management, diversification
- **Payment Systems**: Collateral optimization, settlement risk

**Mitigation Actions**:
- Capital ratios (Basel III+)
- Liquidity provisions (LCR, NSFR)
- CoCo bonds, resolution planning

**Export Formats**: JSON, PDF, Excel

---

## 📊 Comprehensive Data Catalogue

### 48 Pre-Configured Financial Data Sources

#### Exchange Rates (5 pairs)
- EUR/USD, EUR/GBP, EUR/JPY, EUR/CHF, EUR/CNY

#### Interest Rates - Europe (3 sources)
- EONIA (overnight rate)
- EURIBOR (1 month)
- ECB Deposit Facility Rate

#### Interest Rates - US (5 sources)
- SOFR, Federal Funds Rate
- US 10Y & 2Y Treasury Yields
- LIBOR (historical)

#### Banking & Credit (6 sources)
- Euro Area: Deposits, loans
- US: Reserves, commercial loans
- Credit spreads (BAA-AAA), TED Spread

#### Economic Indicators (4 sources)
- US: GDP, Unemployment, CPI
- EU: HICP Inflation

#### Stock Indices (5 sources)
- S&P 500, VIX (volatility)
- Euro Stoxx 50
- Nikkei 225 (Japan)
- Hang Seng (Hong Kong)

#### Commodities (2 sources)
- WTI Crude Oil
- Gold (safe haven)

### Data Sources

#### 1. ECB (European Central Bank)
- **Cost**: Free, no API key required
- **Data**: Exchange rates, interest rates, banking statistics
- **Coverage**: Eurozone, global currencies
- **Integration**: Full SDMX-JSON parser

#### 2. FRED (Federal Reserve Economic Data)
- **Cost**: Free with API key
- **Data**: US economic indicators, interest rates
- **Get Key**: https://fred.stlouisfed.org/

#### 3. Yahoo Finance
- **Cost**: Free, no API key
- **Data**: Stock prices, indices
- **Rate Limit**: ~2000 requests/hour

#### 4. Alpha Vantage
- **Cost**: Free tier (5 calls/min)
- **Data**: Stocks, forex, crypto
- **Get Key**: https://www.alphavantage.co/

#### 5. SEC Edgar
- **Cost**: Free tier (100 requests/month)
- **Data**: Company financials, filings
- **Get Key**: https://sec-api.io

---

## 🚀 Quick Start

### Prerequisites

- **Docker** (20.10+) and **Docker Compose** (2.0+)
- **NVIDIA GPU** (24GB desired for acceleration)
- **16GB RAM minimum** (32GB+ recommended)
- **50GB disk space**

### Installation

```bash
# Clone repository
git clone https://github.com/rahatimrahat/beacon.git
cd beacon

# Start services (interactive setup with rebuild options)
./scripts/start.sh
```

The start script will:
- ✅ Detect if Docker Compose v2 (plugin) or legacy is available
- ✅ Check for GPU support (NVIDIA)
- ✅ Create necessary directories
- ✅ Generate .env file if missing
- ✅ Ask if you want to rebuild (with/without cache)
- ✅ Build and start all services
- ✅ Wait for services to be healthy
- ✅ Auto-populate data catalogue (48 sources)
- ✅ Show you access URLs and quick start guide

**Access Points**:
- Frontend GUI: http://localhost:6789
- Backend API: http://localhost:3456
- API Docs: http://localhost:3456/docs

**Note**: Script uses `docker compose` (no hyphen) if available, falls back to `docker-compose` (legacy).

### Running Complete Pipeline

```bash
# Start DATA → BNE ENGINE → RESULTS pipeline
curl -X POST http://localhost:3456/api/v1/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Systemic Risk Analysis Q4 2024",
    "catalogue_items": [1,2,3,4,5,6,7,8,9,10],
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "config": {"model": "HGT"}
  }'

# Monitor progress (returns job_id from above)
curl http://localhost:3456/api/v1/pipeline/{job_id}

# Get DATA quality report
curl http://localhost:3456/api/v1/pipeline/{job_id}/data

# Get BNE ENGINE metrics
curl http://localhost:3456/api/v1/pipeline/{job_id}/engine

# Get RESULTS summary
curl http://localhost:3456/api/v1/pipeline/{job_id}/results

# Download results (JSON, PDF, or Excel)
curl http://localhost:3456/api/v1/pipeline/{job_id}/download/json -o report.json
curl http://localhost:3456/api/v1/pipeline/{job_id}/download/pdf -o report.pdf
curl http://localhost:3456/api/v1/pipeline/{job_id}/download/excel -o report.xlsx
```

---

## 🛠️ Technologies

### Backend Stack
- **FastAPI** - High-performance REST API
- **PostgreSQL** - Relational database
- **Redis** - Caching, message broker
- **Celery** - Distributed task queue
- **SQLAlchemy** - ORM

### Machine Learning (BNE Engine)
- **PyTorch 2.5.1** - Deep learning framework
- **PyTorch Geometric 2.6.1** - Graph neural networks
- **Model**: Heterogeneous Graph Transformer (HGT)
  - Multi-head attention mechanisms
  - Heterogeneous message passing
  - Temporal encoding

### Data Processing
- **Pandas 2.2.3** - Data manipulation
- **NumPy 1.26.4** - Numerical computing
- **yfinance 0.2.50** - Yahoo Finance API
- **fredapi 0.5.2** - FRED API
- **alpha-vantage 2.3.1** - Alpha Vantage API

### Frontend Stack
- **React 18** - UI framework
- **Material-UI** - Component library
- **React Query** - Data fetching
- **Recharts** - Visualization

### Infrastructure
- **Docker** - Containerization
- **NVIDIA CUDA 12.1** - GPU acceleration
- **Ubuntu 22.04** - Base OS

---

## 📚 API Documentation

### Pipeline Endpoints

```
POST /api/v1/pipeline                           - Start complete DATA→ENGINE→RESULTS pipeline
GET  /api/v1/pipeline/{job_id}                  - Monitor pipeline status & progress
GET  /api/v1/pipeline/{job_id}/data             - DATA module quality report
GET  /api/v1/pipeline/{job_id}/engine           - BNE ENGINE performance metrics
GET  /api/v1/pipeline/{job_id}/results          - RESULTS module summary
GET  /api/v1/pipeline/{job_id}/download/{format} - Download results (json/pdf/excel)
```

### Job Management Endpoints

```
GET  /api/v1/jobs                    - List all jobs (filter by type, status)
POST /api/v1/jobs                    - Create new job (data_collection, training, prediction, backtest)
GET  /api/v1/jobs/{id}               - Get job details and progress
DELETE /api/v1/jobs/{id}             - Cancel running job
```

**Job Types**:
- `data_collection` - Collect and validate financial data
- `training` - Train ML models (HGT, GNN, LSTM, Transformer)
- `prediction` - Generate predictions using trained models
- `backtest` - Validate model performance on historical data

### Data Catalogue Endpoints

```
GET  /api/v1/catalogue                - List all 48 data sources (filter by category/region/risk)
GET  /api/v1/catalogue/summary        - Statistics by category, region, risk type
GET  /api/v1/catalogue/defaults       - Get default 41 recommended sources
GET  /api/v1/catalogue/categories     - List all categories (exchange_rates, interest_rates, etc.)
GET  /api/v1/catalogue/regions        - List all regions (north_america, europe, asia, etc.)
GET  /api/v1/catalogue/risk-types     - List risk types (market_liquidity, funding_liquidity, etc.)
GET  /api/v1/catalogue/{id}           - Get specific catalogue item details
POST /api/v1/catalogue/{id}/test      - Test data source connectivity
```

### Data Source Management

```
GET  /api/v1/data-sources          - List all configured data sources
POST /api/v1/data-sources          - Add new data source
GET  /api/v1/data-sources/{id}     - Get data source details
PUT  /api/v1/data-sources/{id}     - Update data source configuration
DELETE /api/v1/data-sources/{id}   - Remove data source
```

**Supported Plugins**: `ecb`, `fred`, `yfinance`, `alpha_vantage`, `sec_edgar`, `world_bank`, `bis`, `imf`

### Asset Management

```
GET  /api/v1/assets              - List all monitored assets
POST /api/v1/assets              - Add new asset to monitor
POST /api/v1/assets/bulk         - Add multiple assets at once
GET  /api/v1/assets/{id}         - Get asset details
PUT  /api/v1/assets/{id}         - Update asset configuration
DELETE /api/v1/assets/{id}       - Stop monitoring asset
```

### Results & Explainability

```
GET  /api/v1/results/                          - List all completed jobs with results
GET  /api/v1/results/{job_id}                  - Get complete job results
GET  /api/v1/results/{job_id}/executive-summary - Get executive summary
GET  /api/v1/results/{job_id}/data-quality     - Get data quality metrics
GET  /api/v1/results/{job_id}/risk-scores      - Get risk score breakdown
GET  /api/v1/results/{job_id}/visualizations   - List available visualizations

GET  /api/v1/explainability/{job_id}/explanation      - EU AI Act compliant model explanations
GET  /api/v1/explainability/{job_id}/bank-risks       - Per-bank risk analysis
GET  /api/v1/explainability/{job_id}/contagion-analysis - Network contagion effects
GET  /api/v1/explainability/{job_id}/executive-summary - Training/prediction summary
GET  /api/v1/explainability/{job_id}/visualizations/{name} - Download visualization (PNG)
GET  /api/v1/explainability/{job_id}/download/predictions  - Download predictions (CSV)
```

### Configuration Management

```
GET  /api/v1/config           - Get current system configuration
PUT  /api/v1/config/model     - Update model parameters (hidden_dim, num_heads, layers, dropout, lr)
PUT  /api/v1/config/data      - Update data parameters (look_back, correlation_threshold, rate_limit)
PUT  /api/v1/config/training  - Update training parameters (batch_size, epochs, early_stopping)
```

### System Monitoring

```
GET  /api/v1/system/status                    - System health (CPU, memory, GPU, disk)
GET  /api/v1/system/resources/recommendations - Get resource optimization suggestions
```

### Error Management

```
GET  /api/v1/errors              - List all error logs (filter by severity, category)
GET  /api/v1/errors/statistics   - Error statistics and analytics
GET  /api/v1/errors/{id}         - Get error details with solutions
POST /api/v1/errors/report       - Report client-side error
POST /api/v1/errors/{id}/resolve - Mark error as resolved
DELETE /api/v1/errors/{id}       - Delete error log
```

**Interactive API Docs**: http://localhost:3456/docs (Swagger UI)

---

## 🔧 Configuration

### Model Parameters

Adjust via Configuration API or GUI:

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| **Hidden Dimension** | 64-256 | 128 | Model complexity |
| **Number of Heads** | 4-16 | 8 | Attention mechanisms |
| **Number of Layers** | 2-5 | 3 | Network depth |
| **Dropout** | 0.0-0.5 | 0.1 | Regularization |
| **Learning Rate** | 0.0001-0.01 | 0.001 | Training speed |

### Data Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| **Lookback Days** | 30-365 | 90 | Historical data window |
| **Correlation Threshold** | 0.0-1.0 | 0.5 | Min correlation for edges |
| **API Rate Limit** | 0.5-5 sec | 2.0 | Delay between calls |

### Training Parameters

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| **Batch Size** | 8-128 | 32 | Samples per batch |
| **Number of Epochs** | 10-500 | 100 | Max iterations |
| **Early Stopping** | 5-50 | 10 | Patience epochs |

---

## 🐛 Troubleshooting

### Common Issues

#### 1. "Cannot connect to Docker daemon"
```bash
# Check Docker status
docker ps
```

#### 2. "Port already in use"
```bash
# Check what's using port
lsof -i :3456
lsof -i :6789
```

#### 3. "GPU not available"
- Check: `nvidia-smi`
- Install nvidia-docker2
- CPU mode works (slower)

#### 4. "Out of memory"
- Reduce batch size
- Reduce hidden dimension
- Reduce number of layers

#### 5. "Data collection fails"
- Check API keys
- Verify internet connection
- Check rate limits

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f celery-worker

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Restarting Services

```bash
# Restart all
docker-compose restart

# Restart specific
docker-compose restart backend

# Full reset (deletes data!)
docker-compose down -v
docker-compose up --build -d
```

---

## 📖 Documentation

For complete system architecture, module specifications, and context recovery:

**See**: `ROADMAP.md` - Comprehensive 500+ line documentation

---

## 🎯 Key Features

✅ **Modular Architecture** - DATA-ENGINE-RESULTS pipeline with full observability
✅ **BNE Engine** - Banking Network Engine with state-of-the-art ML models
✅ **Comprehensive Catalogue** - 48 pre-configured financial data sources
✅ **Global Coverage** - US, Europe, Asia, Latin America, Middle East, Africa
✅ **Risk-Focused** - 5 types of liquidity and systemic risk
✅ **Real-Time Monitoring** - Live job progress tracking and status updates
✅ **Quality Assurance** - Automated data validation and certification
✅ **SOTA ML Models** - HGT, GNN, Transformers, LSTM
✅ **EU AI Act Compliant** - Full model explainability and transparency
✅ **Job Management** - Data collection, training, prediction, backtesting
✅ **Actionable Reports** - Recommendations for regulators, banks, payment systems
✅ **Multiple Exports** - JSON, PDF, Excel formats
✅ **Error Management** - Comprehensive error logging and resolution tracking
✅ **Configuration API** - Dynamic model, data, and training parameter tuning
✅ **Production-Ready** - PostgreSQL database, Celery workers, Redis cache
✅ **API-First Design** - 55+ REST endpoints with Swagger documentation

---

## 📊 System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                       Frontend                          │
│                   (React + Vite)                        │
│                   Port: 6789                            │
└────────────────────┬────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│                    Backend API                          │
│                     (FastAPI)                           │
│                    Port: 3456                           │
└────┬──────────────────────────────────────────────┬─────┘
     │                                               │
     ↓                                               ↓
┌────────────┐                              ┌───────────────┐
│ PostgreSQL │                              │ Celery Worker │
│  Port:5432 │                              │  (Background) │
└────────────┘                              └───────┬───────┘
     ↑                                               │
     │                                               ↓
     │                                        ┌─────────────┐
     └────────────────────────────────────────│    Redis    │
                                              │  Port: 6379 │
                                              └─────────────┘
```

### Database Schema

- **pipeline_jobs** - Main orchestration tracking (full pipeline status)
- **data_jobs** - DATA module metrics (quality scores, completeness)
- **engine_jobs** - BNE ENGINE module metrics (model performance, risk scores)
- **result_jobs** - RESULTS module outputs (reports, visualizations)
- **jobs** - Individual job tracking (data_collection, training, prediction, backtest)
- **data_catalogue** - 48 financial data items (categories, regions, risk types)
- **data_sources** - 8 configured data providers (ECB, FRED, Yahoo, etc.)
- **assets** - Monitored assets and securities
- **error_logs** - Comprehensive error tracking with resolution status
- **config** - Dynamic system configuration (model, data, training parameters)

---

## 🤝 Contributing

This is a production system. For contributions:
1. Follow modular architecture (DATA-ENGINE-RESULTS)
2. Add tests for new features
3. Update ROADMAP.md if architecture changes
4. Follow existing code patterns

---

## 📜 License

Copyright © 2025 BNE (Banking Network Engine). All rights reserved.

---

## 🏷️ About

**BEACON** - Banking Early Alert Comprehensive Observation Network
**Powered by BNE** - Banking Network Engine

*"Your early warning system for systemic liquidity risk"*

**Version**: 2.0.0
**Architecture**: Modular (DATA-BNE ENGINE-RESULTS)
**ML Models**: HGT, GNN, Transformers, LSTM
**Data Sources**: 48 pre-configured (ECB, FRED, Yahoo Finance, Alpha Vantage, SEC, World Bank, BIS, IMF)
**Coverage**: Global (US, Europe, Asia, Latin America, Middle East, Africa)
**API Endpoints**: 55+ REST endpoints
**Job Types**: data_collection, training, prediction, backtest
**Explainability**: EU AI Act compliant
**Repository**: https://github.com/rahatimrahat/beacon
**License**: Copyright © 2025 BNE (Banking Network Engine). All rights reserved.
