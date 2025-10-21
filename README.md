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

1. **Market Liquidity Risk** - Ability to trade assets without price impact
2. **Funding Liquidity Risk** - Ability to meet cash obligations
3. **Systemic Risk** - Financial system stability and contagion
4. **Operational Risk** - Process failures and operational stress

---

## 💻 Current State

The BEACON application is currently under development. The core three-module architecture (DATA, BNE ENGINE, RESULTS) is in place, but the functionality of each module is still being implemented.

### Module 1: DATA
The data collection module is functional and can collect data from the configured sources.

### Module 2: BNE ENGINE
The BNE Engine has a baseline implementation using a logistic regression model. This is a placeholder for a more sophisticated model that will be implemented in the future.

### Module 3: RESULTS
The results module can generate reports in JSON, PDF, and Excel formats. The content of the reports is based on the output of the baseline BNE Engine.

---

## 📊 Comprehensive Data Catalogue

### 50+ Pre-Configured Financial Data Sources

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
- **scikit-learn** - Baseline model

### Data Processing
- **Pandas 2.2.3** - Data manipulation
- **NumPy 1.26.4** - Numerical computing
- **yfinance 0.2.50** - Yahoo Finance API
- **fredapi 0.5.2** - FRED API
- **alpha-vantage 2.3.1** - Alpha Vantage API

### Reporting
- **fpdf** - PDF generation
- **openpyxl** - Excel generation

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
POST /api/v1/pipeline              - Start complete pipeline
GET  /api/v1/pipeline/{job_id}     - Monitor status
GET  /api/v1/pipeline/{job_id}/data    - DATA quality report
GET  /api/v1/pipeline/{job_id}/engine  - BNE ENGINE metrics
GET  /api/v1/pipeline/{job_id}/results - RESULTS summary
GET  /api/v1/pipeline/{job_id}/download/{format} - Download results (json/pdf/excel)
```

### Data Catalogue Endpoints

```
GET  /api/v1/catalogue             - List all data sources
GET  /api/v1/catalogue/summary     - Statistics
GET  /api/v1/catalogue/defaults    - Default selection (40+ items)
GET  /api/v1/catalogue/categories  - Available categories
GET  /api/v1/catalogue/regions     - Available regions
GET  /api/v1/catalogue/risk-types  - Risk types
```

### Other Endpoints

```
GET  /api/v1/data-sources          - Manage data sources
GET  /api/v1/assets                - Manage assets
GET  /api/v1/jobs                  - Background jobs
GET  /api/v1/config                - System configuration
GET  /api/v1/system/status         - System health
GET  /api/v1/errors                - Error logs
```

**Interactive Docs**: http://localhost:3456/docs

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

✅ **Modular Architecture** - DATA-ENGINE-RESULTS pipeline
✅ **BNE Engine** - Banking Network Engine with state-of-the-art ML
✅ **Comprehensive Catalogue** - 50+ pre-configured sources
✅ **Global Coverage** - US, Europe, Asia markets
✅ **Risk-Focused** - 4 types of liquidity risk
✅ **Real-Time Monitoring** - Every stage observable
✅ **Quality Assurance** - Data certification before processing
✅ **SOTA ML** - HGT, GNN, Transformers
✅ **Actionable Reports** - For regulators, banks, payment systems
✅ **Multiple Exports** - JSON, PDF, Excel
✅ **Production-Ready** - Database-backed, error handling, monitoring

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

- **pipeline_jobs** - Main orchestration tracking
- **data_jobs** - DATA module metrics
- **engine_jobs** - BNE ENGINE module metrics
- **result_jobs** - RESULTS module outputs
- **data_catalogue** - 50+ financial data items
- **data_sources** - Configured connections
- **assets** - Monitored assets
- **error_logs** - System errors

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
**ML Models**: HGT, GNN, Transformers
**Data Sources**: 50+ (ECB, FRED, Yahoo, Alpha Vantage, SEC)
**Coverage**: Global (US, Europe, Asia)
**Repository**: https://github.com/rahatimrahat/beacon
**License**: Copyright © 2025 BNE (Banking Network Engine). All rights reserved.
