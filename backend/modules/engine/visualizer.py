"""Result visualization for training outputs."""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Dict, List
import json

sns.set_style("whitegrid")


def create_training_report(job_dir: str, job_id: int) -> Dict[str, str]:
    """
    Create comprehensive training report with visualizations.

    Args:
        job_dir: Directory containing training outputs
        job_id: Job ID

    Returns:
        Dictionary mapping visualization names to file paths
    """
    job_path = Path(job_dir)

    # Load data
    predictions_df = pd.read_csv(job_path / 'predictions.csv')

    with open(job_path / 'training_history.json', 'r') as f:
        history = json.load(f)

    # Create visualizations
    viz_paths = {}

    # 1. Training/Validation Loss Curves
    viz_paths['loss_curves'] = _plot_loss_curves(history, job_path)

    # 2. Predictions vs Actual
    viz_paths['predictions'] = _plot_predictions(predictions_df, job_path)

    # 3. Error Distribution
    viz_paths['error_dist'] = _plot_error_distribution(predictions_df, job_path)

    # 4. Residuals Plot
    viz_paths['residuals'] = _plot_residuals(predictions_df, job_path)

    # 5. Summary Statistics
    viz_paths['summary'] = _create_summary_table(predictions_df, history, job_path)

    return viz_paths


def _plot_loss_curves(history: Dict, output_dir: Path) -> str:
    """Plot training and validation loss curves."""
    fig, ax = plt.subplots(figsize=(12, 6))

    epochs = list(range(1, len(history['train_loss']) + 1))
    ax.plot(epochs, history['train_loss'], label='Training Loss', linewidth=2, marker='o', markersize=4)
    ax.plot(epochs, history['val_loss'], label='Validation Loss', linewidth=2, marker='s', markersize=4)

    # Mark best epoch
    best_epoch = history['best_epoch'] + 1
    best_val_loss = history['val_loss'][history['best_epoch']]
    ax.axvline(x=best_epoch, color='r', linestyle='--', alpha=0.7, label=f'Best Epoch ({best_epoch})')
    ax.scatter([best_epoch], [best_val_loss], color='red', s=100, zorder=5)

    ax.set_xlabel('Epoch', fontsize=12)
    ax.set_ylabel('Loss (MSE)', fontsize=12)
    ax.set_title('Training and Validation Loss Over Time', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    # Use log scale if values vary greatly
    if max(history['train_loss']) / min(history['train_loss']) > 100:
        ax.set_yscale('log')
        ax.set_ylabel('Loss (MSE, log scale)', fontsize=12)

    plt.tight_layout()
    path = output_dir / 'loss_curves.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()

    return str(path)


def _plot_predictions(df: pd.DataFrame, output_dir: Path) -> str:
    """Plot predictions vs actual values."""
    fig, ax = plt.subplots(figsize=(12, 8))

    # Scatter plot
    ax.scatter(df['actual'], df['predicted'], alpha=0.5, s=30)

    # Perfect prediction line
    min_val = min(df['actual'].min(), df['predicted'].min())
    max_val = max(df['actual'].max(), df['predicted'].max())
    ax.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2, label='Perfect Prediction')

    # Add trend line
    z = np.polyfit(df['actual'], df['predicted'], 1)
    p = np.poly1d(z)
    ax.plot(df['actual'].sort_values(), p(df['actual'].sort_values()),
            'g-', linewidth=2, alpha=0.7, label=f'Trend Line (y={z[0]:.2f}x+{z[1]:.2f})')

    ax.set_xlabel('Actual Values', fontsize=12)
    ax.set_ylabel('Predicted Values', fontsize=12)
    ax.set_title('Predictions vs Actual Values', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add R² annotation
    ss_res = np.sum((df['actual'] - df['predicted']) ** 2)
    ss_tot = np.sum((df['actual'] - df['actual'].mean()) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    ax.text(0.05, 0.95, f'R² = {r2:.4f}', transform=ax.transAxes,
            fontsize=12, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    path = output_dir / 'predictions_vs_actual.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()

    return str(path)


def _plot_error_distribution(df: pd.DataFrame, output_dir: Path) -> str:
    """Plot error distribution."""
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))

    # Histogram
    axes[0].hist(df['error'], bins=50, alpha=0.7, edgecolor='black')
    axes[0].axvline(x=0, color='r', linestyle='--', linewidth=2)
    axes[0].set_xlabel('Prediction Error', fontsize=12)
    axes[0].set_ylabel('Frequency', fontsize=12)
    axes[0].set_title('Error Distribution', fontsize=14, fontweight='bold')
    axes[0].grid(True, alpha=0.3)

    # Add statistics
    mean_error = df['error'].mean()
    std_error = df['error'].std()
    axes[0].text(0.05, 0.95, f'Mean: {mean_error:.2f}\nStd: {std_error:.2f}',
                transform=axes[0].transAxes, fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # Box plot
    axes[1].boxplot([df['abs_error']], labels=['Absolute Error'])
    axes[1].set_ylabel('Absolute Error', fontsize=12)
    axes[1].set_title('Absolute Error Distribution', fontsize=14, fontweight='bold')
    axes[1].grid(True, alpha=0.3, axis='y')

    # Add statistics
    mae = df['abs_error'].mean()
    median_ae = df['abs_error'].median()
    q75 = df['abs_error'].quantile(0.75)
    axes[1].text(0.55, 0.95, f'MAE: {mae:.2f}\nMedian: {median_ae:.2f}\n75th %: {q75:.2f}',
                transform=axes[1].transAxes, fontsize=10, verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.tight_layout()
    path = output_dir / 'error_distribution.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()

    return str(path)


def _plot_residuals(df: pd.DataFrame, output_dir: Path) -> str:
    """Plot residuals."""
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))

    # Residuals vs Predicted
    axes[0].scatter(df['predicted'], df['error'], alpha=0.5, s=30)
    axes[0].axhline(y=0, color='r', linestyle='--', linewidth=2)
    axes[0].set_xlabel('Predicted Values', fontsize=12)
    axes[0].set_ylabel('Residuals', fontsize=12)
    axes[0].set_title('Residuals vs Predicted Values', fontsize=14, fontweight='bold')
    axes[0].grid(True, alpha=0.3)

    # Q-Q plot for normality check
    from scipy import stats
    stats.probplot(df['error'], dist="norm", plot=axes[1])
    axes[1].set_title('Q-Q Plot (Normality Check)', fontsize=14, fontweight='bold')
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    path = output_dir / 'residuals.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()

    return str(path)


def _create_summary_table(df: pd.DataFrame, history: Dict, output_dir: Path) -> str:
    """Create summary statistics table."""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis('tight')
    ax.axis('off')

    # Calculate metrics
    mae = df['abs_error'].mean()
    rmse = np.sqrt((df['error'] ** 2).mean())
    mape = (df['abs_error'] / df['actual'].abs()).mean() * 100

    ss_res = np.sum((df['actual'] - df['predicted']) ** 2)
    ss_tot = np.sum((df['actual'] - df['actual'].mean()) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Summary data
    summary_data = [
        ['Metric', 'Value'],
        ['─' * 30, '─' * 30],
        ['Training Metrics', ''],
        ['  Best Epoch', f"{history['best_epoch'] + 1} / {len(history['train_loss'])}"],
        ['  Final Train Loss', f"{history['train_loss'][-1]:.6f}"],
        ['  Best Val Loss', f"{min(history['val_loss']):.6f}"],
        ['', ''],
        ['Test Set Performance', ''],
        ['  Mean Absolute Error (MAE)', f'{mae:.4f}'],
        ['  Root Mean Squared Error (RMSE)', f'{rmse:.4f}'],
        ['  Mean Absolute % Error (MAPE)', f'{mape:.2f}%'],
        ['  R² Score', f'{r2:.4f}'],
        ['', ''],
        ['Data Statistics', ''],
        ['  Test Samples', f'{len(df)}'],
        ['  Actual Mean', f'{df["actual"].mean():.2f}'],
        ['  Actual Std', f'{df["actual"].std():.2f}'],
        ['  Predicted Mean', f'{df["predicted"].mean():.2f}'],
        ['  Predicted Std', f'{df["predicted"].std():.2f}'],
    ]

    table = ax.table(cellText=summary_data, cellLoc='left', loc='center',
                    colWidths=[0.6, 0.4])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 2)

    # Style header
    for i in range(2):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')

    # Style section headers
    for row in [2, 7, 12]:
        for col in range(2):
            table[(row, col)].set_facecolor('#E8F5E9')
            table[(row, col)].set_text_props(weight='bold')

    plt.title('Training Summary Report', fontsize=16, fontweight='bold', pad=20)

    path = output_dir / 'summary_table.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()

    return str(path)
