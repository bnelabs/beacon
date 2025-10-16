# FinAI - Financial Liquidity Risk Monitoring System

A deep learning-based system for predicting and monitoring liquidity risk in financial markets using Graph Neural Networks.

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Technologies](#technologies)
- [Quick Start](#quick-start)
- [System Architecture](#system-architecture)
- [Data Sources](#data-sources)
- [Machine Learning Model](#machine-learning-model)
- [Configuration Guide](#configuration-guide)
- [API Documentation](#api-documentation)
- [Troubleshooting](#troubleshooting)

## Overview

FinAI is an intelligent liquidity risk monitoring system that uses advanced machine learning to predict potential liquidity crises in financial markets. The system collects data from multiple sources, builds a graph representation of asset relationships, and uses a Heterogeneous Graph Transformer (HGT) model to forecast liquidity metrics.

### What is Liquidity Risk?

Liquidity risk is the potential difficulty of buying or selling an asset without causing significant price changes. This system monitors:
- **Trading volume trends** - How easily assets can be bought/sold
- **Price volatility** - Stability of asset prices
- **Market depth** - Available orders at different price levels
- **Correlation patterns** - Relationships between different assets

### Key Features

- **Multi-Source Data Integration**: Yahoo Finance, FRED, Alpha Vantage, CSV uploads, custom APIs
- **Graph-Based Analysis**: Models relationships between assets using Graph Neural Networks
- **Real-Time Monitoring**: Automated data collection and continuous risk assessment
- **Predictive Analytics**: Forecasts liquidity metrics up to 30 days ahead
- **User-Friendly Interface**: No coding required - configure everything through the web GUI
- **Comprehensive Error Tracking**: Detailed error logging and analytics for troubleshooting
- **GPU Acceleration**: Leverages CUDA for fast model training (CPU fallback available)

## How It Works

### Data Flow

```
Data Sources (APIs/CSV)
         ↓
[1] Data Collection
         ↓
[2] Feature Engineering
    - Price changes
    - Volume metrics
    - Technical indicators
    - Economic indicators
         ↓
[3] Graph Construction
    - Nodes: Assets + Indicators
    - Edges: Correlations
         ↓
[4] HGT Model
    - Processes graph structure
    - Learns asset relationships
    - Temporal patterns
         ↓
[5] Predictions
    - Liquidity score (0-1)
    - Risk level (low/medium/high)
    - Volatility forecast
         ↓
[6] Visualization & Alerts
```

### Processing Pipeline

1. **Data Collection**
   - Fetches historical and real-time market data
   - Collects economic indicators (GDP, interest rates, etc.)
   - Stores data in PostgreSQL database

2. **Feature Engineering**
   - Calculates price changes, returns, volatility
   - Computes volume-based metrics
   - Generates technical indicators (RSI, MACD, Bollinger Bands)
   - Normalizes data for model input

3. **Graph Construction**
   - Creates nodes for each asset and indicator
   - Computes correlations between assets
   - Establishes edges based on correlation threshold
   - Builds heterogeneous graph with multiple node/edge types

4. **Model Training**
   - Heterogeneous Graph Transformer processes the graph
   - Learns complex relationships through attention mechanisms
   - Trains on historical data with temporal validation
   - Optimizes to predict liquidity metrics

5. **Prediction Generation**
   - Generates forecasts for specified time horizons
   - Calculates confidence intervals
   - Assigns risk levels based on thresholds
   - Updates predictions as new data arrives

### Outputs

The system provides:
- **Liquidity Scores**: 0 (illiquid) to 1 (highly liquid) for each asset
- **Risk Classifications**: Low, Medium, High, Critical
- **Volatility Forecasts**: Expected price variability
- **Anomaly Detection**: Identification of unusual patterns
- **Visual Dashboards**: Charts, graphs, and trend analysis
- **Downloadable Reports**: CSV/JSON exports of predictions and metrics

## Technologies

### Backend Stack

- **FastAPI**: High-performance REST API framework
- **PostgreSQL**: Relational database for structured data
- **Redis**: Caching and message broker for background tasks
- **Celery**: Distributed task queue for async processing
- **SQLAlchemy**: ORM for database operations

### Machine Learning

- **PyTorch**: Deep learning framework (version 2.5.1)
- **PyTorch Geometric (PyG)**: Graph neural network library (version 2.6.1)
- **Model Architecture**: Heterogeneous Graph Transformer (HGT)
  - Multi-head attention mechanisms
  - Heterogeneous message passing
  - Temporal encoding
  - Hidden dimensions: 128 (configurable)
  - Number of layers: 3 (configurable)
  - Attention heads: 8 (configurable)

### Data Processing

- **Pandas**: Data manipulation and analysis (version 2.2.3)
- **NumPy**: Numerical computations (version 1.26.4)
- **yfinance**: Yahoo Finance API wrapper (version 0.2.50)
- **fredapi**: Federal Reserve Economic Data API (version 0.5.2)
- **alpha-vantage**: Stock market data API (version 2.3.1)

### Frontend Stack

- **React 18**: Modern UI framework
- **Material-UI (MUI)**: Component library
- **React Query**: Data fetching and caching
- **React Router**: Navigation
- **Recharts**: Data visualization

### Infrastructure

- **Docker**: Containerization
- **Docker Compose**: Multi-container orchestration
- **NVIDIA CUDA 12.1**: GPU acceleration (cuDNN 8)
- **Ubuntu 22.04**: Base operating system

## Quick Start

### Prerequisites

- **Docker** (20.10+) and **Docker Compose** (2.0+)
- **NVIDIA GPU** (optional, for acceleration)
  - CUDA-capable GPU with compute capability 7.0+
  - NVIDIA Driver 525+
  - nvidia-docker2 for container GPU access
- **8GB RAM minimum** (16GB+ recommended)
- **10GB disk space** for images and data

### Installation

1. **Clone or extract the repository**
   ```bash
   cd finai
   ```

2. **Run the startup script**
   ```bash
   ./scripts/start.sh
   ```

   The script will:
   - Check system requirements
   - Create necessary directories
   - Build Docker images
   - Start all services
   - Initialize the database

3. **Access the application**
   - Open your browser to `http://localhost:6789`
   - The system is ready when you see the dashboard

### First-Time Setup (via GUI)

1. **Configure Data Sources**
   - Navigate to "Data Sources" page
   - Add API keys (optional):
     - **Yahoo Finance**: No API key needed (free, built-in)
     - **FRED**: Get free key from https://fred.stlouisfed.org/
     - **Alpha Vantage**: Get free key from https://www.alphavantage.co/
     - **SEC Edgar**: Get free key from https://sec-api.io (100 requests/month free)
   - Or upload CSV files with your own data

2. **Add Assets to Monitor**
   - Go to "Assets" page
   - Add individual assets (e.g., AAPL, GOOGL) or
   - Bulk import from a list

3. **Configure System Parameters**
   - Open "Configuration" page
   - Adjust model parameters (defaults work for most cases):
     - **Hidden Dimension**: Model complexity (64-256)
     - **Number of Layers**: Model depth (2-4)
     - **Batch Size**: Training batch size (16-64)
     - **Learning Rate**: Training speed (0.0001-0.01)

4. **Start Data Collection**
   - Go to "Jobs" page
   - Click "Start Job" → Select "Data Collection"
   - Wait for completion (progress shown in real-time)

5. **Train the Model**
   - After data collection completes
   - Start a "Training" job
   - Monitor training progress and metrics

6. **Generate Predictions**
   - Start a "Prediction" job
   - View results on Dashboard
   - Export data as needed

## System Architecture

### Container Architecture

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

- **data_sources**: Configured data source connections
- **assets**: Financial assets being monitored
- **jobs**: Background task tracking and status
- **error_logs**: System error tracking and analytics
- **config**: System configuration parameters

### Background Jobs

All long-running tasks are processed asynchronously:
- **Data Collection**: Fetches data from configured sources
- **Training**: Trains the HGT model on collected data
- **Prediction**: Generates liquidity forecasts
- **Backtest**: Evaluates model performance on historical data

## Data Sources

### 1. Yahoo Finance (yfinance)
- **Cost**: Free, no API key required
- **Data**: Stock prices, volume, historical data
- **Rate Limit**: ~2000 requests/hour
- **Usage**: Primary source for equity data

### 2. FRED (Federal Reserve Economic Data)
- **Cost**: Free with API key registration
- **Data**: Economic indicators (GDP, unemployment, interest rates)
- **Rate Limit**: Unlimited for non-commercial use
- **Get API Key**: https://fred.stlouisfed.org/docs/api/api_key.html

### 3. Alpha Vantage
- **Cost**: Free tier: 5 calls/minute, 500/day
- **Data**: Stocks, forex, crypto, economic indicators
- **Paid Tiers**: Available for higher limits
- **Get API Key**: https://www.alphavantage.co/support/#api-key

### 4. SEC Edgar (sec-api.io)
- **Cost**: Free tier: 100 requests/month
- **Data**:
  - Company financials (10-K, 10-Q filings)
  - Institutional holdings (13F filings)
  - Insider trading (Form 4)
  - Proxy statements (DEF 14A)
  - Company facts and metrics
- **Paid Tiers**:
  - Starter: $49/month (1,000 requests)
  - Pro: $99/month (10,000 requests)
  - Enterprise: Custom pricing
- **Get API Key**: https://sec-api.io
- **Usage**: Access SEC Edgar filings data for fundamental analysis

### 5. CSV Upload
- **Cost**: Free
- **Format Requirements**:
  ```csv
  date,symbol,open,high,low,close,volume
  2024-01-01,AAPL,150.0,152.0,149.0,151.0,1000000
  ```
- **Usage**: Custom data or offline datasets

### 6. Custom API
- **Cost**: Depends on your API
- **Setup**: Configure endpoint, authentication in GUI
- **Usage**: Connect to proprietary data sources

## Machine Learning Model

### Heterogeneous Graph Transformer (HGT)

The system uses a Graph Neural Network architecture specifically designed for heterogeneous graphs (graphs with multiple node and edge types).

#### Model Architecture

```
Input Graph
    ↓
[HGT Layer 1]
├─ Multi-head Attention (8 heads)
├─ Message Passing (asset→asset, indicator→asset)
├─ Node Feature Transformation
└─ Skip Connection
    ↓
[HGT Layer 2]
├─ Multi-head Attention
├─ Message Passing
└─ Skip Connection
    ↓
[HGT Layer 3]
    ↓
[Prediction Head]
├─ Liquidity Score
├─ Volatility
└─ Risk Level
```

#### Node Types

- **Asset Nodes**: Individual stocks/securities with features:
  - Price history
  - Volume trends
  - Technical indicators

- **Indicator Nodes**: Economic/market indicators:
  - Interest rates
  - Market indices
  - Economic metrics

#### Edge Types

- **Asset-Asset**: Correlation-based relationships
- **Asset-Indicator**: Economic influence relationships
- **Temporal**: Time-series connections

#### Training Process

1. **Data Preparation**
   - Time window: Configurable (default: 90 days lookback)
   - Train/validation split: 80/20
   - Sequence length: 30 days

2. **Optimization**
   - Optimizer: Adam
   - Loss Function: MSE for regression + BCE for classification
   - Early Stopping: Patience = 10 epochs
   - Learning Rate Scheduling: ReduceLROnPlateau

3. **Hyperparameters** (all configurable via GUI):
   - `hidden_dim`: Feature dimension (default: 128)
   - `num_heads`: Attention heads (default: 8)
   - `num_layers`: GNN layers (default: 3)
   - `dropout`: Regularization (default: 0.1)
   - `learning_rate`: Training rate (default: 0.001)
   - `batch_size`: Samples per batch (default: 32)
   - `num_epochs`: Training iterations (default: 100)

#### Model Outputs

For each asset, the model predicts:
- **Liquidity Score**: 0.0 (illiquid) to 1.0 (highly liquid)
- **Volatility**: Expected standard deviation of returns
- **Risk Level**: Categorical (Low/Medium/High/Critical)
- **Confidence**: Prediction uncertainty

## Configuration Guide

### Model Parameters

Access via Configuration page → Model Parameters tab

| Parameter | Range | Default | Description | When to Adjust |
|-----------|-------|---------|-------------|----------------|
| **Hidden Dimension** | 64-256 | 128 | Size of internal representations | Increase for complex datasets, decrease for limited GPU memory |
| **Number of Heads** | 4-16 | 8 | Parallel attention mechanisms | More heads = more diverse patterns learned |
| **Number of Layers** | 2-5 | 3 | Depth of the network | More layers = longer-range relationships |
| **Dropout** | 0.0-0.5 | 0.1 | Regularization strength | Increase if overfitting occurs |
| **Learning Rate** | 0.0001-0.01 | 0.001 | Training step size | Decrease if training unstable, increase if too slow |

### Data Parameters

Access via Configuration page → Data Parameters tab

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| **Lookback Days** | 30-365 | 90 | Historical data to collect |
| **Prediction Horizon** | 1-30 | 7 | Days ahead to forecast |
| **Correlation Threshold** | 0.0-1.0 | 0.5 | Minimum correlation for graph edges |
| **Update Frequency** | 1-24 hours | 24 | How often to refresh data |
| **API Rate Limit** | 0.5-5 sec | 2.0 | Delay between API calls |

### Training Parameters

Access via Configuration page → Training Parameters tab

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| **Batch Size** | 8-128 | 32 | Samples per training batch |
| **Number of Epochs** | 10-500 | 100 | Maximum training iterations |
| **Early Stopping Patience** | 5-50 | 10 | Epochs without improvement before stopping |
| **Validation Split** | 0.1-0.3 | 0.2 | Portion of data for validation |

### Hardware-Specific Recommendations

The system provides automatic recommendations based on your hardware:

**Low RAM (< 16GB)**
- Hidden Dimension: 64
- Batch Size: 16
- Number of Layers: 2

**High RAM (32GB+)**
- Hidden Dimension: 256
- Batch Size: 64
- Number of Layers: 4

**No GPU / Limited GPU Memory**
- Hidden Dimension: 64-128
- Batch Size: 16-32
- Number of Layers: 2-3

**High-End GPU (24GB+ VRAM)**
- Hidden Dimension: 256
- Batch Size: 64-128
- Number of Layers: 4-5

## API Documentation

### Interactive Documentation

Full API documentation with interactive testing:
- **Swagger UI**: http://localhost:3456/docs
- **ReDoc**: http://localhost:3456/redoc

### Key Endpoints

#### Data Sources
- `GET /api/v1/data-sources` - List all data sources
- `POST /api/v1/data-sources` - Add new data source
- `PUT /api/v1/data-sources/{id}` - Update data source
- `POST /api/v1/data-sources/test` - Test connection

#### Assets
- `GET /api/v1/assets` - List monitored assets
- `POST /api/v1/assets` - Add single asset
- `POST /api/v1/assets/bulk` - Bulk import assets
- `DELETE /api/v1/assets/{id}` - Remove asset

#### Jobs
- `GET /api/v1/jobs` - List all jobs
- `POST /api/v1/jobs` - Start new job
- `GET /api/v1/jobs/{id}` - Get job status
- `DELETE /api/v1/jobs/{id}` - Cancel running job

#### Configuration
- `GET /api/v1/config` - Get current configuration
- `PUT /api/v1/config/model` - Update model parameters
- `PUT /api/v1/config/data` - Update data parameters
- `PUT /api/v1/config/training` - Update training parameters

#### System
- `GET /api/v1/system/status` - System health and resources
- `GET /api/v1/system/resources/recommendations` - Hardware-based recommendations

#### Errors
- `GET /api/v1/errors` - List error logs
- `GET /api/v1/errors/statistics` - Error analytics
- `POST /api/v1/errors/report` - Report client-side error

## Troubleshooting

### Common Issues

#### 1. "Cannot connect to Docker daemon"
**Solution**: Ensure Docker Desktop is running
```bash
# Check Docker status
docker ps
```

#### 2. "Port already in use"
**Solution**: Stop conflicting services or change ports in docker-compose.yml
```bash
# Check what's using port 3456
lsof -i :3456
```

#### 3. "GPU not available"
**Solutions**:
- Check NVIDIA drivers: `nvidia-smi`
- Install nvidia-docker2
- Or use CPU mode (slower but functional)

#### 4. "Out of memory error during training"
**Solutions**:
- Reduce batch size (Configuration → Training → Batch Size)
- Reduce hidden dimension (Configuration → Model → Hidden Dimension)
- Reduce number of layers
- Use fewer assets

#### 5. "Data collection job fails"
**Solutions**:
- Check API keys in Data Sources
- Verify internet connection
- Check Error Analytics page for details
- Ensure API rate limits not exceeded

#### 6. "Frontend shows 'Cannot connect to server'"
**Solutions**:
- Wait 1-2 minutes for backend to start
- Check backend logs: `docker-compose logs backend`
- Verify backend is running: `curl http://localhost:3456/health`

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f celery-worker

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Restarting Services

```bash
# Restart all services
docker-compose restart

# Restart specific service
docker-compose restart backend

# Full reset (deletes data!)
docker-compose down -v
./scripts/start.sh
```

### Error Analytics

The system tracks all errors automatically:
1. Navigate to "Error Analytics" page
2. View error statistics and trends
3. Filter by severity, category, or status
4. Click on errors for details and suggested solutions
5. Mark errors as resolved after fixing

---

**Version**: 2.0.0
