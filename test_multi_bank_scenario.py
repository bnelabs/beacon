"""
Multi-Bank Scenario Test: HSBC, Citibank, Bank of America, JPMorgan Chase, Wells Fargo

This script creates a comprehensive test scenario for liquidity risk analysis
across multiple major banks using real financial data.
"""

import requests
import json
import time
from datetime import datetime

API_BASE = "http://localhost:3456/api/v1"

def print_section(title):
    print("\n" + "="*80)
    print(f" {title}")
    print("="*80)

def check_health():
    """Check if API is healthy"""
    print_section("CHECKING API HEALTH")
    response = requests.get(f"{API_BASE}/../health")
    print(f"✓ API Status: {response.json()}")
    return response.status_code == 200

def get_catalogue_items():
    """Get available data catalogue items"""
    print_section("FETCHING DATA CATALOGUE")
    response = requests.get(f"{API_BASE}/catalogue")
    items = response.json()

    print(f"✓ Total items available: {len(items)}")

    # Group by source
    by_source = {}
    for item in items:
        source = item['data_source']['plugin_type']
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(item)

    print("\nItems by source:")
    for source, source_items in sorted(by_source.items()):
        print(f"  - {source}: {len(source_items)} items")

    return items

def select_bank_relevant_data(items):
    """Select data relevant for bank liquidity risk analysis"""
    print_section("SELECTING BANK-RELEVANT DATA")

    # Keywords for bank-relevant data
    bank_keywords = [
        'bank', 'credit', 'loan', 'deposit', 'reserve',
        'fed_funds', 'sofr', 'treasury', 'libor', 'commercial',
        'mortgage', 'asset', 'liability', 'capital'
    ]

    selected = []

    # Select FRED data (most comprehensive for US banks)
    fred_items = [i for i in items if i['data_source']['plugin_type'] == 'fred' and i['default_selected']]
    selected.extend([i['id'] for i in fred_items[:10]])  # Top 10 FRED items
    print(f"✓ Selected {len(fred_items[:10])} FRED items")

    # Select ECB data (European banks exposure)
    ecb_items = [i for i in items if i['data_source']['plugin_type'] == 'ecb' and i['default_selected']]
    selected.extend([i['id'] for i in ecb_items[:5]])  # Top 5 ECB items
    print(f"✓ Selected {len(ecb_items[:5])} ECB items")

    # Select World Bank data
    wb_items = [i for i in items if i['data_source']['plugin_type'] == 'world_bank']
    selected.extend([i['id'] for i in wb_items[:3]])
    print(f"✓ Selected {len(wb_items[:3])} World Bank items")

    # Select BIS data (international banking)
    bis_items = [i for i in items if i['data_source']['plugin_type'] == 'bis']
    selected.extend([i['id'] for i in bis_items[:2]])
    print(f"✓ Selected {len(bis_items[:2])} BIS items")

    print(f"\n✓ Total selected: {len(selected)} data items")
    return selected

def create_data_collection_job(catalogue_items):
    """Create and monitor data collection job"""
    print_section("STARTING DATA COLLECTION JOB")

    job_data = {
        "name": "Multi-Bank Scenario - Data Collection",
        "description": "Collecting data for HSBC, Citi, BOFA, JPMorgan, Wells Fargo liquidity analysis",
        "job_type": "data_collection",
        "parameters": {
            "catalogue_items": catalogue_items,
            "start_date": "2023-01-01",
            "end_date": "2024-12-31"
        },
        "scheduled": False
    }

    response = requests.post(f"{API_BASE}/jobs", json=job_data)
    job = response.json()
    job_id = job['id']

    print(f"✓ Job created: #{job_id}")
    print(f"  Name: {job['name']}")
    print(f"  Type: {job['job_type']}")
    print(f"  Status: {job['status']}")

    # Monitor job progress
    print("\nMonitoring progress...")
    while True:
        time.sleep(3)
        response = requests.get(f"{API_BASE}/jobs/{job_id}")
        job = response.json()

        status = job['status']
        progress = job.get('progress', 0)

        print(f"  Status: {status:12} Progress: {progress:3.0f}%", end='\r')

        if status in ['completed', 'failed']:
            print()  # New line after progress
            break

    if status == 'completed':
        print(f"\n✓ Data collection COMPLETED")
        result = job.get('result', {})
        print(f"  Quality Score: {result.get('quality_score', 0):.1f}%")
        print(f"  Completeness: {result.get('completeness', 0):.1f}%")
        print(f"  Fit for Engine: {result.get('fit_for_engine', False)}")
        return job_id, True
    else:
        print(f"\n✗ Data collection FAILED")
        print(f"  Error: {job.get('error_message', 'Unknown error')}")
        return job_id, False

def create_training_job(data_job_id):
    """Create and monitor training job"""
    print_section("STARTING TRAINING JOB (Multi-Scale Model)")

    job_data = {
        "name": "Multi-Bank Liquidity Risk Training",
        "description": "Training multi-scale model for HSBC, Citi, BOFA, JPMorgan, Wells Fargo",
        "job_type": "training",
        "parameters": {
            "data_job_id": data_job_id,
            "train_start": "2023-01-01",
            "train_end": "2024-06-30",
            "test_start": "2024-07-01",
            "test_end": "2024-12-31",
            "config": {
                "model": "temporal_attention",
                "epochs": 50,
                "learning_rate": 0.0005,
                "batch_size": 32,
                "d_model": 128,
                "nhead": 8,
                "num_layers": 3,
                "sequence_length": 30,
                "dropout": 0.1,
                "weight_decay": 0.01
            }
        },
        "scheduled": False
    }

    response = requests.post(f"{API_BASE}/jobs", json=job_data)
    job = response.json()
    job_id = job['id']

    print(f"✓ Training job created: #{job_id}")
    print(f"  Model: Multi-Scale Temporal Attention")
    print(f"  Epochs: 50")
    print(f"  Status: {job['status']}")

    # Monitor job progress
    print("\nMonitoring training progress (this may take 5-15 minutes)...")
    last_progress = -1
    while True:
        time.sleep(5)
        response = requests.get(f"{API_BASE}/jobs/{job_id}")
        job = response.json()

        status = job['status']
        progress = job.get('progress', 0)

        if progress != last_progress:
            print(f"  Status: {status:12} Progress: {progress:3.0f}%")
            last_progress = progress

        if status in ['completed', 'failed']:
            break

    if status == 'completed':
        print(f"\n✓ Training COMPLETED")
        result = job.get('result', {})
        print(f"\n  MODEL PERFORMANCE:")
        print(f"    R² Score:  {result.get('test_r2', 0):.6f}")
        print(f"    MAE:       {result.get('test_mae', 0):.6f}")
        print(f"    RMSE:      {result.get('test_rmse', 0):.6f}")
        print(f"    Epochs:    {result.get('epochs_trained', 0)}")
        print(f"    Best Epoch: {result.get('best_epoch', 0)}")
        return job_id, True
    else:
        print(f"\n✗ Training FAILED")
        print(f"  Error: {job.get('error_message', 'Unknown error')}")
        return job_id, False

def check_results(job_id):
    """Check and display results"""
    print_section(f"CHECKING RESULTS FOR JOB #{job_id}")

    # Executive Summary
    try:
        response = requests.get(f"{API_BASE}/explainability/{job_id}/executive-summary")
        summary = response.json()
        print("\n📊 EXECUTIVE SUMMARY:")
        print(summary.get('summary', 'Not available'))
    except Exception as e:
        print(f"  Executive summary not available: {e}")

    # AI Explainability
    try:
        response = requests.get(f"{API_BASE}/explainability/{job_id}/explanation")
        explanation = response.json()
        print("\n🤖 AI EXPLAINABILITY:")
        print(f"  Compliance: {explanation.get('explainability_compliance', 'Unknown')}")
        print(f"  Summary: {explanation.get('summary', 'Not available')}")

        # Feature importance
        feature_importance = explanation.get('feature_importance', {})
        if feature_importance:
            print(f"\n  Top 5 Important Features:")
            sorted_features = sorted(feature_importance.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
            for i, (feature, importance) in enumerate(sorted_features, 1):
                print(f"    {i}. {feature}: {importance:.4f}")
    except Exception as e:
        print(f"  AI explainability not available: {e}")

    # Per-Bank Risks
    try:
        response = requests.get(f"{API_BASE}/explainability/{job_id}/bank-risks")
        bank_risks = response.json()

        if bank_risks.get('banks'):
            print("\n🏦 PER-BANK LIQUIDITY RISK:")
            print(f"  Summary: {bank_risks.get('summary', '')}")

            for bank in bank_risks['banks']:
                print(f"\n  {bank['bank_name']} ({bank['bank_id']}):")
                print(f"    Overall Risk: {bank['overall_risk_percentage']:.1f}% ({bank['risk_level']})")
                print(f"    Confidence: {bank['confidence_range']['lower']:.1f}% - {bank['confidence_range']['upper']:.1f}%")

                if bank.get('top_vulnerabilities'):
                    print(f"    Top Vulnerabilities:")
                    for vuln in bank['top_vulnerabilities'][:2]:
                        print(f"      • {vuln}")

                if bank.get('recommendations'):
                    print(f"    Recommendations:")
                    for rec in bank['recommendations'][:2]:
                        print(f"      • {rec}")

                if bank.get('is_systemically_important'):
                    print(f"    ⚠️  SYSTEMICALLY IMPORTANT ({bank['systemic_importance_percentage']:.1f}%)")
        else:
            print("\n  Per-bank risk data not available (requires multi-bank dataset)")
    except Exception as e:
        print(f"  Per-bank risks not available: {e}")

    # Contagion Analysis
    try:
        response = requests.get(f"{API_BASE}/explainability/{job_id}/contagion-analysis")
        contagion = response.json()

        if contagion.get('system_health'):
            print("\n🔗 CONTAGION ANALYSIS:")
            health = contagion['system_health']
            print(f"  System Health:")
            print(f"    Average Risk: {health.get('avg_risk_percentage', 0):.1f}%")
            print(f"    Max Risk: {health.get('max_risk_percentage', 0):.1f}%")
            print(f"    Systemic Risk: {health.get('systemic_risk_percentage', 0):.1f}%")
            print(f"    Critical Banks: {health.get('num_critical_risk_banks', 0)}")

            # Systemic banks
            if contagion.get('systemic_banks'):
                print(f"\n  Systemically Important Banks:")
                for bank in contagion['systemic_banks'][:3]:
                    print(f"    • {bank['bank_id']}: {bank['systemic_importance_percentage']:.1f}% ({bank['reason']})")

            # Cascade scenarios
            if contagion.get('cascade_scenarios'):
                print(f"\n  Cascade Scenarios:")
                for scenario in contagion['cascade_scenarios'][:3]:
                    print(f"    • If {scenario['initial_failure']} fails:")
                    print(f"      → {scenario['total_failures']} banks affected")
                    print(f"      → Cascade depth: {scenario['cascade_depth']} rounds")
                    print(f"      → Severity: {scenario['severity']}")
        else:
            print("\n  Contagion analysis not available (requires multi-bank dataset with exposures)")
    except Exception as e:
        print(f"  Contagion analysis not available: {e}")

    # Visualizations
    print("\n📈 VISUALIZATIONS:")
    viz_names = ['loss_curves', 'predictions_vs_actual', 'error_distribution', 'residuals', 'summary_table']
    for viz in viz_names:
        viz_url = f"{API_BASE}/explainability/{job_id}/visualizations/{viz}"
        print(f"  • {viz}: {viz_url}")

    # Download links
    print("\n💾 DOWNLOAD:")
    print(f"  • CSV: {API_BASE}/explainability/{job_id}/download/predictions?format=csv")
    print(f"  • Excel: {API_BASE}/explainability/{job_id}/download/predictions?format=excel")

def main():
    """Run complete multi-bank scenario test"""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                                                                            ║
║           BEACON - Multi-Bank Liquidity Risk Analysis Test                ║
║                                                                            ║
║  Testing banks: HSBC, Citibank, Bank of America, JPMorgan, Wells Fargo   ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)

    start_time = datetime.now()

    # Step 1: Health check
    if not check_health():
        print("✗ API is not healthy. Exiting.")
        return

    # Step 2: Get catalogue
    items = get_catalogue_items()
    if not items:
        print("✗ No catalogue items available. Exiting.")
        return

    # Step 3: Select bank-relevant data
    selected_items = select_bank_relevant_data(items)

    # Step 4: Data collection
    data_job_id, success = create_data_collection_job(selected_items)
    if not success:
        print("✗ Data collection failed. Cannot proceed with training.")
        return

    # Step 5: Training
    training_job_id, success = create_training_job(data_job_id)
    if not success:
        print("✗ Training failed. Cannot proceed with results.")
        return

    # Step 6: Check results
    check_results(training_job_id)

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print_section("TEST COMPLETED")
    print(f"✓ Data Collection Job: #{data_job_id}")
    print(f"✓ Training Job: #{training_job_id}")
    print(f"✓ Total Duration: {duration:.0f} seconds ({duration/60:.1f} minutes)")
    print(f"\n✓ View results at: http://localhost:6789/results")
    print(f"✓ Select Job #{training_job_id} to see all visualizations and analysis")
    print("\n" + "="*80)

if __name__ == "__main__":
    main()
