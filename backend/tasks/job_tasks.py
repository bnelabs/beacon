"""Celery tasks for background jobs."""

from celery import Task
import traceback
import logging
from datetime import datetime, timedelta, timezone
import psutil
import os
from pathlib import Path

from .celery_app import celery_app
from backend.database import SessionLocal
from backend.modules.data.quality_gate import DataQualityGate
from backend.services.job_service import JobService
from backend.services.enhanced_error_translator import translate_error_enhanced as translate_error
import json
from dataclasses import asdict
import numpy as np

logger = logging.getLogger(__name__)


def convert_numpy_types(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    return obj


def persist_risk_scores(db, job_id: int, predictions_df, model_version: str, horizon_days: int) -> int:
    """Write prediction outputs to the risk-score hypertable.

    The risk_scores and model_metrics hypertables existed since the
    TimescaleDB migration but nothing ever wrote to them -- the fifth-round
    review named this explicitly. Scores are persisted with their provenance
    (job, model version, horizon); an uncalibrated score is stored with
    ``risk_level`` null rather than a fabricated band.
    """
    from backend.modules.results.timeseries_store import TimeSeriesStore

    now = datetime.now(timezone.utc)
    rows = []
    has_score = 'risk_score' in predictions_df.columns
    has_source = 'source' in predictions_df.columns
    has_bank = 'bank_id' in predictions_df.columns
    has_level = 'risk_level' in predictions_df.columns
    for _, record in predictions_df.iterrows():
        if not has_score:
            continue
        score = record['risk_score']
        entity = record['source'] if has_source else (record['bank_id'] if has_bank else None)
        if score is None or entity is None or np.isnan(float(score)):
            continue
        rows.append({
            "time": now,
            "entity_type": "source" if has_source else "bank",
            "entity_id": str(entity),
            "model_version": str(model_version)[:50],
            "horizon_days": int(horizon_days),
            "risk_score": float(score),
            "risk_level": (str(record['risk_level']) if has_level and record['risk_level'] else None),
            "prediction_job_id": int(job_id),
        })
    if not rows:
        return 0
    return TimeSeriesStore(db).record_risk_scores(rows)


def persist_model_metrics(db, job_id: int, metrics: dict, model_version: str) -> int:
    """Write scalar backtest/evaluation metrics to the metrics hypertable."""
    from backend.modules.results.timeseries_store import TimeSeriesStore

    now = datetime.now(timezone.utc)
    rows = []
    for name, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not np.isfinite(float(value)):
            continue
        rows.append({
            "time": now,
            "job_id": int(job_id),
            "metric_name": str(name)[:64],
            "metric_value": float(value),
            "model_version": str(model_version)[:50],
        })
    if not rows:
        return 0
    return TimeSeriesStore(db).record_model_metrics(rows)


def error_details_to_json(error_details) -> str:
    """Convert ErrorDetails (dict or dataclass) to JSON string for database storage."""
    try:
        # If it's already a dict, use it directly
        if isinstance(error_details, dict):
            error_dict = error_details
        else:
            # Try to convert dataclass to dict
            error_dict = asdict(error_details)
            # Convert Enum values to strings if present
            if 'severity' in error_dict and hasattr(error_dict['severity'], 'value'):
                error_dict['severity'] = error_dict['severity'].value
            if 'category' in error_dict and hasattr(error_dict['category'], 'value'):
                error_dict['category'] = error_dict['category'].value
        return json.dumps(error_dict)
    except Exception as e:
        logger.error(f"Failed to convert error details to JSON: {e}")
        return json.dumps({"user_message": "An error occurred", "technical_message": str(error_details)})


class JobTask(Task):
    """Base task with progress tracking and error handling."""

    def update_progress(self, job_id: int, progress: float, status: str = "running", current_step: str = None):
        """Update job progress in database."""
        db = SessionLocal()
        try:
            service = JobService(db)
            service.update_job_status(job_id, status=status, progress=progress, current_step=current_step)
        finally:
            db.close()

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        job_id = args[0] if args else None
        if job_id:
            db = SessionLocal()
            try:
                service = JobService(db)
                user_friendly = translate_error(exc, context="running job")
                service.update_job_status(
                    job_id,
                    status="failed",
                    error_message=str(exc),
                    user_friendly_error=error_details_to_json(user_friendly)
                )
                logger.error(f"Job {job_id} failed: {exc}\n{einfo}")
            finally:
                db.close()


@celery_app.task(base=JobTask, bind=True, name="run_data_collection")
def run_data_collection(self, job_id: int, parameters: dict):
    """
    Run data collection job.

    **For non-technical users:** This downloads the latest market data
    from your configured data sources.
    """
    db = SessionLocal()
    process = psutil.Process(os.getpid())
    start_memory = process.memory_info().rss / (1024 ** 2)  # MB
    started_at = datetime.now(timezone.utc)

    try:
        service = JobService(db)
        service.update_job_status(job_id, status="running", progress=0.0)

        # Import the new modular data collection system
        from backend.modules.data.orchestrator import DataOrchestrator

        logger.info(f"Starting data collection for job {job_id}")

        # Initialize data orchestrator
        self.update_progress(job_id, 10.0)
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Create progress callback - orchestrator already sends progress in 0-100 range
        def orchestrator_progress_callback(progress: float, message: str):
            try:
                # Orchestrator sends progress 0-100, we just pass it through
                logger.info(f"[job_{job_id}] Progress callback: {progress}% - {message}")
                self.update_progress(job_id, progress, current_step=message)
            except Exception as e:
                logger.error(f"[job_{job_id}] Error in progress callback: {e}")

        orchestrator = DataOrchestrator(db, f"job_{job_id}", output_dir, progress_callback=orchestrator_progress_callback)

        # Run data collection - progress will be reported via callback (20%-95%)
        # No need for manual update_progress call here

        # Get catalogue items from parameters
        catalogue_items = parameters.get('catalogue_items')
        if not catalogue_items:
            # No items specified - fetch items marked as default_selected from database
            from backend.models.data_catalogue import DataCatalogueItem
            default_items = db.query(DataCatalogueItem).filter(
                DataCatalogueItem.default_selected == True,
                DataCatalogueItem.enabled == True
            ).all()
            catalogue_items = [item.id for item in default_items]
            logger.info(f"No items specified, using {len(catalogue_items)} default catalogue items")

        selected_regions = [str(region) for region in parameters.get('regions', []) if region]
        selected_countries = [str(country) for country in parameters.get('countries', []) if country]

        # Default to ~5 years of history for better coverage of annual/quarterly data
        today = datetime.now(timezone.utc).date()
        default_start = (today - timedelta(days=5 * 365)).isoformat()
        default_end = today.isoformat()
        start_date = parameters.get('start_date') or default_start
        end_date = parameters.get('end_date') or default_end
        raw_fail_on_any_error = parameters.get("fail_on_any_error", True)
        if isinstance(raw_fail_on_any_error, str):
            fail_on_any_error = raw_fail_on_any_error.strip().lower() not in {
                "0", "false", "no", "off"
            }
        else:
            fail_on_any_error = bool(raw_fail_on_any_error)

        logger.info(
            "Running data collection with %d catalogue items (regions=%s, countries=%s, strict=%s)...",
            len(catalogue_items),
            selected_regions or "all",
            selected_countries or "all",
            fail_on_any_error,
        )

        # Run the complete data pipeline
        data_package = orchestrator.run(
            catalogue_items=catalogue_items,
            start_date=start_date,
            end_date=end_date,
            user_id="system",
            countries=selected_countries or None,
            regions=selected_regions or None,
            fail_on_any_error=fail_on_any_error,
        )

        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare results (convert numpy types to Python types)
        result = convert_numpy_types({
            "quality_score": data_package.quality_report.quality_score,
            "completeness": data_package.quality_report.completeness,
            "fit_for_engine": data_package.quality_report.fit_for_engine,
            "anomalies_detected": data_package.quality_report.anomalies_detected,
            "quality_attestation": (data_package.metadata or {}).get("quality_attestation"),
            # Content address of the exact rows this verdict was issued against.
            "snapshot_id": (data_package.metadata or {}).get("snapshot_id"),
            "dataset_snapshot": (data_package.metadata or {}).get("dataset_snapshot"),
            "output_path": data_package.timeseries_path,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "regions": selected_regions,
            "countries": selected_countries,
            "collection_report": (data_package.metadata or {}).get("collection_report"),
            "fail_on_any_error": fail_on_any_error,
        })

        service.update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            result=result
        )

        # Update memory usage
        db_job = service.get_job(job_id)
        if db_job:
            db_job.peak_memory_mb = peak_memory
            db.commit()

        # Sync telemetry for the source this collection belonged to, when it
        # belonged to one: scheduled and manual runs both carry
        # data_source_id, and the health payload reads exactly these columns.
        # A success clears the failure streak, which is what ends the backoff.
        source_id = parameters.get("data_source_id")
        if source_id:
            from backend.services.scheduling import record_sync_success

            record_sync_success(
                db,
                int(source_id),
                started_at,
                rows=int(data_package.num_observations or 0),
            )

        logger.info(f"Data collection completed for job {job_id}")
        return result

    except Exception as e:
        logger.error(f"Data collection failed for job {job_id}: {e}\n{traceback.format_exc()}")
        user_friendly = translate_error(e, context="collecting data")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=error_details_to_json(user_friendly)
        )
        # The failure streak is the backoff: scheduling.next_due_at doubles
        # the interval per consecutive failure, so recording it here is what
        # keeps a down feed from being hammered at its healthy cadence.
        source_id = parameters.get("data_source_id")
        if source_id:
            from backend.services.scheduling import record_sync_failure

            record_sync_failure(db, int(source_id), str(e))
        raise
    finally:
        db.close()


@celery_app.task(base=JobTask, bind=True, name="run_training")
def run_training(self, job_id: int, parameters: dict):
    """
    Run model training job.

    **For non-technical users:** This trains the AI model on the collected data
    so it can predict liquidity risk.
    """
    db = SessionLocal()
    process = psutil.Process(os.getpid())
    start_memory = process.memory_info().rss / (1024 ** 2)

    try:
        service = JobService(db)
        service.update_job_status(job_id, status="running", progress=0.0)

        logger.info(f"Starting BNE ENGINE training for job {job_id}")

        # Training is driven directly by the trainer classes selected below
        # (MultiScaleTrainer / ModelTrainer). EngineOrchestrator is NOT
        # involved in this task -- it serves the synchronous pipeline route
        # (api/routes/pipeline.py). An earlier revision constructed one here
        # and never called it; the object did nothing but log a device line
        # and imply an architecture this task does not use.
        self.update_progress(job_id, 10.0)
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)

        raw_config = parameters.get('config', {'model': 'temporal_attention'})
        config = dict(raw_config) if isinstance(raw_config, dict) else {'model': 'temporal_attention'}
        if 'num_epochs' in config and 'epochs' not in config:
            config['epochs'] = config['num_epochs']
        # The old default here was "HGT", but MultiScaleTrainer never built a
        # graph model: it warned that HGT was "not fully integrated" and trained
        # MultiScaleTemporalAttentionModel, while the job result still reported
        # model_type="HGT". The default now names the model that is trained.
        config.setdefault('model', 'temporal_attention')

        # For training, we need existing data package
        # Check if user provided a data_job_id to use existing collected data
        data_job_id = parameters.get("data_job_id")

        from backend.models.job import Job

        if not data_job_id:
            # Try to find the most recent completed data collection job
            recent_data_job = db.query(Job).filter(
                Job.job_type == "data_collection",
                Job.status == "completed"
            ).order_by(Job.completed_at.desc()).first()

            if recent_data_job:
                data_job_id = recent_data_job.id
                logger.info(f"Using most recent data collection job: {data_job_id}")
            else:
                raise ValueError("No completed data collection job found. Run data collection first.")

        self.update_progress(job_id, 20.0)

        # Load the data package from the completed data job
        data_job_dir = f"/app/data/jobs/{data_job_id}"
        if not os.path.exists(f"{data_job_dir}/timeseries.parquet"):
            raise FileNotFoundError(f"Data package not found for job {data_job_id}. Run data collection first.")

        logger.info(f"Loading data package from job {data_job_id}")

        # Load data package (simplified - just load the files)
        import pandas as pd
        timeseries_df = pd.read_parquet(f"{data_job_dir}/timeseries.parquet")
        logger.info(f"Loaded {len(timeseries_df)} timeseries records")
        logger.info(f"Columns: {list(timeseries_df.columns)}")
        logger.info(f"Index: {timeseries_df.index.name}")

        # Reset index to get date column if it's in the index
        if timeseries_df.index.name == 'date' or 'date' in str(timeseries_df.index.name).lower():
            timeseries_df = timeseries_df.reset_index()

        self.update_progress(job_id, 40.0)

        # Get date range from parameters, or derive it from the payload's own
        # span. The previous defaults were hardcoded to 2023-01-01..2024-12-31:
        # with a five-year collection window they silently discarded everything
        # outside a fixed historical slice -- including the most recent
        # observations a monitoring product exists to score.
        from backend.modules.engine.trainer import (
            default_training_windows,
            split_train_val_by_date,
        )

        param_train_start = parameters.get("train_start")
        param_train_end = parameters.get("train_end")
        param_test_start = parameters.get("test_start")
        param_test_end = parameters.get("test_end")

        # Find date column (could be 'date', 'Date', 'timestamp', etc.)
        date_col = None
        for col in timeseries_df.columns:
            col_lower = str(col).lower()
            if 'date' in col_lower or 'time' in col_lower:
                date_col = col
                break

        if not date_col:
            logger.error(f"Available columns: {list(timeseries_df.columns)}")
            raise ValueError(f"No date column found in timeseries data. Available columns: {list(timeseries_df.columns)}")

        # Ensure date column is datetime
        timeseries_df[date_col] = pd.to_datetime(timeseries_df[date_col], errors='coerce')

        # Resolve the window boundaries: explicit parameters win; anything
        # missing is derived chronologically from the data actually collected.
        windows_derived_from_data = not all(
            [param_train_start, param_train_end, param_test_start, param_test_end]
        )
        data_min = timeseries_df[date_col].min()
        data_max = timeseries_df[date_col].max()
        if windows_derived_from_data:
            derived_start, derived_train_end, derived_end = default_training_windows(
                data_min, data_max, train_fraction=0.8
            )
        else:
            derived_start = derived_train_end = derived_end = None

        train_start = param_train_start or derived_start
        train_end = param_train_end or derived_train_end
        test_start = param_test_start or derived_train_end
        test_end = param_test_end or derived_end

        # Convert date strings to datetime for comparison
        train_start_dt = pd.to_datetime(train_start)
        train_end_dt = pd.to_datetime(train_end)
        test_start_dt = pd.to_datetime(test_start)
        test_end_dt = pd.to_datetime(test_end)

        # Mixed explicit/derived parameters must still produce a chronological,
        # non-overlapping split: training on rows the test window also contains
        # would evaluate the model on data it saw.
        if not (train_start_dt <= train_end_dt < test_end_dt):
            raise ValueError(
                f"Resolved training windows are not chronological: train "
                f"[{train_start_dt}, {train_end_dt}], test end {test_end_dt}"
            )
        if test_start_dt <= train_end_dt:
            if windows_derived_from_data:
                # Derived test side starts strictly after train_end.
                pass
            else:
                raise ValueError(
                    f"Explicit test window starts at {test_start_dt}, which is not "
                    f"after the training window end {train_end_dt}; the split "
                    "would evaluate on training data"
                )

        logger.info(
            "Training windows (%s): train [%s .. %s], test (%s .. %s]",
            "derived from payload" if windows_derived_from_data else "from parameters",
            train_start_dt.date(), train_end_dt.date(),
            ">" if windows_derived_from_data and not param_test_start else ">=",
            test_start_dt.date(),
        )

        # Split data into train/test. When the windows were derived, the test
        # side is strictly after train_end so the boundary day cannot appear in
        # both; explicit parameters keep their inclusive semantics.
        train_df = timeseries_df[
            (timeseries_df[date_col] >= train_start_dt) &
            (timeseries_df[date_col] <= train_end_dt)
        ]
        if windows_derived_from_data and not param_test_start:
            test_df = timeseries_df[
                (timeseries_df[date_col] > train_end_dt) &
                (timeseries_df[date_col] <= test_end_dt)
            ]
        else:
            test_df = timeseries_df[
                (timeseries_df[date_col] >= test_start_dt) &
                (timeseries_df[date_col] <= test_end_dt)
            ]

        logger.info(f"Train set: {len(train_df)} records, Test set: {len(test_df)} records")

        self.update_progress(job_id, 60.0)

        # Multi-scale training
        logger.info("Starting multi-scale model training...")

        # Check if we have source_code column (multi-source data)
        has_multi_source = 'source_code' in train_df.columns

        if has_multi_source:
            logger.info("Using MULTI-SCALE trainer for heterogeneous data sources")
            from backend.modules.engine.multi_scale_trainer import MultiScaleTrainer as TrainerClass
        else:
            logger.info("Using single-scale trainer")
            from backend.modules.engine.trainer import ModelTrainer as TrainerClass

        # Get model configuration
        model_type = config.get('model', 'temporal_attention').lower()
        logger.info(f"Training {model_type.upper()} model")

        # Create trainer
        import torch

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"Using device: {device}")

        trainer = TrainerClass(model_type=model_type, device=device, config=config)

        # Split validation from train chronologically by date (80/20 of the
        # training window's span). The previous positional iloc cut split the
        # source-major frame by SOURCE, not by time: the validation side held
        # sources the training side never saw, which the multi-scale dataset
        # then skipped, leaving validation empty and model selection frozen at
        # the epoch-0 checkpoint.
        train_subset, val_subset, val_cutoff = split_train_val_by_date(
            train_df, date_col, val_fraction=0.2
        )
        logger.info(
            "Chronological train/val split at %s: Train=%d rows, Val=%d rows",
            pd.to_datetime(val_cutoff).date(), len(train_subset), len(val_subset),
        )

        if has_multi_source:
            sources = train_df['source_code'].nunique()
            logger.info(f"Split: Train={len(train_subset)}, Val={len(val_subset)}, Test={len(test_df)}, Sources={sources}")

        # Train model. With ensemble_size >= 2 on the single-source path,
        # train M independently seeded members so the prediction engine can
        # decompose aleatoric vs epistemic variance (and refuse a prediction
        # whose epistemic term spikes). The multi-scale trainer does not
        # train independent members yet; a request it cannot honour is
        # recorded in the result rather than silently ignored.
        self.update_progress(job_id, 65.0)

        ensemble_size = max(1, int(config.get('ensemble_size', 1) or 1))
        ensemble_members: list = []
        ensemble_note = None
        if ensemble_size >= 2 and not has_multi_source:
            from backend.modules.engine.trainer import train_ensemble
            training_metrics, ensemble_members = train_ensemble(
                train_df=train_subset,
                val_df=val_subset,
                test_df=test_df,
                output_dir=output_dir,
                model_type=model_type,
                device=device,
                config=config,
            )
        else:
            if ensemble_size >= 2:
                ensemble_note = (
                    "ensemble_size was requested but the multi-scale trainer "
                    "does not train independent members yet; a single model "
                    "was trained and the uncertainty decomposition will "
                    "report itself not measurable"
                )
                logger.warning("%s (ensemble_size=%d)", ensemble_note, ensemble_size)
            training_metrics = trainer.train(
                train_df=train_subset,
                val_df=val_subset,
                test_df=test_df,
                output_dir=output_dir
            )

        self.update_progress(job_id, 95.0)

        # Generate visualizations
        logger.info("Generating visualizations...")
        from backend.modules.engine.visualizer import create_training_report

        try:
            viz_paths = create_training_report(output_dir, job_id)
            logger.info(f"Created {len(viz_paths)} visualizations")
        except Exception as e:
            logger.warning(f"Failed to create visualizations: {e}")
            viz_paths = {}

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        history_path = Path(output_dir) / "training_history.json"

        # Prepare results with training metrics
        data_job = service.get_job(data_job_id)

        # Walk-forward lift over simple baselines. Only the single-scale trainer
        # produces it today: the multi-scale model takes several heterogeneous
        # inputs, so the flat design matrix the backtest harness needs does not
        # describe it. Absent means "not measured", not "no lift".
        baseline_comparison = getattr(training_metrics, "baseline_comparison", None)

        result = {
            "status": "completed",
            "message": f"Model training completed successfully with {model_type.upper()}",
            "data_source_job": data_job_id,
            "model_type": model_type.upper(),
            "multi_scale": has_multi_source,
            "train_period": f"{train_start} to {train_end}",
            "test_period": f"{test_start} to {test_end}",
            "windows_derived_from_data": bool(windows_derived_from_data),
            "split_method": "chronological_by_date",
            "train_records": len(train_subset),
            "val_records": len(val_subset),
            "test_records": len(test_df),
            "total_records": len(timeseries_df),
            "features": list(timeseries_df.columns),
            "device": str(device),
            # Training metrics
            "epochs_trained": training_metrics.total_epochs,
            "best_epoch": training_metrics.best_epoch + 1,
            "final_train_loss": float(training_metrics.train_loss[-1]),
            "final_val_loss": float(training_metrics.val_loss[-1]),
            "best_val_loss": float(min(training_metrics.val_loss)),
            "test_loss": float(training_metrics.test_loss),
            "test_mae": float(training_metrics.test_mae),
            "test_rmse": float(training_metrics.test_rmse),
            "test_r2": float(training_metrics.test_r2),
            # Walk-forward lift over simple baselines: without it, the complexity
            # of a bespoke attention model is unjustified.
            "baseline_comparison": baseline_comparison,
            "model_path": training_metrics.model_path,
            "ensemble": {
                "size": len(ensemble_members) if ensemble_members else 1,
                "requested": ensemble_size,
                "members": ensemble_members,
                **({"note": ensemble_note} if ensemble_note else {}),
            },
            "predictions_path": training_metrics.predictions_path,
            "training_history_path": str(history_path),
            "train_loss_history": [float(value) for value in training_metrics.train_loss],
            "val_loss_history": [float(value) for value in training_metrics.val_loss],
            "visualizations": viz_paths,
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

        data_scope = data_job.result if (data_job and isinstance(data_job.result, dict)) else {}
        result["regions"] = data_scope.get("regions")
        result["countries"] = data_scope.get("countries")

        # Reproducibility manifest: bind the artefact to the code revision, the
        # resolved config, the DATA attestation and the data snapshot it was
        # trained on, and hash the weights so tampering is detectable.
        from backend.modules.engine.reproducibility import ModelManifest

        attestation_payload = data_scope.get("quality_attestation") or {}
        training_summary = {
            "epochs_trained": int(training_metrics.total_epochs),
            "best_epoch": int(training_metrics.best_epoch) + 1,
            "best_val_loss": float(min(training_metrics.val_loss)),
            "test_loss": float(training_metrics.test_loss),
            "test_mae": float(training_metrics.test_mae),
            "test_rmse": float(training_metrics.test_rmse),
            "test_r2": float(training_metrics.test_r2),
        }
        manifest = ModelManifest.capture(
            training_metrics.model_path,
            config,
            job_id=str(job_id),
            model_type=str(model_type).upper(),
            attestation_id=attestation_payload.get("attestation_id"),
            snapshot_id=data_scope.get("snapshot_id"),
            dataset_row_counts=attestation_payload.get("dataset_row_counts"),
            training_metrics=training_summary,
            backtest=baseline_comparison,
            extra={
                "data_source_job": str(data_job_id),
                "multi_scale": bool(has_multi_source),
                "train_records": int(len(train_subset)),
                "val_records": int(len(val_subset)),
                "test_records": int(len(test_df)),
            },
        )
        manifest_path = manifest.write()
        result["reproducibility_manifest"] = manifest_path
        result["reproducibility"] = manifest.to_dict()
        logger.info("[%s] Model provenance: %s", job_id, manifest.describe())

        # Add per-source metrics if available
        if hasattr(training_metrics, 'per_source_metrics'):
            result["per_source_metrics"] = training_metrics.per_source_metrics

        service.update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            result=result
        )

        # Update memory usage
        db_job = service.get_job(job_id)
        if db_job:
            db_job.peak_memory_mb = peak_memory
            db.commit()

        logger.info(f"Training completed for job {job_id}")
        return result

    except Exception as e:
        logger.error(f"Training failed for job {job_id}: {e}\n{traceback.format_exc()}")
        user_friendly = translate_error(e, context="training model")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=error_details_to_json(user_friendly)
        )
        raise
    finally:
        db.close()


@celery_app.task(base=JobTask, bind=True, name="run_prediction")
def run_prediction(self, job_id: int, parameters: dict):
    """
    Run prediction job.

    **For non-technical users:** This uses the trained model to predict
    liquidity risk for the next 7 days.
    """
    db = SessionLocal()

    try:
        service = JobService(db)
        service.update_job_status(job_id, status="running", progress=0.0)

        logger.info(f"Starting prediction for job {job_id}")

        # Load trained model and data
        from backend.modules.engine.prediction_engine import RealPredictionEngine
        import torch
        import os

        self.update_progress(job_id, 10.0)

        # Get model and data paths
        trained_model_job = parameters.get("trained_model_job")
        forecast_horizon = parameters.get("forecast_horizon", 7)

        if not trained_model_job:
            raise ValueError("trained_model_job parameter is required for prediction")

        # Get the trained model job - refresh from DB to avoid stale data
        from sqlalchemy import inspect
        trained_job = service.get_job(trained_model_job)
        if not trained_job or trained_job.status != "completed":
            raise ValueError(f"Trained model job {trained_model_job} not found or not completed")

        # Force refresh from database
        db.expire(trained_job)
        db.refresh(trained_job)

        logger.info(f"Trained job result type: {type(trained_job.result)}")
        logger.info(f"Trained job result: {trained_job.result}")

        # Extract paths from trained job result
        if isinstance(trained_job.result, dict):
            model_path = trained_job.result.get("model_path")
            data_source_job = trained_job.result.get("data_source_job")
        else:
            raise ValueError(f"Trained job {trained_model_job} has invalid result format: {type(trained_job.result)}")

        # Get the original data from the data collection job (not predictions)
        data_path = None
        data_scope = {}
        if data_source_job:
            data_job = service.get_job(data_source_job)
            if data_job and isinstance(data_job.result, dict):
                data_path = data_job.result.get("output_path")
                data_scope = data_job.result

        logger.info(f"Model path: {model_path}, Data path: {data_path}")

        if not model_path or not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")

        if not data_path or not os.path.exists(data_path):
            raise FileNotFoundError(f"Data file not found: {data_path}")

        self.update_progress(job_id, 20.0)

        # Initialize prediction engine
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        attestation = DataQualityGate.attestation_from_job_result(
            data_scope if isinstance(data_scope, dict) else {},
            job_id=str(data_source_job),
        )
        engine = RealPredictionEngine(
            model_path=model_path,
            device=device,
            config=parameters.get('config', {}),
            quality_attestation=attestation,
        )

        self.update_progress(job_id, 40.0)

        # Load and prepare data
        import pandas as pd
        data = pd.read_parquet(data_path)

        self.update_progress(job_id, 50.0)

        data_scope = {}
        if data_job and isinstance(data_job.result, dict):
            data_scope = data_job.result

        # Generate predictions. The attestation travels as an explicit argument,
        # so no pandas reshape between loading and inference can drop it.
        prediction_result = engine.predict(data, attestation=attestation)

        self.update_progress(job_id, 80.0)

        # Save predictions
        output_dir = parameters.get('output_dir', '/app/data/predictions')
        os.makedirs(output_dir, exist_ok=True)
        output_path = f"{output_dir}/predictions_{job_id}.parquet"

        prediction_result.predictions_df.to_parquet(output_path)

        # Persist to the risk-score hypertable: it existed since the
        # TimescaleDB migration with no writer anywhere (fifth-round finding).
        try:
            persisted = persist_risk_scores(
                db,
                job_id,
                prediction_result.predictions_df,
                model_version=str(trained_job.result.get('model_type', 'unknown')),
                horizon_days=int(forecast_horizon),
            )
            logger.info("Persisted %d risk-score row(s) for job %s", persisted, job_id)
        except Exception as persist_exc:  # noqa: BLE001 - storage outage must not void the prediction
            logger.warning("Risk-score persistence skipped for job %s: %s", job_id, persist_exc)

        # Convert NaN to None for JSON serialization
        import math
        def clean_nan(obj):
            if isinstance(obj, dict):
                return {k: clean_nan(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_nan(v) for v in obj]
            elif isinstance(obj, float) and math.isnan(obj):
                return None
            return obj

        result = {
            "status": "completed",
            "predictions_path": output_path,
            "num_predictions": len(prediction_result.predictions_df),
            "mean_risk": float(prediction_result.predictions_df['risk_score'].mean()) if 'risk_score' in prediction_result.predictions_df.columns else None,
            # Per-source confidence-method counts, so the explainability card
            # can report the interval state this job actually produced instead
            # of a blanket claim. Plain ints: numpy integers would not survive
            # JSON serialisation into jobs.result.
            "confidence_methods": (
                {
                    str(method): int(count)
                    for method, count in prediction_result.predictions_df["confidence_method"]
                    .value_counts()
                    .items()
                }
                if "confidence_method" in prediction_result.predictions_df.columns
                else {}
            ),
            # Aleatoric/epistemic decomposition state for this run (deep
            # ensemble when the checkpoint has members; single-model reports
            # the split not measurable). The explainability card derives its
            # uncertainty block from this and from confidence_methods.
            "uncertainty_decomposition": clean_nan(prediction_result.uncertainty_summary),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "feature_importances": clean_nan(prediction_result.feature_importances),
            "metrics": clean_nan(prediction_result.metrics),
            "regions": parameters.get("regions") or data_scope.get("regions"),
            "countries": parameters.get("countries") or data_scope.get("countries"),
            "data_source_job": data_source_job
        }

        service.update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            result=result
        )

        logger.info(f"Prediction completed for job {job_id}")
        return result

    except Exception as e:
        logger.error(f"Prediction failed for job {job_id}: {e}\n{traceback.format_exc()}")
        user_friendly = translate_error(e, context="generating predictions")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=error_details_to_json(user_friendly)
        )
        raise
    finally:
        db.close()


@celery_app.task(base=JobTask, bind=True, name="run_backtest")
def run_backtest(self, job_id: int, parameters: dict):
    """
    Run backtest job.

    **For non-technical users:** This tests the model's performance on
    historical data to see how accurate it would have been.
    """
    db = SessionLocal()
    process = psutil.Process(os.getpid())
    start_memory = process.memory_info().rss / (1024 ** 2)

    try:
        service = JobService(db)
        service.update_job_status(job_id, status="running", progress=0.0)

        logger.info(f"Starting backtest for job {job_id}")

        from backend.modules.engine.trainer import ModelTrainer
        from backend.modules.engine.prediction_engine import RealPredictionEngine
        import torch
        import numpy as np

        self.update_progress(job_id, 10.0)

        # Get parameters
        trained_model_job = parameters.get("trained_model_job")
        start_date = parameters.get("start_date")
        end_date = parameters.get("end_date")

        if not trained_model_job:
            raise ValueError("trained_model_job parameter is required for backtest")

        # Get the trained model job
        trained_job = service.get_job(trained_model_job)
        if not trained_job or trained_job.status != "completed":
            raise ValueError(f"Trained model job {trained_model_job} not found or not completed")

        # Extract paths
        if isinstance(trained_job.result, dict):
            model_path = trained_job.result.get("model_path")
            data_source_job = trained_job.result.get("data_source_job")
        else:
            raise ValueError(f"Trained job {trained_model_job} has invalid result format")

        # Get data from data collection job
        data_path = None
        data_scope = {}
        if data_source_job:
            data_job = service.get_job(data_source_job)
            if data_job and isinstance(data_job.result, dict):
                data_path = data_job.result.get("output_path")
                data_scope = data_job.result

        if not model_path or not data_path:
            raise ValueError("Could not retrieve model_path or data_path from trained job")

        self.update_progress(job_id, 20.0)

        # Load historical data
        import pandas as pd
        data = pd.read_parquet(data_path)

        if 'date' in data.columns and start_date and end_date:
            data['date'] = pd.to_datetime(data['date'])
            test_data = data[(data['date'] >= start_date) & (data['date'] <= end_date)]
            train_data = data[data['date'] < start_date]
        else:
            # If no date column or params, use last 20% as test
            split_idx = int(len(data) * 0.8)
            train_data = data[:split_idx]
            test_data = data[split_idx:]

        logger.info(f"Backtest: {len(train_data)} train samples, {len(test_data)} test samples")

        self.update_progress(job_id, 40.0)

        # Initialize prediction engine with trained model
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        attestation = DataQualityGate.attestation_from_job_result(
            data_scope if isinstance(data_scope, dict) else {},
            job_id=str(data_source_job),
        )
        engine = RealPredictionEngine(
            model_path=model_path,
            device=device,
            config=parameters.get('config', {}),
            quality_attestation=attestation,
        )

        self.update_progress(job_id, 60.0)

        # Roll the window across the test rows so the metrics describe the same
        # observations as the target, with a seam between sources that no metric is
        # allowed to difference across. `predict()` is deliberately not called here:
        # it collapses each source to one score (and pays for explainability), so it
        # is only used as a fallback when no series can be built.
        from backend.modules.engine.backtesting import (
            WalkForwardConfig,
            align_series_targets,
            boundaries_from_group_sizes,
            compute_metrics,
            directional_accuracy as _directional_accuracy,
            walk_forward_folds_per_segment,
        )

        risk_series_params = parameters.get("risk_series")
        if not isinstance(risk_series_params, dict):
            risk_series_params = {}

        risk_series = None
        risk_series_error = None
        try:
            risk_series = engine.predict_risk_series(
                test_data,
                attestation=attestation,
                max_steps=risk_series_params.get("max_steps", 2000),
                batch_size=risk_series_params.get("batch_size", 256),
            )
        except Exception as series_exc:  # noqa: BLE001 - degrade to an explicit skip
            risk_series_error = f"{type(series_exc).__name__}: {series_exc}"
            logger.warning(
                "Per-timestep risk series unavailable for job %s: %s", job_id, risk_series_error
            )

        pred_values = None
        boundaries: list = []
        # Alignment state: a score at window-end row t predicts row t+1, so
        # ground truth joins on the frame's `predicted_row_offset`, never on
        # `row_offset` (which would score every prediction one step early).
        aligned_actuals = None
        aligned_preds = None
        aligned_boundaries = None
        actuals_full = None
        # Only a genuine per-timestep series may feed the return-based metrics. The
        # per-source fallback below is a vector of unrelated entities and must never
        # be differenced as if it were a time series.
        series_usable = False
        prediction_result = None

        def _fold_actuals(full: "np.ndarray | None", test_idx: np.ndarray):
            """Per-fold targets: only folds whose rows are ALL aligned carry actuals.

            ``actuals_full`` is NaN where a row has no target at its predicted
            position (each source's final window, or no target column at all).
            A fold containing any NaN would poison every aggregate, so such a
            fold reports prediction-only metrics instead of partial ones.
            """
            if full is None:
                return None
            subset = full[test_idx]
            if subset.size == 0 or not bool(np.isfinite(subset).all()):
                return None
            return subset

        def _extract_risk_scores() -> np.ndarray:
            """Pull the engine's per-source risk scores out of the result frame."""
            nonlocal prediction_result
            if prediction_result is None:
                prediction_result = engine.predict(test_data, attestation=attestation)
            frame = prediction_result.predictions_df
            if 'risk_score' in frame.columns:
                column = frame['risk_score']
            elif 'prediction' in frame.columns:
                column = frame['prediction']
            else:
                column = frame.iloc[:, -1]
            return np.asarray(column.values, dtype=float)

        if risk_series is not None and risk_series.n_steps > 1:
            frame = risk_series.frame
            pred_values = np.asarray(frame["risk_score"], dtype=float)
            boundaries = list(risk_series.boundaries)
            series_usable = True
            backtest_metrics = {
                "risk_series": risk_series.to_dict(),
                "prediction_count": int(pred_values.size),
            }

            target_col = (
                'actual_risk' if 'actual_risk' in test_data.columns
                else 'target' if 'target' in test_data.columns
                else None
            )
            if target_col is not None:
                target_series = np.asarray(test_data[target_col].values, dtype=float)
                predicted_offsets = np.asarray(frame["predicted_row_offset"], dtype=int)
                mask, aligned_actuals, aligned_preds = align_series_targets(
                    predicted_offsets, target_series, pred_values
                )
                if mask.any():
                    # The aligned subset drops rows (each source's final window
                    # has no predicted row in range), so the seam boundaries
                    # are rebuilt from the aligned per-source counts rather
                    # than reused from the full-length series.
                    source_labels = frame["source"].to_numpy()
                    valid_counts = [
                        int(((source_labels == name) & mask).sum())
                        for name in risk_series.sources
                    ]
                    aligned_boundaries = list(boundaries_from_group_sizes(valid_counts))
                    actuals_full = np.full(pred_values.size, np.nan)
                    actuals_full[mask] = aligned_actuals
                else:
                    aligned_actuals = None
                    aligned_preds = None
                    backtest_metrics["target_alignment"] = (
                        "skipped: no risk-series row has a finite in-range target "
                        "at the row it predicts (predicted_row_offset)"
                    )
                    logger.warning(
                        "Backtest target alignment skipped for job %s: no predicted "
                        "row position resolves to a finite target",
                        job_id,
                    )

            if aligned_actuals is not None and aligned_actuals.size > 0:
                mse = float(np.mean((aligned_actuals - aligned_preds) ** 2))
                mae = float(np.mean(np.abs(aligned_actuals - aligned_preds)))
                ss_res = float(np.sum((aligned_actuals - aligned_preds) ** 2))
                ss_tot = float(np.sum((aligned_actuals - np.mean(aligned_actuals)) ** 2))
                backtest_metrics.update({
                    "mse": mse,
                    "mae": mae,
                    "rmse": float(np.sqrt(mse)),
                    "r2": float(1 - (ss_res / (ss_tot + 1e-8))),
                    "n_aligned": int(aligned_actuals.size),
                    "target_alignment": (
                        "predicted_row_offset: the score for the window ending at "
                        "row t is paired with the target at row t+1 of the same source"
                    ),
                    # Awareness of source seams is part of the metric, not a caveat.
                    "directional_accuracy": _directional_accuracy(
                        aligned_actuals, aligned_preds, aligned_boundaries
                    ),
                })
            elif target_col is None:
                backtest_metrics.update({
                    "mean_prediction": float(np.mean(pred_values)),
                    "std_prediction": float(np.std(pred_values)),
                    "min_prediction": float(np.min(pred_values)),
                    "max_prediction": float(np.max(pred_values)),
                    "note": "No ground truth column in the test window",
                })
        else:
            # No usable series: fall back to the per-source scores so the job still
            # reports prediction statistics, and say plainly that nothing was scored.
            pred_values = _extract_risk_scores()
            backtest_metrics = {
                "prediction_count": int(pred_values.size),
                "mean_prediction": float(np.mean(pred_values)) if pred_values.size else None,
                "std_prediction": float(np.std(pred_values)) if pred_values.size else None,
                "min_prediction": float(np.min(pred_values)) if pred_values.size else None,
                "max_prediction": float(np.max(pred_values)) if pred_values.size else None,
                "risk_series_skipped": (
                    risk_series_error
                    or "the risk series has no more than one aligned timestep"
                ),
            }
            logger.info(
                "Per-timestep risk series skipped for job %s: %s",
                job_id,
                backtest_metrics["risk_series_skipped"],
            )

        # Evaluation extension: directional agreement between the risk series and
        # any available ground truth, plus walk-forward fold diagnostics.
        #
        # The series is ordered in time and source-major, so `boundaries` marks
        # the seam between sources and no metric differences across it.
        wf_raw = parameters.get("walk_forward")
        if not isinstance(wf_raw, dict):
            wf_raw = {}
        try:
            wf_config = WalkForwardConfig(
                n_splits=int(wf_raw.get("n_splits", 5)),
                test_size=wf_raw.get("test_size", 0.2),
                expanding=bool(wf_raw.get("expanding", True)),
                gap=int(wf_raw.get("gap", 0)),
                min_train_size=int(wf_raw.get("min_train_size", 1)),
            )
        except (TypeError, ValueError) as config_exc:
            logger.warning(f"Invalid walk_forward parameters for job {job_id}, using defaults: {config_exc}")
            wf_config = WalkForwardConfig()

        # Only metrics that are meaningful for a risk state. Sharpe, Sortino,
        # max drawdown, Calmar, volatility and VaR/CVaR were deleted: they
        # characterise the return of a priced asset, and a risk score is a latent
        # state, not a price. The "return" series they consumed was manufactured
        # by sign-flipping that state, so the statistics described an artefact.
        quant_keys = (
            "directional_accuracy",
            "hit_rate",
            "mse",
            "mae",
            "rmse",
            "r2",
        )

        # A series is scoreable when it is ordered in time and has more than one
        # point. A ground-truth target is optional: without it the error metrics
        # are undefined and only the direction-free diagnostics are reported.
        if series_usable:
            if aligned_actuals is not None:
                # Error metrics are computed on the aligned subset with its own
                # rebuilt seams; the full-length series stays available for the
                # fold diagnostics below.
                quant_metrics = compute_metrics(
                    actual=aligned_actuals,
                    predicted=aligned_preds,
                    boundaries=aligned_boundaries or None,
                )
            else:
                quant_metrics = compute_metrics(
                    actual=None, predicted=pred_values, boundaries=boundaries or None
                )
            for quant_key in quant_keys:
                if quant_key in quant_metrics:
                    backtest_metrics[quant_key] = quant_metrics[quant_key]

            # Folds are generated inside each source's own contiguous span: folding
            # across a concatenation of sources would train on one entity and test
            # on another.
            walk_forward = {
                "config": wf_config.to_dict(),
                "folds": [],
                "aggregation": "per_source",
            }
            source_names = risk_series.sources if risk_series is not None else []
            entries, failures = walk_forward_folds_per_segment(
                boundaries or None, int(pred_values.size), wf_config
            )
            for segment_index, _segment, folds in entries:
                source_name = (
                    source_names[segment_index]
                    if segment_index < len(source_names)
                    else str(segment_index)
                )
                for fold_index, (train_idx, test_idx) in enumerate(folds):
                    walk_forward["folds"].append({
                        "source": source_name,
                        "fold": fold_index,
                        "train_start": int(train_idx[0]),
                        "train_end": int(train_idx[-1]) + 1,
                        "test_start": int(test_idx[0]),
                        "test_end": int(test_idx[-1]) + 1,
                        "n_train": int(train_idx.size),
                        "n_test": int(test_idx.size),
                        "metrics": compute_metrics(
                            actual=_fold_actuals(actuals_full, test_idx),
                            predicted=pred_values[test_idx],
                        ),
                    })
            if failures:
                walk_forward["skipped_sources"] = {
                    source_names[index] if index < len(source_names) else str(index): reason
                    for index, reason in failures.items()
                }
            if not walk_forward["folds"]:
                walk_forward["skipped"] = "no source had enough timesteps for the fold configuration"
            backtest_metrics["walk_forward"] = walk_forward
        else:
            skip_reason = risk_series_error or (
                "the per-timestep risk series has no more than one aligned point"
                if risk_series is not None
                else "the per-timestep risk series could not be built"
            )
            quant_metrics = {quant_key: None for quant_key in quant_keys}
            backtest_metrics["quant_metrics_skipped"] = skip_reason
            backtest_metrics["walk_forward"] = {
                "config": wf_config.to_dict(),
                "folds": [],
                "skipped": skip_reason,
            }
            logger.info("Return-based backtest metrics skipped for job %s: %s", job_id, skip_reason)

        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Convert NaN to None for JSON serialization
        import math
        def clean_nan(obj):
            if isinstance(obj, dict):
                return {k: clean_nan(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_nan(v) for v in obj]
            elif isinstance(obj, float) and math.isnan(obj):
                return None
            return obj

        # Event-based validation (fifth-round wiring): when the job declares
        # an EventDefinition, label stress episodes on each source's indicator
        # series over the declared test window and score the risk series
        # against them -- ROC AUC, average precision and conservative
        # earliest-alarm lead time. Labels use future observations by
        # construction (that is what a label is); they never touch features.
        event_definition_raw = parameters.get("event_definition")
        if series_usable and isinstance(event_definition_raw, dict):
            from backend.modules.data.event_labeller import EventDefinition, label_events
            from backend.modules.engine.event_metrics import (
                average_precision,
                lead_time_stats,
                roc_auc,
            )

            try:
                definition = EventDefinition(**event_definition_raw)
            except TypeError as def_exc:
                raise ValueError(f"invalid event_definition: {def_exc}") from def_exc

            value_col = 'Close' if 'Close' in test_data.columns else 'Value'
            frame = risk_series.frame if risk_series is not None else None
            event_metrics_payload = {"definition": definition.to_dict(), "by_source": {}}
            for source_name in (risk_series.sources if risk_series is not None else []):
                block = frame[frame["source"] == source_name]
                source_rows = test_data[test_data['source_code'] == source_name].sort_values('Date')
                series_values = pd.to_numeric(source_rows[value_col], errors='coerce').to_numpy(dtype=float)
                if series_values.size < definition.horizon + definition.min_duration:
                    event_metrics_payload["by_source"][source_name] = {"skipped": "series_too_short"}
                    continue
                from dataclasses import replace as _dc_replace

                from backend.modules.data.semantics import event_direction

                resolved_direction = definition.direction or event_direction(source_name)
                if resolved_direction is None:
                    event_metrics_payload["by_source"][source_name] = {
                        "skipped": "no declared or registered stress direction for this series"
                    }
                    continue

                # Alignment: scores join the series through row_offset -- the
                # documented RiskSeriesResult contract. The previous naive
                # truncation (events[:len(scores)]) shifted every label by the
                # sequence warm-up (~30 business days), which is larger than
                # the lead times being measured: a 20-day warning read as
                # simultaneous, a simultaneous alarm read as a lead.
                offsets = np.asarray(block["row_offset"], dtype=int)
                scores_raw = np.asarray(block["risk_score"], dtype=float)
                keep = (offsets >= 0) & (offsets < series_values.size) & np.isfinite(scores_raw)
                offsets = offsets[keep]
                if offsets.size == 0:
                    event_metrics_payload["by_source"][source_name] = {"skipped": "no_aligned_scores"}
                    continue
                # Direction: for a direction=-1 series stress lives in FALLING
                # values, so scoring the high tail of the raw score against
                # falling-value labels measures the opposite of a warning.
                # Sign-adjust so higher always means more stress; the alarm
                # quantile is then taken on the adjusted scores.
                sign = 1.0 if resolved_direction == "up" else -1.0
                scores_block = scores_raw[keep] * sign

                source_definition = _dc_replace(definition, direction=resolved_direction)
                labelling = label_events(series_values, source_definition)
                events_aligned = labelling.events[offsets]
                if events_aligned.size == 0 or not events_aligned.any():
                    event_metrics_payload["by_source"][source_name] = {"skipped": "no_events_in_window"}
                    continue
                alarms = scores_block >= np.quantile(scores_block, definition.quantile)
                event_metrics_payload["by_source"][source_name] = {
                    "n_events": int(labelling.n_events),
                    "roc_auc": roc_auc(events_aligned, scores_block),
                    "average_precision": average_precision(events_aligned, scores_block),
                    "lead_time": lead_time_stats(
                        events_aligned, alarms, max_lead=2 * definition.horizon
                    ),
                }
            backtest_metrics["event_metrics"] = event_metrics_payload
        elif isinstance(event_definition_raw, dict):
            backtest_metrics["event_metrics"] = {
                "skipped": "no usable per-timestep risk series to score against the labelled events"
            }

        # Volatility track (the census's `garch` disposition, wired): GARCH(1,1)
        # priced against unconditional variance per source, on each source's own
        # contiguous span -- returns never difference across a source seam. This
        # track prices VOLATILITY, not levels: it consumes none of the quant or
        # event metrics above and feeds none of them. Skips are per-source and
        # declared, as everywhere else.
        if 'source_code' in test_data.columns:
            from backend.modules.engine.backtesting import compare_volatility_baselines

            volatility_value_col = 'Close' if 'Close' in test_data.columns else 'Value'
            volatility_payload = {}
            for volatility_source in test_data['source_code'].unique():
                volatility_rows = test_data[
                    test_data['source_code'] == volatility_source
                ].sort_values('Date')
                volatility_values = pd.to_numeric(
                    volatility_rows[volatility_value_col], errors='coerce'
                ).to_numpy(dtype=float)
                try:
                    volatility_payload[str(volatility_source)] = compare_volatility_baselines(
                        volatility_values
                    )
                except Exception as vol_exc:  # noqa: BLE001 - a per-source failure is recorded, it does not void the backtest
                    volatility_payload[str(volatility_source)] = {
                        "failed": f"{type(vol_exc).__name__}: {vol_exc}"
                    }
            backtest_metrics["volatility_baselines"] = {"by_source": volatility_payload}

        # Persist scalar metrics to the metrics hypertable (fifth-round wiring).
        try:
            persisted = persist_model_metrics(
                db,
                job_id,
                backtest_metrics,
                model_version=str(trained_job.result.get('model_type', 'unknown')),
            )
            logger.info("Persisted %d metric row(s) for backtest job %s", persisted, job_id)
        except Exception as persist_exc:  # noqa: BLE001 - storage outage must not void the backtest
            logger.warning("Metric persistence skipped for job %s: %s", job_id, persist_exc)

        # Persist the aligned series when an output directory is configured, so a
        # risk curve can be inspected without re-running the backtest.
        risk_series_path = None
        series_output_dir = parameters.get('output_dir')
        if risk_series is not None and series_output_dir:
            try:
                os.makedirs(series_output_dir, exist_ok=True)
                candidate = f"{series_output_dir}/risk_series_{job_id}.csv"
                risk_series.frame.to_csv(candidate, index=False)
                risk_series_path = candidate
            except Exception as write_exc:  # noqa: BLE001 - the metrics matter more than the file
                logger.warning(
                    "Could not persist the risk series for job %s: %s", job_id, write_exc
                )

        # Prepare results summary
        result = {
            "status": "completed",
            "train_samples": len(train_data),
            "test_samples": len(test_data),
            "backtest_metrics": clean_nan(backtest_metrics),
            "quant_metrics": clean_nan(quant_metrics),
            "walk_forward": clean_nan(walk_forward),
            "risk_series": (
                None if risk_series is None else clean_nan(risk_series.to_dict())
            ),
            "risk_series_path": risk_series_path,
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

        service.update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            result=result
        )

        # Update memory usage
        db_job = service.get_job(job_id)
        if db_job:
            db_job.peak_memory_mb = peak_memory
            db.commit()

        logger.info(f"Backtest completed for job {job_id}")
        return result

    except Exception as e:
        logger.error(f"Backtest failed for job {job_id}: {e}\n{traceback.format_exc()}")
        user_friendly = translate_error(e, context="running backtest")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=error_details_to_json(user_friendly)
        )
        raise
    finally:
        db.close()
