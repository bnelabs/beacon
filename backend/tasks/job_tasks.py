"""Celery tasks for background jobs."""

from celery import Task
import traceback
import logging
from datetime import datetime
import psutil
import os
import torch

from .celery_app import celery_app
from database import SessionLocal
from services.job_service import JobService
from services.enhanced_error_translator import translate_error_enhanced as translate_error
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

@celery_app.task(base=JobTask, bind=True, name="run_explanation")
def run_explanation(self, job_id: int, parameters: dict):
    """Run SHAP explanation for a specific prediction."""
    db = SessionLocal()
    try:
        service = JobService(db)
        service.update_job_status(job_id, status="running", progress=0.0)

        model_version_id = parameters.get("model_version_id")
        prediction_id = parameters.get("prediction_id")

        from models.model import ModelVersion
        import torch
        import shap
        import pandas as pd

        # 1. Load model
        model_version = db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not model_version:
            raise ValueError(f"Model version {model_version_id} not found.")

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model = torch.load(model_version.model_path, map_location=device)
        model.eval()

        # 2. Load data
        data_job_id = model_version.job.id
        data_job_dir = f"/app/data/jobs/{data_job_id}"
        timeseries_df = pd.read_parquet(f"{data_job_dir}/timeseries.parquet")

        # 3. Get the specific prediction instance
        # This is a placeholder, as the prediction data format is not finalized
        background_data = timeseries_df.sample(100)  # Background for SHAP
        instance_to_explain = timeseries_df.iloc[[prediction_id]]

        # 4. Create explainer and generate SHAP values
        explainer = shap.KernelExplainer(model.predict, background_data)
        shap_values = explainer.shap_values(instance_to_explain)

        # 5. Save SHAP values
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)
        shap_values_path = f"{output_dir}/shap_values.json"
        with open(shap_values_path, "w") as f:
            json.dump(shap_values.tolist(), f)

        result = {
            "status": "completed",
            "shap_values_path": shap_values_path,
        }

        service.update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            result=result
        )

        return result

    except Exception as e:
        logger.error(f"Explanation failed for job {job_id}: {e}")
        user_friendly = translate_error(e, context="generating explanation")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=error_details_to_json(user_friendly)
        )
        raise
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
        from modules.data.orchestrator import DataOrchestrator

        logger.info(f"Starting data collection for job {job_id}")

        # Initialize data orchestrator
        self.update_progress(job_id, 10.0)
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Create progress callback to map orchestrator progress (0-100%) to job progress (20-95%)
        def orchestrator_progress_callback(orchestrator_progress: float, message: str):
            job_progress = 20.0 + (orchestrator_progress * 0.75)  # Maps 0-100 to 20-95
            self.update_progress(job_id, job_progress, current_step=message)

        orchestrator = DataOrchestrator(db, f"job_{job_id}", output_dir, progress_callback=orchestrator_progress_callback)

        # Run data collection - progress will be reported via callback (20%-95%)
        # No need for manual update_progress call here

        # Get catalogue items from parameters
        catalogue_items = parameters.get('catalogue_items')
        if not catalogue_items:
            # No items specified - fetch items marked as default_selected from database
            from models.data_catalogue import DataCatalogueItem
            default_items = db.query(DataCatalogueItem).filter(
                DataCatalogueItem.default_selected == True,
                DataCatalogueItem.enabled == True
            ).all()
            catalogue_items = [item.id for item in default_items]
            logger.info(f"No items specified, using {len(catalogue_items)} default catalogue items")

        start_date = parameters.get('start_date', '2024-01-01')
        end_date = parameters.get('end_date', '2024-12-31')

        logger.info(f"Running data collection with {len(catalogue_items)} catalogue items...")

        # Run the complete data pipeline
        data_package = orchestrator.run(
            catalogue_items=catalogue_items,
            start_date=start_date,
            end_date=end_date,
            user_id="system"
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
            "output_path": data_package.timeseries_path,
            "completed_at": datetime.utcnow().isoformat()
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
        from modules.engine.orchestrator import EngineOrchestrator
        from modules.data.orchestrator import DataPackage

        logger.info(f"Starting BNE ENGINE training for job {job_id}")

        # Initialize engine orchestrator
        self.update_progress(job_id, 10.0)
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)

        from services.configuration_service import ConfigurationService
        config_service = ConfigurationService(db)
        config = config_service.get_active_configuration()
        if not config:
            raise ValueError("No active configuration found in the database.")

        # Link job to configuration
        from models.configuration import JobConfiguration
        job_config = JobConfiguration(job_id=job_id, configuration_id=config.id)
        db.add(job_config)
        db.commit()

        orchestrator = EngineOrchestrator(f"job_{job_id}", output_dir, config.config_data)

        # For training, we need existing data package
        # Check if user provided a data_job_id to use existing collected data
        data_job_id = parameters.get("data_job_id")

        if not data_job_id:
            raise ValueError("A data_job_id must be provided to run a training job.")

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

        from models.experiment import Experiment, Run
        experiment_name = parameters.get("experiment_name", "Default Experiment")
        experiment = db.query(Experiment).filter(Experiment.name == experiment_name).first()
        if not experiment:
            experiment = Experiment(name=experiment_name, description="Default experiment")
            db.add(experiment)
            db.commit()
            db.refresh(experiment)

        run = Run(
            experiment_id=experiment.id,
            job_id=job_id,
            configuration_id=config.id,
            parameters=parameters,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # REAL MODEL TRAINING WITH MULTI-SCALE SUPPORT
        logger.info("Starting REAL multi-scale model training...")

        # Check if we have source_code column (multi-source data)
        has_multi_source = 'source_code' in train_df.columns

        if has_multi_source:
            logger.info("Using MULTI-SCALE trainer for heterogeneous data sources")
            from modules.engine.multi_scale_trainer import MultiScaleTrainer as TrainerClass
        else:
            logger.info("Using single-scale trainer")
            from modules.engine.trainer import ModelTrainer as TrainerClass

        # Get model configuration
        model_type = config.config_data.get('model', 'temporal_attention').lower()
        logger.info(f"Training {model_type.upper()} model")

        # Create trainer
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"Using device: {device}")

        def training_callback(metrics):
            run.metrics = metrics
            db.commit()

        trainer = TrainerClass(model_type=model_type, device=device, config=config.config_data, training_callback=training_callback)

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

        run.status = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()

        self.update_progress(job_id, 95.0)

        # Generate visualizations
        logger.info("Generating visualizations...")
        from modules.engine.visualizer import create_training_report

        try:
            viz_paths = create_training_report(output_dir, job_id)
            logger.info(f"Created {len(viz_paths)} visualizations")
        except Exception as e:
            logger.warning(f"Failed to create visualizations: {e}")
            viz_paths = {}

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare results with REAL training metrics
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
            # REAL METRICS
            "epochs_trained": training_metrics.total_epochs,
            "best_epoch": training_metrics.best_epoch + 1,
            "final_train_loss": float(training_metrics.train_loss[-1]),
            "final_val_loss": float(training_metrics.val_loss[-1]),
            "best_val_loss": float(min(training_metrics.val_loss)),
            "test_loss": float(training_metrics.test_loss),
            "test_mae": float(training_metrics.test_mae),
            "test_rmse": float(training_metrics.test_rmse),
            "test_r2": float(training_metrics.test_r2),
            "model_path": training_metrics.model_path,
            "predictions_path": training_metrics.predictions_path,
            "visualizations": viz_paths,
            "completed_at": datetime.utcnow().isoformat()
        }

        # Add per-source metrics if available
        if hasattr(training_metrics, 'per_source_metrics'):
        # Create Model and ModelVersion
        from models.model import Model, ModelVersion
        model_name = config.config_data.get("model", {}).get("name", "LiquidityForecaster")
        model = db.query(Model).filter(Model.name == model_name).first()
        if not model:
            model = Model(name=model_name, description="Liquidity forecasting model")
            db.add(model)
            db.commit()
            db.refresh(model)

        model_version = ModelVersion(
            model_id=model.id,
            job_id=job_id,
            configuration_id=config.id,
            version=model.versions.count() + 1 if model.versions else 1,
            metrics=result,
            model_path=result["model_path"],
        )
        db.add(model_version)
        db.commit()

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

        model_version_id = parameters.get("model_version_id")
        data_job_id = parameters.get("data_job_id")

        from models.model import ModelVersion
        import torch
        import pandas as pd

        # 1. Load model
        model_version = db.query(ModelVersion).filter(ModelVersion.id == model_version_id).first()
        if not model_version:
            raise ValueError(f"Model version {model_version_id} not found.")

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model = torch.load(model_version.model_path, map_location=device)
        model.eval()

        # 2. Load data
        data_job_dir = f"/app/data/jobs/{data_job_id}"
        timeseries_df = pd.read_parquet(f"{data_job_dir}/timeseries.parquet")

        # 3. Run inference
        predictions = model.predict(timeseries_df)

        # 4. Save predictions
        output_dir = f"/app/data/jobs/{job_id}"
        os.makedirs(output_dir, exist_ok=True)
        predictions_path = f"{output_dir}/predictions.csv"
        predictions.to_csv(predictions_path, index=False)

        result = {
            "status": "completed",
            "predictions_path": predictions_path,
        }

        service.update_job_status(
            job_id,
            status="completed",
            progress=100.0,
            result=result
        )

        return result

    except Exception as e:
        logger.error(f"Prediction failed for job {job_id}: {e}")
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

        # NOTE: Placeholder - actual backtesting requires full pipeline
        logger.warning("Backtest job running with placeholder implementation")
        logger.info("Full backtesting requires pipeline orchestration")

        self.update_progress(job_id, 20.0)

        # Simulate processing
        import time
        time.sleep(2)

        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare placeholder results summary
        result = {
            "status": "placeholder",
            "message": "Backtesting requires full pipeline integration. Use pipeline API for complete backtesting.",
            "num_windows": 0,
            "avg_mse": None,
            "avg_mae": None,
            "completed_at": datetime.utcnow().isoformat()
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
from celery.schedules import crontab

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Run daily at midnight
    sender.add_periodic_task(
        crontab(hour=0, minute=0),
        monitor_production_model.s(),
    )

@celery_app.task(name="monitor_production_model")
def monitor_production_model():
    """Periodically monitor the production model for data drift and performance degradation."""
    db = SessionLocal()
    try:
        from models.model import ModelVersion
        from evidently.report import Report
        from evidently.metric_preset import DataDriftPreset
        import pandas as pd

        # 1. Get the production model
        prod_model = db.query(ModelVersion).filter(ModelVersion.stage == "Production").first()
        if not prod_model:
            logger.info("No production model to monitor.")
            return

        # 2. Get the training data
        training_job = prod_model.job
        training_data_path = f"/app/data/jobs/{training_job.id}/timeseries.parquet"
        reference_data = pd.read_parquet(training_data_path)

        # 3. Get the latest prediction data (assuming predictions are stored somewhere)
        # This part is a placeholder as prediction data storage is not fully implemented
        # In a real scenario, you would fetch the latest data that the model has predicted on
        # For now, we will simulate new data by taking a recent slice of the training data
        current_data = reference_data.tail(1000)

        # 4. Generate data drift report
        report = Report(metrics=[DataDriftPreset()])
        report.run(reference_data=reference_data, current_data=current_data)
        drift_report = report.as_dict()

        # 5. Check for drift and store report
        prod_model.metrics["drift_report"] = drift_report
        db.commit()

        if drift_report["data_drift"]["data"]["metrics"]["dataset_drift"]:
            logger.warning(f"Data drift detected for model {prod_model.model.name} v{prod_model.version}")
            # Create an alert (e.g., update model status, send notification)
            prod_model.status = "Drift Detected"
            db.commit()

            # Trigger retraining pipeline
            from services.pipeline_service import PipelineService
            pipeline_service = PipelineService(db)
            pipeline_service.trigger_retraining_pipeline(prod_model.id)

    except Exception as e:
        logger.error(f"Failed to monitor production model: {e}")
    finally:
        db.close()
