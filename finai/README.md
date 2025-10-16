# Liquidity Monitor Production System

A production-grade financial liquidity monitoring system that uses heterogeneous graph neural networks to predict liquidity risk across global financial markets.

## Features

- **Heterogeneous Graph Modeling**: Captures complex relationships between different types of financial entities
- **Walk-Forward Backtesting**: Implements gold-standard backtesting methodology to avoid look-ahead bias
- **Real-Time Data Integration**: Fetches data from multiple sources (Yahoo Finance, FRED, SEC EDGAR)
- **Production Architecture**: Modular, testable, and maintainable codebase following best practices
- **Data Caching**: Efficient caching mechanism to avoid repeated API calls
- **Comprehensive Logging**: Structured logging for monitoring and debugging
- **Containerization with Docker/Docker Compose**: Facilitates reproducible deployment
- **Interactive Visualizations**: Rich dashboards and graph visualizations

## Project Structure

```
liquidity_monitor_production_final/
├── configs/
│   └── config.yaml              # Main configuration file
├── data/
│   ├── raw/                     # Raw downloaded data
│   ├── processed/               # Processed features
│   ├── external/                # External reference data
│   └── cache/                   # Cached data files (managed by system)
├── src/
│   └── liquidity_monitor/      # Python Package Root
│       ├── data/
│       │   ├── collection.py    # Data collection module (Handles API calls + Rate Limiting)
│       │   ├── processing.py    # Data processing and feature engineering
│       │   └── graph_builder.py # Graph construction
│       ├── models/
│       │   ├── hgt.py           # Heterogeneous Graph Transformer model
│       │   └── training.py      # Training and evaluation logic
│       ├── utils/
│       │   ├── config.py        # Configuration management
│       │   ├── logger.py        # Logging utilities
│       │   ├── validation.py    # Data validation using Pandera
│       │   └── cache.py         # Data caching utilities (Parquet/Feather support)
│       ├── visualization/
│       │   └── dashboards.py    # Visualization and dashboard generation
│       └── pipeline.py          # Main pipeline orchestration
├── tests/
│   ├── unit/                    # Unit tests (Covering utils, processing, graph building)
│   └── integration/             # Integration tests (Covering end-to-end flow using mocks)
├── notebooks/
│   └── exploratory_analysis.ipynb # Example EDA Notebook
├── models/saved/                # Saved model artifacts (.pth)
├── results/
│   ├── backtests/              # Backtesting results files (.csv, dashboards)
│   └── dashboards/             # Visualization outputs (.html)
├── logs/                       # Log files
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
├── docker-compose.yml          # Docker Compose configuration
├── .env                        # Environment variables template (API keys secrets)
├── pytest.ini                 # Test configuration
└── main.py                     # Main entry point script
```

## Getting Started & Running

### 1. Setup Environment & Install Dependencies

First, ensure you are in the root directory (`/Users/barisnacierzeren/Downloads/Finai/liquidity_monitor_production_final`).

```bash
# On macOS/Linux where Python/pip is available
pip install -r requirements.txt
```

### 2. Configure API Keys

Edit the `.env` file located in the root directory and replace placeholders with your actual credentials for FRED and SEC APIs.

### 3. Run a Single Pipeline Execution

Run a standard prediction cycle using default date ranges (or specify them via arguments):
```bash
python main.py
# Example with custom dates:
# python main.py --train-start 2022-01-01 --train-end 2022-12-31 --test-start 2023-01-01 --test-end 2023-12-31
```

### 4. Run Walk-Forward Backtesting

Execute the multi-year backtesting routine defined by default:
```bash
python main.py --backtest
```

### 5. Verification and Testing

Verify that all modules import correctly and the configuration loads:
```bash
python verify_installation.py
```
Run the integrated test suite with coverage reporting:
```bash
pytest
# Or for detailed HTML report:
# pytest --cov-report=html
```

## Docker Deployment

For reproducible environments and deployment:

1. **Build the Docker image:** (Ensure you are in the root directory)
```bash
docker build -t liquidity-monitor .
```

2. **Run the container:** (Set environment variables for API keys if running locally)
```bash
export FRED_API_KEY="your_key"
export SEC_API_KEY="your_key"
docker run -e FRED_API_KEY -e SEC_API_KEY -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs liquidity-monitor
```
*(We rely on the host directory mounting defined in `docker-compose.yml` for persistence, but the above shows running a standalone container)*

You can also use `docker-compose.yml` for a simpler setup:
```bash
docker-compose up --build
```

## Key Production Enhancements

*   **Rate Limiting**: Added mandatory sleep intervals during batch asset downloading to respect external API rate limits (**Supervisor Feedback Addressed**).
*   **Code Correctness**: Critical library imports (`pandera`, `pandas`) fixed in utility and model files based on supervisor review.
*   **Robustness**: Enhanced graph building logic, sequence preparation, and input handling in the HGT model forward pass.
*   **Verification**: Added `verify_installation.py` script and comprehensive `.gitignore`.
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
liquidity_monitor_production_final/README.md

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/tests/integration/test_pipeline.py
liquidity_monitor_production_final/notebooks/exploratory_analysis.ipynb
liquidity_monitor_production_final/README.md

# Current Time
10/16/2025, 2:16:17 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
203,499 / 1,048.576K tokens used (19%)

# Current Mode
ACT MODE
</environment_details>
