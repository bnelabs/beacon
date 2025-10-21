# BEACON - Banking Early Alert Comprehensive Observation Network

**Powered by BNE (Banking Network Engine)**

> *"Your early warning system for systemic liquidity risk"*

## System Architecture Roadmap

**Copyright © 2025 BNE (Banking Network Engine). All rights reserved.**

### Three-Module Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         BEACON SYSTEM                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌───────────┐      ┌───────────┐      ┌───────────┐           │
│  │   DATA    │  →   │ BNE ENGINE│  →   │  RESULTS  │           │
│  │  MODULE   │      │  MODULE   │      │  MODULE   │           │
│  └───────────┘      └───────────┘      └───────────┘           │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## MODULE 1: DATA (Collection, Preparation, Validation)

**Purpose:** Acquire, clean, validate, and prepare financial data for processing

**Location:** `backend/modules/data/`

**Components:**
- `collector.py` - Multi-source data collection orchestrator
- `validator.py` - Data quality checks, anomaly detection
- `cleaner.py` - Missing value handling, outlier treatment
- `formatter.py` - Standardization, normalization, feature engineering
- `analyzer.py` - Exploratory data analysis, statistics, visualizations
- `monitor.py` - Real-time collection status, progress tracking

**Features:**
- Catalogue-driven: Users select from 50+ pre-configured sources
- Automatic anomaly detection (statistical + ML-based)
- Data quality scoring (0-100)
- "Fit-for-engine" certification
- Missing data imputation strategies
- Outlier detection and handling
- Real-time progress monitoring
- Data versioning and lineage tracking

**User Experience:**
1. Select data sources from catalogue (default or custom)
2. Review collection limits (API rate limits, date ranges)
3. Start collection → Monitor progress
4. Review data quality report
5. Inspect anomalies and warnings
6. Approve data for ENGINE or re-collect

**API Endpoints:**
- `POST /api/v1/data/collect` - Start collection job
- `GET /api/v1/data/status/{job_id}` - Monitor progress
- `GET /api/v1/data/quality/{job_id}` - Quality report
- `GET /api/v1/data/anomalies/{job_id}` - Detected issues
- `GET /api/v1/data/preview/{job_id}` - Data preview
- `POST /api/v1/data/approve/{job_id}` - Certify for ENGINE

---

## MODULE 2: BNE ENGINE (Banking Network Engine) (ML Processing, Risk Computation)

**Purpose:** Process prepared data using SOTA ML techniques to compute liquidity risks

**Location:** `backend/modules/engine/`

**Components:**
- `orchestrator.py` - Main processing pipeline coordinator
- `preprocessor.py` - Feature engineering, graph construction
- `model_registry.py` - SOTA model management (HGT, GNN, Transformers)
- `trainer.py` - Model training with monitoring
- `predictor.py` - Risk prediction and scoring
- `evaluator.py` - Performance metrics, validation
- `monitor.py` - Real-time processing status
- `explainer.py` - Model interpretability (SHAP, attention weights)

**Models (State-of-the-Art):**
- Heterogeneous Graph Transformer (HGT) - Current
- Graph Neural Networks (GNN)
- Temporal Attention Networks
- LSTM/GRU for time series
- Ensemble methods

**Features:**
- Pluggable model architecture
- Hyperparameter optimization (Optuna)
- Real-time training monitoring
- GPU acceleration
- Model versioning
- A/B testing for model comparison
- Explainable AI (what drives predictions)
- Uncertainty quantification

**Risk Computations:**
- **Market Liquidity Risk** - Asset-level trading liquidity
- **Funding Liquidity Risk** - Institution cash flow stress
- **Systemic Risk** - Network contagion, cascade effects
- **Operational Risk** - Process failure probabilities

**User Experience:**
1. Review data certification
2. Select engine configuration (model, hyperparameters)
3. Start processing → Monitor in real-time
4. View training curves, compute stats
5. Review intermediate results
6. Inspect model decisions (explainability)
7. Approve results for RESULTS module

**API Endpoints:**
- `POST /api/v1/engine/process` - Start processing
- `GET /api/v1/engine/status/{job_id}` - Real-time status
- `GET /api/v1/engine/metrics/{job_id}` - Training metrics
- `GET /api/v1/engine/explain/{job_id}` - Model explanations
- `GET /api/v1/engine/models` - Available models
- `POST /api/v1/engine/compare` - A/B model comparison

---

## MODULE 3: RESULTS (Visualization, Reports, Advisories)

**Purpose:** Present comprehensive risk analysis with visualizations and actionable recommendations

**Location:** `backend/modules/results/`

**Components:**
- `generator.py` - Report generation orchestrator
- `visualizer.py` - Charts, graphs, heatmaps, networks
- `analyzer.py` - Risk interpretation and scoring
- `advisor.py` - Regulatory recommendations, mitigation strategies
- `formatter.py` - Report formatting (PDF, HTML, JSON)
- `exporter.py` - Multi-format export

**Report Sections:**

### 1. Executive Summary
- Overall systemic risk score (0-100)
- Critical alerts and warnings
- Top risk factors
- Key recommendations

### 2. Geographic Risk Analysis
- Risk heatmap by region (US, Europe, Asia)
- Cross-border contagion risks
- Regional vulnerability scores

### 3. Institutional Risk Profiles
- Bank-by-bank risk scores
- Payment system vulnerabilities
- Shadow banking risks
- Interconnectedness metrics

### 4. Market Liquidity Analysis
- Asset class liquidity scores
- Bid-ask spreads analysis
- Market depth metrics
- Illiquidity contagion paths

### 5. Funding Liquidity Analysis
- Overnight funding stress
- Term funding vulnerabilities
- Collateral quality assessment
- Liquidity coverage ratios (LCR)

### 6. Systemic Risk Indicators
- Network centrality measures
- Cascade simulation results
- Too-connected-to-fail institutions
- Contagion probability matrices

### 7. Regulatory Recommendations
**For Regulators:**
- Capital requirement adjustments
- Liquidity buffer recommendations
- Stress test scenarios
- Macroprudential policy suggestions

**For Banks:**
- Liquidity management strategies
- Asset-liability matching
- Diversification recommendations
- Contingency funding plans

**For Payment Systems:**
- Settlement risk mitigations
- Collateral optimization
- Operational resilience measures

### 8. Mitigation Actions
- Required capital ratios (Basel III+)
- Liquidity provisions (LCR, NSFR)
- Contingent conversion (CoCo bonds)
- Resolution planning requirements

**Visualizations:**
- Risk heatmaps (geographic, sectoral)
- Network graphs (contagion paths)
- Time series (risk evolution)
- Scatter plots (risk-return)
- Distribution plots (VaR, CVaR)
- Stress test scenarios
- Monte Carlo simulations

**User Experience:**
1. Review executive summary
2. Drill down into specific regions/institutions
3. Explore interactive visualizations
4. Read detailed explanations
5. Review recommendations
6. Export reports (PDF, Excel, JSON)
7. Share with stakeholders

**API Endpoints:**
- `GET /api/v1/results/summary/{job_id}` - Executive summary
- `GET /api/v1/results/geographic/{job_id}` - Regional analysis
- `GET /api/v1/results/institutional/{job_id}` - Institution profiles
- `GET /api/v1/results/market-liquidity/{job_id}` - Market analysis
- `GET /api/v1/results/funding-liquidity/{job_id}` - Funding analysis
- `GET /api/v1/results/systemic/{job_id}` - Systemic risk
- `GET /api/v1/results/recommendations/{job_id}` - Advisories
- `GET /api/v1/results/visualizations/{job_id}` - Charts data
- `POST /api/v1/results/export/{job_id}` - Export report

---

## Inter-Module Communication

### DATA → ENGINE
```python
{
  "job_id": "data_123",
  "status": "certified",
  "quality_score": 95.5,
  "datasets": {
    "timeseries": "s3://bucket/data_123/timeseries.parquet",
    "features": "s3://bucket/data_123/features.parquet",
    "graph": "s3://bucket/data_123/graph.pkl"
  },
  "metadata": {
    "date_range": ["2019-01-01", "2024-12-31"],
    "assets": 500,
    "observations": 1000000,
    "anomalies_fixed": 12
  }
}
```

### ENGINE → RESULTS
```python
{
  "job_id": "engine_456",
  "model": "HGT_v2.1",
  "status": "completed",
  "performance": {
    "mse": 0.0234,
    "mae": 0.0156,
    "r2": 0.89
  },
  "predictions": "s3://bucket/engine_456/predictions.parquet",
  "explanations": "s3://bucket/engine_456/shap_values.pkl",
  "risk_scores": {
    "market_liquidity": {...},
    "funding_liquidity": {...},
    "systemic_risk": {...}
  }
}
```

---

## Database Schema

### Jobs Table (Orchestration)
```sql
CREATE TABLE pipeline_jobs (
  id SERIAL PRIMARY KEY,
  job_type VARCHAR(50),  -- 'data', 'engine', 'results'
  status VARCHAR(50),
  parent_job_id INTEGER,  -- Links modules
  ...
);
```

### Data Module Tables
- `data_collections` - Collection metadata
- `data_quality_reports` - Quality scores
- `data_anomalies` - Detected issues

### Engine Module Tables
- `engine_runs` - Processing metadata
- `model_versions` - Model registry
- `predictions` - Risk scores
- `explanations` - Model interpretability

### Results Module Tables
- `reports` - Generated reports
- `recommendations` - Advisory outputs
- `visualizations` - Chart configurations

---

## Technology Stack

### Backend
- FastAPI - REST API
- SQLAlchemy - ORM
- PostgreSQL - Main database
- Redis - Caching, Celery broker
- Celery - Async task processing
- PyTorch - Deep learning
- PyTorch Geometric - Graph neural networks
- Pandas, NumPy - Data manipulation
- Scikit-learn - ML utilities
- SHAP - Model explainability
- Optuna - Hyperparameter optimization

### Frontend (Future Enhancement)
- React - UI framework
- D3.js/Plotly - Interactive visualizations
- Material-UI - Component library
- WebSockets - Real-time updates

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Load Balancer                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │ API     │       │ API     │       │ API     │
   │ Server  │       │ Server  │       │ Server  │
   └────┬────┘       └────┬────┘       └────┬────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │ Celery  │       │ Celery  │       │ Celery  │
   │ Worker  │       │ Worker  │       │ Worker  │
   │ (DATA)  │       │ (ENGINE)│       │ (RESULTS)│
   └─────────┘       └─────────┘       └─────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                ┌──────────┴──────────┐
                │                     │
           ┌────▼────┐          ┌────▼────┐
           │ Postgre │          │  Redis  │
           │   SQL   │          │         │
           └─────────┘          └─────────┘
```

---

## Context Recovery Instructions

If context is lost, read this file and continue from:
1. Check `backend/modules/` for module implementations
2. Review `backend/api/routes/` for API endpoints
3. Check `backend/tasks/` for Celery tasks
4. Review `backend/models/` for database schemas
5. Frontend is in `frontend/src/pages/` and `frontend/src/components/`

**Key Files to Review:**
- `backend/modules/data/orchestrator.py` - DATA module entry
- `backend/modules/engine/orchestrator.py` - ENGINE module entry
- `backend/modules/results/generator.py` - RESULTS module entry
- `backend/api/routes/pipeline.py` - Main pipeline API
- `backend/tasks/pipeline_tasks.py` - Async task definitions

**Current Progress:** ✅ Baseline implementation complete
**Next Steps:** Implement a more sophisticated model for the BNE Engine
