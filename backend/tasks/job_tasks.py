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

        logger.info(
            "Running data collection with %d catalogue items (regions=%s, countries=%s)...",
            len(catalogue_items),
            selected_regions or "all",
            selected_countries or "all",
        )

        # Run the complete data pipeline
        data_package = orchestrator.run(
            catalogue_items=catalogue_items,
            start_date=start_date,
            end_date=end_date,
            user_id="system",
            countries=selected_countries or None,
            regions=selected_regions or None,
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

        # Import BNE engine system
        from backend.modules.engine.orchestrator import EngineOrchestrator
        from backend.modules.data.orchestrator import DataPackage

        logger.info(f"Starting BNE ENGINE training for job {job_id}")

        # Initialize engine orchestrator
        self.update_progress(job_id, 10.0)
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)

        raw_config = parameters.get('config', {'model': 'HGT'})
        config = dict(raw_config) if isinstance(raw_config, dict) else {'model': 'HGT'}
        if 'num_epochs' in config and 'epochs' not in config:
            config['epochs'] = config['num_epochs']
        config.setdefault('model', 'HGT')
        orchestrator = EngineOrchestrator(f"job_{job_id}", output_dir, config)

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

        # Get date range from parameters or use defaults
        train_start = parameters.get("train_start", "2023-01-01")
        train_end = parameters.get("train_end", "2024-06-30")
        test_start = parameters.get("test_start", "2024-07-01")
        test_end = parameters.get("test_end", "2024-12-31")

        # Convert date strings to datetime for comparison
        train_start_dt = pd.to_datetime(train_start)
        train_end_dt = pd.to_datetime(train_end)
        test_start_dt = pd.to_datetime(test_start)
        test_end_dt = pd.to_datetime(test_end)

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
        timeseries_df[date_col] = pd.to_datetime(timeseries_df[date_col])

        # Split data into train/test
        train_df = timeseries_df[
            (timeseries_df[date_col] >= train_start_dt) &
            (timeseries_df[date_col] <= train_end_dt)
        ]
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

        # Split validation from train (80/20)
        train_size = int(len(train_df) * 0.8)
        train_subset = train_df.iloc[:train_size]
        val_subset = train_df.iloc[train_size:]

        if has_multi_source:
            sources = train_df['source_code'].nunique()
            logger.info(f"Split: Train={len(train_subset)}, Val={len(val_subset)}, Test={len(test_df)}, Sources={sources}")

        # Train model
        self.update_progress(job_id, 65.0)

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

        # Generate predictions on test set, with the source attestation passed
        # explicitly rather than assumed from the frame.
        prediction_result = engine.predict(test_data, attestation=attestation)

        actuals = None
        pred_values = None

        def _extract_risk_scores() -> np.ndarray:
            """Pull the engine's per-source risk scores out of the result frame."""
            frame = prediction_result.predictions_df
            if 'risk_score' in frame.columns:
                column = frame['risk_score']
            elif 'prediction' in frame.columns:
                column = frame['prediction']
            else:
                column = frame.iloc[:, -1]
            return np.asarray(column.values, dtype=float)

        # Calculate backtest metrics. The engine emits one risk score per data
        # source while a target column is per-row, so the two series only describe
        # the same observations when their lengths agree. A mismatch is reported as
        # a skip instead of being truncated into confident-looking numbers.
        if 'actual_risk' in test_data.columns or 'target' in test_data.columns:
            target_col = 'actual_risk' if 'actual_risk' in test_data.columns else 'target'
            actuals = np.asarray(test_data[target_col].values, dtype=float)
            pred_values = _extract_risk_scores()

            if pred_values.size == actuals.size and pred_values.size > 0:
                mse = float(np.mean((actuals - pred_values) ** 2))
                mae = float(np.mean(np.abs(actuals - pred_values)))
                rmse = float(np.sqrt(mse))
                ss_res = float(np.sum((actuals - pred_values) ** 2))
                ss_tot = float(np.sum((actuals - np.mean(actuals)) ** 2))
                r2 = float(1 - (ss_res / (ss_tot + 1e-8)))

                if actuals.size > 1:
                    directional_accuracy = float(
                        np.mean((np.diff(actuals) > 0) == (np.diff(pred_values) > 0))
                    )
                else:
                    directional_accuracy = 0.0

                backtest_metrics = {
                    "mse": mse,
                    "mae": mae,
                    "rmse": rmse,
                    "r2": r2,
                    "directional_accuracy": directional_accuracy,
                }
            else:
                backtest_metrics = {
                    "prediction_count": int(pred_values.size),
                    "target_count": int(actuals.size),
                    "note": (
                        "skipped: the engine returned "
                        f"{pred_values.size} per-source risk scores for "
                        f"{actuals.size} labelled test rows, so the series are not aligned"
                    ),
                }
                # The comparison is unusable for this job; drop the target series so
                # the return-based block below also reports a skip instead of
                # differencing unrelated values.
                actuals = None
                logger.warning(
                    "Backtest metrics skipped for job %s: %s",
                    job_id,
                    backtest_metrics["note"],
                )
        else:
            # No ground truth - compute prediction statistics
            pred_values = _extract_risk_scores()

            backtest_metrics = {
                "mean_prediction": float(np.mean(pred_values)) if pred_values.size else None,
                "std_prediction": float(np.std(pred_values)) if pred_values.size else None,
                "min_prediction": float(np.min(pred_values)) if pred_values.size else None,
                "max_prediction": float(np.max(pred_values)) if pred_values.size else None,
                "note": "No ground truth available"
            }

        # Quantitative extension: risk-signal returns, tail-risk statistics, and
        # walk-forward fold diagnostics. Purely additive to backtest_metrics.
        #
        # These metrics are return- and transition-based, so they require a series
        # ordered in time. They are reported only when the engine's risk scores are
        # genuinely aligned with the target rows; otherwise a concatenation of
        # per-source scores would invent transitions between unrelated entities --
        # the same class of artefact the boundary-aware aggregation in
        # `backtesting` exists to remove.
        from backend.modules.engine.backtesting import (
            WalkForwardConfig,
            compute_metrics,
            generate_walk_forward_folds,
        )

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

        quant_keys = (
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "calmar_ratio",
            "annualized_volatility",
            "hit_rate",
            "var_95",
            "cvar_95",
        )

        aligned_series = (
            actuals is not None
            and pred_values is not None
            and np.asarray(pred_values).size == np.asarray(actuals).size
            and np.asarray(pred_values).size > 1
        )

        if aligned_series:
            quant_metrics = compute_metrics(actual=actuals, predicted=pred_values)
            for quant_key in quant_keys:
                backtest_metrics[quant_key] = quant_metrics[quant_key]

            walk_forward = {"config": {}, "folds": []}
            try:
                walk_forward["config"] = wf_config.to_dict()
                folds = generate_walk_forward_folds(len(pred_values), wf_config)
                for fold_index, (train_idx, test_idx) in enumerate(folds):
                    walk_forward["folds"].append({
                        "fold": fold_index,
                        "train_start": int(train_idx[0]),
                        "train_end": int(train_idx[-1]) + 1,
                        "test_start": int(test_idx[0]),
                        "test_end": int(test_idx[-1]) + 1,
                        "n_train": int(len(train_idx)),
                        "n_test": int(len(test_idx)),
                        "metrics": compute_metrics(
                            actual=actuals[test_idx],
                            predicted=pred_values[test_idx],
                        ),
                    })
            except (TypeError, ValueError) as wf_exc:
                walk_forward["error"] = str(wf_exc)
                logger.warning(f"Walk-forward folds skipped for job {job_id}: {wf_exc}")
            backtest_metrics["walk_forward"] = walk_forward
        else:
            if actuals is None:
                skip_reason = (
                    "the test window carries no ground-truth target column, so the "
                    "risk signal cannot be scored against realised outcomes"
                )
            else:
                skip_reason = (
                    f"the engine returned {np.asarray(pred_values).size} per-source risk "
                    f"scores for {np.asarray(actuals).size} test rows, so the two series "
                    "are not a time series of the same observations"
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

        # Prepare results summary
        result = {
            "status": "completed",
            "train_samples": len(train_data),
            "test_samples": len(test_data),
            "backtest_metrics": clean_nan(backtest_metrics),
            "quant_metrics": clean_nan(quant_metrics),
            "walk_forward": clean_nan(walk_forward),
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
