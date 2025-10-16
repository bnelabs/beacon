"""Main entry point for the liquidity monitor."""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path before importing project modules
# Determine project root here based on where main.py resides
PROJECT_ROOT = Path(__file__).parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

from liquidity_monitor.pipeline import LiquidityMonitorPipeline
from liquidity_monitor.utils.config import Config
from liquidity_monitor.utils.logger import setup_logger

# Load configuration globally to set logging parameters
CONFIG = Config()
LOG_LEVEL = CONFIG.get("logging.level", "INFO")
LOG_DIR = "logs" # Target 'logs' directory for file persistence, per docker-compose volume mapping

logger = setup_logger("main", log_dir=LOG_DIR, level=LOG_LEVEL)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Liquidity Monitor Pipeline")
    
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to configuration file (relative to CWD)"
    )
    
    parser.add_argument(
        "--train-start",
        type=str,
        default=None,
        help="Training start date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--train-end",
        type=str,
        default=None,
        help="Training end date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--test-start",
        type=str,
        default=None,
        help="Test start date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--test-end",
        type=str,
        default=None,
        help="Test end date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run walk-forward backtesting"
    )
    
    return parser.parse_args()


def run_backtesting(pipeline: LiquidityMonitorPipeline):
    """Run walk-forward backtesting."""
    logger.info("Starting walk-forward backtesting execution.")
    
    pipeline.run_backtesting()


def run_single_pipeline(pipeline: LiquidityMonitorPipeline, args):
    """Run a single pipeline execution using provided CLI dates or defaults."""
    
    # Default date logic revised for practicality:
    
    # 1. Determine TEST END date (T_test_end)
    if args.test_end:
        test_end_str = args.test_end
    else:
        # Default to today if not specified
        test_end_str = datetime.now().strftime("%Y-%m-%d")
    test_end_dt = datetime.strptime(test_end_str, "%Y-%m-%d")

    # 2. Determine TRAIN END date (T_train_end)
    if args.train_end:
        train_end_str = args.train_end
    else:
        # Default train_end to one year before test_end
        split_date = test_end_dt - timedelta(days=365)
        train_end_str = split_date.strftime("%Y-%m-%d")
        
    train_end_dt = datetime.strptime(train_end_str, "%Y-%m-%d")

    # 3. Determine TEST START date (T_test_start)
    if args.test_start:
        test_start_str = args.test_start
    else:
        # Default test_start to one year after train_end (approx)
        test_start_dt = train_end_dt + timedelta(days=1)
        test_start_str = test_start_dt.strftime("%Y-%m-%d")

    # 4. Determine TRAIN START date (T_train_start)
    if args.train_start:
        train_start_str = args.train_start
    else:
        # Default train_start to 10 years before train_end
        default_train_start = train_end_dt - timedelta(days=3650)
        train_start_str = default_train_start.strftime("%Y-%m-%d")
    
    logger.info(f"Executing single run pipeline:")
    logger.info(f"- Train Period: {train_start_str} to {train_end_str}")
    logger.info(f"- Test Period: {test_start_str} to {test_end_str}")

    results = pipeline.run_pipeline(
        train_start_str, train_end_str, test_start_str, test_end_str
    )
    
    logger.info("Pipeline execution complete")
    logger.info(f"Results: {results}")


def main():
    """Main function."""
    args = parse_arguments()
    
    # Initialize pipeline (config_path will be relative to CWD /Users/barisnacierzeren/Downloads/Finai)
    pipeline = LiquidityMonitorPipeline(args.config)
    
    if args.backtest:
        # Run backtesting
        run_backtesting(pipeline)
    else:
        # Run single pipeline
        run_single_pipeline(pipeline, args)


if __name__ == "__main__":
    main()
</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
liquidity_monitor_production_final/src/liquidity_monitor/main.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/src/liquidity_monitor/pipeline.py
liquidity_monitor_production_final/src/liquidity_monitor/main.py

# Current Time
10/16/2025, 2:15:42 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
149,752 / 1,048.576K tokens used (14%)

# Current Mode
ACT MODE
</environment_details>
