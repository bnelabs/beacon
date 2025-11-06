# BEACON Liquidity Risk Platform

**Banking Early Alert Comprehensive Observation Network (BEACON)** – A production-ready systemic liquidity risk monitoring platform powered by the Banking Network Engine (BNE).

Real-time liquidity risk predictions powered by advanced ML models with interactive 3D globe interface.

---

## Quick Start

```bash
# Build and start all services
docker compose build
docker compose up -d

# Access the platform
open http://localhost:9876      # Frontend UI
open http://localhost:3456/docs # API Documentation
```

**View logs:**
```bash
docker compose logs -f backend
```

**Stop services:**
```bash
docker compose down
```

---

## Architecture

```
Frontend (React 19 + Vite + Three.js)
  └── 77.5MB Docker image, ~323KB gzipped bundle
  └── Interactive 3D globe with 14 banking regions
  └── 6 Pages: Dashboard, Globe View, Models, Jobs, Results, Data Sources
  └── Nginx production server (port 9876)

Backend (FastAPI + Celery + PostgreSQL + Redis)
  └── 6-stage data pipeline (collection → validation → cleaning → formatting → analysis → certification)
  └── 15+ data plugins: ECB, FRED, BIS, IMF, World Bank, Yahoo Finance, FDIC, FMP, SEC
  └── HGT models with multi-scale training
  └── RESTful API (port 3456)

ML Stack (PyTorch + PyTorch Geometric)
  └── Heterogeneous Graph Transformers (HGT)
  └── Temporal Attention Networks
  └── Real metrics: MSE, MAE, RMSE, R², directional accuracy
  └── SHAP values, attention weights, feature importance
  └── GPU acceleration (CUDA) + mixed precision training
```

---

## Key Features

- **50+ Financial Indicators** from 15+ integrated data sources
- **Geographic Scope**: Global, regional (North America, Europe, Asia, Pacific, Latin America, Africa), country-level
- **Production-ready ML**: HGT models, multi-scale training, real PyTorch metrics
- **EU AI Act Compliant**: Built-in explainability with SHAP values, attention weights, uncertainty quantification
- **Scope Propagation**: Region/country filters persist through data jobs, training, prediction, and backtest workflows
- **Real-time Progress**: Celery task callbacks with 0-100% monitoring

---

## API Usage

```bash
# Create a data collection job
curl -X POST http://localhost:3456/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"data_collection","parameters":{"regions":["PACIFIC"],"countries":["Japan"]}}'

# Check job status
curl http://localhost:3456/api/v1/jobs/{jobId}

# Get reports
curl http://localhost:3456/api/v2/reports/brief/{jobId}
curl http://localhost:3456/api/v2/reports/detailed/{jobId}
```

---

## Prerequisites

- Docker 20.10+ and Docker Compose v2
- Optional: NVIDIA driver for GPU acceleration
- No local Python/Node installs required

---

## Technology Stack

**Frontend**: React 19.1.1, Vite 7.1.7, Three.js 0.170.0, Zustand 5.0.0, TanStack Query 5.62.7, Tailwind CSS 3.4.17

**Backend**: FastAPI 0.109.0, Celery 5.3.6, SQLAlchemy 2.0.25, PostgreSQL 15, Redis 7

**ML**: PyTorch 2.5.1, PyTorch Geometric 2.6.1, pandas 2.2.3, scikit-learn 1.5.2

---

## Documentation

- **API Docs**: http://localhost:3456/docs (Swagger UI)
- **Configuration**: Edit `.env` file for API keys and database credentials

---

Built with ❤️ by the BEACON team
