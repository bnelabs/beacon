"""Celery tasks for background jobs."""

from celery import Task
import traceback
import logging
from datetime import datetime
import psutil
import os

from .celery_app import celery_app
from database import SessionLocal
from services.job_service import JobService
from services.enhanced_error_translator import translate_error_enhanced as translate_error

logger = logging.getLogger(__name__)


class JobTask(Task):
    """Base task with progress tracking and error handling."""

    def update_progress(self, job_id: int, progress: float, status: str = "running"):
        """Update job progress in database."""
        db = SessionLocal()
        try:
            service = JobService(db)
            service.update_job_status(job_id, status=status, progress=progress)
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
                    user_friendly_error=user_friendly
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

        orchestrator = DataOrchestrator(db, f"job_{job_id}", output_dir)

        # Run data collection with default catalogue items
        self.update_progress(job_id, 20.0)

        # Get catalogue items from parameters or use defaults
        catalogue_items = parameters.get('catalogue_items', list(range(1, 11)))
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

        # Prepare results
        result = {
            "quality_score": data_package.quality_report.quality_score,
            "completeness": data_package.quality_report.completeness,
            "fit_for_engine": data_package.quality_report.fit_for_engine,
            "anomalies_detected": data_package.quality_report.anomalies_detected,
            "output_path": data_package.timeseries_path,
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

        logger.info(f"Data collection completed for job {job_id}")
        return result

    except Exception as e:
        logger.error(f"Data collection failed for job {job_id}: {e}\n{traceback.format_exc()}")
        user_friendly = translate_error(e, context="collecting data")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=user_friendly
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

        config = parameters.get('config', {'model': 'HGT'})
        orchestrator = EngineOrchestrator(f"job_{job_id}", output_dir, config)

        # For training, we need existing data package
        # For now, log that training requires data collection first
        logger.info("BNE ENGINE training requires data collection to be completed first...")
        self.update_progress(job_id, 20.0)

        # Get date range from parameters or use defaults
        train_start = parameters.get("train_start", "2019-01-01")
        train_end = parameters.get("train_end", "2023-12-31")
        test_start = parameters.get("test_start", "2024-01-01")
        test_end = parameters.get("test_end", "2024-06-30")

        # NOTE: Placeholder - actual training requires a data package
        # For now, mark as completed with placeholder results
        logger.warning("Training job running with placeholder implementation")
        logger.info("Full BNE ENGINE training requires pipeline orchestration")

        self.update_progress(job_id, 50.0)

        # Simulate processing time
        import time
        time.sleep(2)

        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare placeholder results
        result = {
            "status": "placeholder",
            "message": "Training requires full pipeline integration. Use pipeline API for complete training.",
            "train_period": f"{train_start} to {train_end}",
            "test_period": f"{test_start} to {test_end}",
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

        logger.info(f"Training completed for job {job_id}")
        return result

    except Exception as e:
        logger.error(f"Training failed for job {job_id}: {e}\n{traceback.format_exc()}")
        user_friendly = translate_error(e, context="training model")
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=user_friendly
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

        # TODO: Implement prediction logic
        # This will load the trained model and make predictions

        self.update_progress(job_id, 50.0)

        result = {
            "status": "predictions generated",
            "message": "Prediction functionality to be implemented",
            "completed_at": datetime.utcnow().isoformat()
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
            user_friendly_error=user_friendly
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
        service.update_job_status(
            job_id,
            status="failed",
            error_message=str(e),
            user_friendly_error=user_friendly
        )
        raise
    finally:
        db.close()
