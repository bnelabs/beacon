# BEACON API v2 – Frontend Revamp Contract

This document captures the REST interface required by the new Globe-first UI.  
Every endpoint returns production data (no mocks) and reuses the existing data ingestion,
training, and inference layers.

---

## 1. Data Discovery

### `GET /api/v2/datasources`
Fetch the data sources available for the user-selected geographic regions.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `regions`   | `string` (comma-separated) | ✓ | Region codes, e.g. `NA,EU_WEST,MENA` |

**Response 200**
```json
{
  "regions": ["NA", "EU_WEST"],
  "sources": [
    {
      "id": 42,
      "code": "FRED_IR_USD",
      "name": "FRED – USD Interest Rates",
      "provider": "FRED",
      "category": "interest_rates",
      "region": "north_america",
      "enabled": true,
      "default_selected": true,
      "coverage": {
        "start": "2000-01-01",
        "end": "2025-01-01",
        "frequency": "daily",
        "data_points": 4376
      },
      "supports_historical": true,
      "latency_minutes": 15
    }
  ],
  "other_connectors_supported": true
}
```

### `POST /api/v1/connectors`
Existing endpoint for custom bank connectors. The new UI submits:

```json
{
  "name": "Bank ABC Treasury Feed",
  "api_url": "https://api.bankabc.com/liquidity",
  "credentials": {
    "client_id": "abc",
    "client_secret": "•••••"
  },
  "regions": ["NA"],
  "asset_classes": ["funding_liquidity"],
  "metadata": {
    "contact_email": "risk@bankabc.com",
    "notes": "Requires mTLS certificate already on file."
  }
}
```

---

## 2. Data Catalogue

### `GET /api/v2/datacatalog`
Paginated asset catalogue filtered by selected sources.

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `sources`   | `string` (comma-separated) | ✓ | Data source IDs |
| `page`      | `integer` |   | Defaults to `1` |
| `page_size` | `integer` |   | Defaults to `25`, max `100` |
| `search`    | `string`  |   | Fuzzy match on asset code/name |

**Response 200**
```json
{
  "page": 1,
  "page_size": 25,
  "total": 240,
  "assets": [
    {
      "id": 9901,
      "code": "ECB_ESTR",
      "name": "Euro Short-Term Rate (ESTR)",
      "source_id": 12,
      "source_code": "ECB_MARKET",
      "category": "interest_rates",
      "region": "europe",
      "granularity": "macro",
      "unit": "percent",
      "frequency": "daily",
      "coverage": {
        "start": "2019-10-01",
        "end": "2025-01-04",
        "missing_ratio": 0.0012,
        "anomaly_score": 0.04
      },
      "tags": ["money_market", "europe"],
      "default_windows": {
        "training": ["2019-10-01", "2024-06-30"],
        "testing": ["2024-07-01", "2024-12-31"]
      }
    }
  ]
}
```

---

## 3. Data Jobs & Reports

### `POST /api/v1/jobs/download`
Existing ingestion job stays untouched. The UI submits payload:
```json
{
  "asset_ids": [9901, 1502, 6710],
  "regions": ["EU_WEST", "NA"],
  "sources": [12, 42, 55]
}
```

### `GET /api/v1/jobs/status/{jobId}`
Existing status endpoint continues to drive progress polling.  
Ensure the response includes `progress`, `current_step`, and `eta_seconds` if available.

### `GET /api/v2/reports/brief/{jobId}`
Summarised download/QC outcome.

**Response 200**
```json
{
  "job_id": 731,
  "status": "completed",
  "downloaded": 48,
  "failed": 2,
  "fit_for_purpose_score": 0.87,
  "quality_metrics": {
    "completeness": 0.94,
    "consistency": 0.91,
    "timeliness": 0.89
  },
  "started_at": "2025-01-08T09:15:00Z",
  "completed_at": "2025-01-08T09:17:30Z"
}
```

### `GET /api/v2/reports/detailed/{jobId}`
Asset-level QC report feeding the modal.

```json
{
  "job_id": 731,
  "assets": [
    {
      "asset_id": 9901,
      "name": "Euro Short-Term Rate (ESTR)",
      "status": "ok",
      "downloaded_points": 423,
      "missing_points": 0,
      "anomalies_detected": 1,
      "anomalies_details": [
        {
          "timestamp": "2024-10-17",
          "type": "outlier",
          "magnitude": 3.2,
          "resolution": "capped_to_p95"
        }
      ],
      "fit_for_engine": true
    }
  ],
  "summary": {
    "warnings": ["2 assets exceeded retry thresholds"],
    "recommendations": [
      "Re-authorise FedWire connector before next run."
    ]
  }
}
```

---

## 4. Training Pipeline

### `GET /api/v1/config/training-defaults`
**New helper** returning the pre-filled parameter set for the Phase 4 configuration screen.

**Response 200**
```json
{
  "sequence_length": 60,
  "batch_size": 32,
  "epochs": 100,
  "learning_rate": 0.0008,
  "validation_split": 0.2,
  "model": "temporal_attention",
  "optimizer": "adamw",
  "early_stopping": {
    "patience": 12,
    "min_delta": 0.0001
  }
}
```

### `POST /api/v1/jobs/train`
Existing endpoint – ensure it accepts overrides for the above configuration fields and returns `job_id`.

### `GET /api/v1/reports/download/{jobId}?format={pdf|excel|word}`
Existing downloads remain. The UI shows links once the training job finishes.

---

## 5. Model Library

### `GET /api/v1/models`
Existing endpoint should return the metadata required to render the “bookshelf”:
```json
{
  "models": [
    {
      "id": "model_20250108_1130",
      "name": "Multi-scale Transformer – Jan 2025",
      "created_at": "2025-01-08T11:30:00Z",
      "trained_on_job": 902,
      "metrics": {
        "mae": 0.031,
        "rmse": 0.046,
        "r2": 0.89
      },
      "tags": ["transformer", "multi-source", "production"]
    }
  ]
}
```

### `GET /api/v1/models/{modelId}`
Lazy-load detail (existing endpoint or add support) with training history, validation metrics, and dataset lineage.

---

## 6. Prediction & Backtesting

### `POST /api/v1/predict`
Existing endpoint must be extended to return the time-series envelope required by Phase 6 visualisations.

**Request**
```json
{
  "model_id": "model_20250108_1130",
  "horizon_days": 7,
  "scenario": {
    "volatility": 0.18,
    "funding_spread_bps": 45,
    "shock_type": "systemic_liquidity"
  },
  "what_if": {
    "region_shocks": [
      {"region": "EU_WEST", "magnitude": 0.12},
      {"region": "NA", "magnitude": 0.05}
    ]
  }
}
```

**Response 200**
```json
{
  "job_id": 1045,
  "model_id": "model_20250108_1130",
  "horizon_days": 7,
  "timeline": [
    {
      "day": 1,
      "timestamp": "2025-01-09T00:00:00Z",
      "system_tension": 0.68,
      "market_liquidity": 0.62,
      "funding_liquidity": 0.66,
      "network": {
        "nodes": [
          {"id": "BANK_A", "name": "Bank A", "risk": 0.82, "region": "EU_WEST"},
          {"id": "BANK_B", "name": "Bank B", "risk": 0.64, "region": "NA"}
        ],
        "edges": [
          {"from": "BANK_A", "to": "BANK_B", "exposure": 1.6e9}
        ]
      }
    }
  ],
  "feature_importances": {
    "funding_spread": 0.31,
    "stress_liquidity": 0.27,
    "volatility": 0.19
  },
  "confidence": {
    "lower": 0.55,
    "upper": 0.81
  }
}
```

### `POST /api/v1/backtest/{modelId}`
Existing backtest endpoint; the new UI expects `job_id` in response for polling.

### `GET /api/v2/reports/backtest/{jobId}`
JSON payload for the backtest results display.

```json
{
  "job_id": 1102,
  "model_id": "model_20250108_1130",
  "status": "completed",
  "period": {
    "start": "2023-01-01",
    "end": "2024-12-31"
  },
  "metrics": {
    "mae": 0.034,
    "rmse": 0.051,
    "r2": 0.88,
    "hit_ratio": 0.79,
    "max_drawdown": -0.12
  },
  "per_region": [
    {"region": "EU_WEST", "mae": 0.029, "rmse": 0.044},
    {"region": "NA", "mae": 0.036, "rmse": 0.053}
  ],
  "events": [
    {
      "timestamp": "2023-03-10",
      "label": "SVB Failure",
      "actual_tension": 0.84,
      "predicted_tension": 0.81
    }
  ],
  "download_links": {
    "csv": "/api/v1/reports/download/1102?format=csv",
    "pdf": "/api/v1/reports/download/1102?format=pdf"
  }
}
```

---

## 7. Telemetry Enhancements

- **Jobs status payload** should include (if available):
  - `estimated_completion` (ISO datetime)
  - `progress_breakdown` (per stage percentages)
  - `resource_usage` (CPU %, GPU %, memory).
- Ensure all new endpoints require the same auth / headers as existing v1 endpoints (none for now).

---

## 8. Error Model

All v2 endpoints return FastAPI error payloads in the existing format:
```json
{
  "detail": {
    "technical": "Data catalogue not available for sources [12]",
    "user_friendly": "We could not load the catalogue for one of your selected sources. Please try again."
  }
}
```

If a job is still running, `/api/v2/reports/*` respond with HTTP `202 Accepted`:
```json
{
  "job_id": 731,
  "status": "running",
  "progress": 62.5
}
```

---

## 9. Open Questions
1. Do we need region-level overrides when users select both region and specific countries?  
2. Should `/api/v1/predict` schedule long-running jobs or respond synchronously? For v2 UI we assume synchronous inference under 15 seconds; longer runs can fall back to jobs.
3. Authentication/SSO is out of scope for MVP; revisit before going to production.

---

Keeping this file up to date ensures the frontend build remains fully data-driven with zero mock content.

