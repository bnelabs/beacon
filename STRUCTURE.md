# FinAI Project Structure

This document describes the project's folder structure following industry best practices.

```
finai/
├── backend/                    # Backend application (FastAPI + ML)
│   ├── api/                    # REST API layer
│   │   ├── routes/             # API route handlers
│   │   │   ├── __init__.py
│   │   │   ├── assets.py
│   │   │   ├── config.py
│   │   │   ├── data_sources.py
│   │   │   ├── errors.py
│   │   │   ├── jobs.py
│   │   │   └── system.py
│   │   └── main.py             # FastAPI application entry point
│   ├── core/                   # Core ML and data processing
│   │   ├── data/               # Data collection and processing
│   │   ├── models/             # ML model implementations
│   │   ├── plugins/            # Data source plugins
│   │   ├── utils/              # Utilities (config, logging, cache)
│   │   └── visualization/      # Visualization modules
│   ├── models/                 # Database ORM models
│   ├── schemas/                # Pydantic schemas
│   ├── services/               # Business logic services
│   ├── tasks/                  # Celery background tasks
│   ├── database.py             # Database configuration
│   ├── __init__.py
│   └── Dockerfile              # Backend Docker image
│
├── frontend/                   # Frontend application (React)
│   ├── src/
│   │   ├── api/                # API client
│   │   ├── components/         # React components
│   │   ├── hooks/              # Custom React hooks
│   │   ├── pages/              # Page components
│   │   ├── services/           # Frontend services
│   │   ├── App.jsx             # Root component
│   │   └── main.jsx            # Entry point
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile              # Frontend Docker image
│
├── configs/                    # Configuration files
│   └── config.yaml             # System configuration
│
├── data/                       # Data storage (gitignored)
│   ├── raw/                    # Raw collected data
│   ├── processed/              # Processed features
│   └── cache/                  # Cached data
│
├── models/                     # Trained model storage (gitignored)
│   └── saved/                  # Saved model checkpoints
│
├── logs/                       # Application logs (gitignored)
│
├── results/                    # Prediction results (gitignored)
│
├── tests/                      # Test suite
│   ├── unit/                   # Unit tests
│   └── integration/            # Integration tests
│
├── scripts/                    # Utility scripts
│   └── start.sh                # Startup script
│
├── docs/                       # Additional documentation
│
├── notebooks/                  # Jupyter notebooks for analysis
│
├── docker-compose.yml          # Multi-container orchestration
├── requirements.txt            # Python dependencies
├── pytest.ini                  # Pytest configuration
├── .env                        # Environment variables (gitignored)
├── .gitignore                  # Git ignore rules
├── .dockerignore               # Docker ignore rules
├── README.md                   # Main documentation
└── STRUCTURE.md                # This file
```

## Key Design Principles

### 1. Separation of Concerns
- **backend/api**: HTTP layer only, delegates to services
- **backend/core**: Core ML logic, independent of API
- **backend/services**: Business logic, orchestrates core + models
- **backend/models**: Database schema only
- **backend/schemas**: Request/response validation

### 2. Clean Architecture
- Dependencies point inward
- Core has no external dependencies
- API layer is thin, delegates to services
- Easy to test, maintain, and scale

### 3. Monorepo Structure
- Single repository for frontend + backend
- Separate Docker images for each service
- Shared configuration at root level
- Independent deployment possible

### 4. Data Organization
- Runtime data (data/, logs/, results/) in gitignore
- Configuration versioned (configs/)
- Models versioned separately or ignored based on size

## Module Responsibilities

### Backend
- **api/**: HTTP handling, request validation, response formatting
- **core/**: Machine learning, data processing, graph neural networks
- **models/**: SQLAlchemy ORM models for PostgreSQL
- **schemas/**: Pydantic models for API validation
- **services/**: Business logic, error handling, orchestration
- **tasks/**: Celery background jobs (training, prediction, data collection)

### Frontend
- **api/**: Axios client for backend communication
- **components/**: Reusable React components
- **hooks/**: Custom hooks for state and effects
- **pages/**: Full page components (Dashboard, Assets, Jobs, etc.)
- **services/**: Frontend utilities and helpers

## Import Conventions

### Backend
- Use relative imports within modules: `from .models import Asset`
- Absolute imports from package root: `from api.main import app`
- No circular dependencies

### Frontend
- Use absolute imports: `import Button from 'components/Button'`
- Configured in vite.config.js

## Docker Structure

Each service has its own Dockerfile in its directory:
- `backend/Dockerfile`: CUDA-enabled Python environment
- `frontend/Dockerfile`: Node.js Alpine image
- `docker-compose.yml`: Orchestrates all services
