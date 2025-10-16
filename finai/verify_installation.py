"""Verify the installation."""

import sys
from pathlib import Path
import os

# Add src to path before running imports
SRC_PATH = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC_PATH))

try:
    from liquidity_monitor.utils.config import Config
    from liquidity_monitor.data.collection import DataCollector
    from liquidity_monitor.data.processing import DataProcessor, LiquidityDataset, collate_fn
    from liquidity_monitor.data.graph_builder import GraphBuilder
    from liquidity_monitor.models.hgt import HeteroLiquidityHGT
    from liquidity_monitor.pipeline import LiquidityMonitorPipeline
    from liquidity_monitor.visualization.dashboards import DashboardGenerator
    from liquidity_monitor.utils.cache import DataCache
    
    print("✅ All core modules imported successfully.")
    
    # Test configuration loading
    # We assume config.yaml is present in the relative path from the CWD (/Users/barisnacierzeren/Downloads/Finai)
    config_path = Path("liquidity_monitor_production_final/configs/config.yaml")
    if config_path.exists():
        config = Config(str(config_path))
        print("✅ Configuration loaded successfully.")
        
        # Test if essential lists are populated (basic sanity check post-config load)
        banks = config.data.get("banks", [])
        if banks:
            print(f"✅ Config check: Loaded {len(banks)} banks.")
        else:
            print("❌ Config check: No banks loaded (check config file structure).")
            
    else:
        print(f"❌ Configuration file not found at: {config_path}")
    
    # Test basic functionality (Instantiating components without calling heavy API functions)
    # Note: This will still fail if API keys are missing ONLY IF DataCollector/Config tries to access them, 
    # but we only instantiate DataCollector here which typically only fails on instantiation if API key getter errors out.
    
    # We test initialization instead of full run
    try:
        collector = DataCollector(config)
        print("✅ DataCollector initialized successfully.")
        
        graph_builder = GraphBuilder(config)
        assert len(graph_builder._asset_categories['banks']) > 0, "Asset categories not loaded into GraphBuilder."
        print("✅ GraphBuilder initialized successfully.")
        
        print("\\n✅ Installation verified successfully!")
        print("\\nNext steps:")
        print("1. Edit .env file with your actual API keys.")
        print("2. Run tests: pytest")
        print("3. Run example: python src/liquidity_monitor/main.py (or python main.py if running from project root)")
        
    except ValueError as e:
        print(f"⚠️ Initialization Warning (Expected if API keys are placeholders): {e}")
    except Exception as e:
        print(f"❌ Initialization failed during component instantiation: {e}")

except ImportError as e:
    print(f"❌ Critical Import Error: {e}")
    print("Please ensure Python dependencies listed in requirements.txt are installed.")
except Exception as e:
    print(f"❌ Unexpected Error during verification: {e}")
finally:
    # Clean up path modification
    if sys.path[0] == str(SRC_PATH):
        sys.path.pop(0)

</final_file_content>

IMPORTANT: For any future changes to this file, use the final_file_content shown above as your reference. This content reflects the current state of the file, including any auto-formatting (e.g., if you used single quotes but the formatter converted them to double quotes). Always base your SEARCH/REPLACE operations on this final version to ensure accuracy.<environment_details>
# Visual Studio Code Visible Files
liquidity_monitor_production_final/verify_installation.py

# Visual Studio Code Open Tabs
# ... (truncated list of files)
liquidity_monitor_production_final/notebooks/exploratory_analysis.ipynb
liquidity_monitor_production_final/verify_installation.py

# Current Time
10/16/2025, 2:17:05 PM (Europe/Istanbul, UTC+3:00)

# Context Window Usage
190,831 / 1,048.576K tokens used (18%)

# Current Mode
ACT MODE
</environment_details>
