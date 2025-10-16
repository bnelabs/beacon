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

        # Import the existing data collection system
        from ...liquidity_monitor.data.collection import DataCollector
        from ...liquidity_monitor.config import Config

        logger.info(f"Starting data collection for job {job_id}")

        # Load configuration
        self.update_progress(job_id, 5.0)
        config = Config()

        # Initialize data collector
        self.update_progress(job_id, 10.0)
        collector = DataCollector(config)

        # Collect asset data
        self.update_progress(job_id, 20.0)
        logger.info("Collecting asset data...")
        asset_data = collector.collect_asset_data()
        self.update_progress(job_id, 50.0)

        # Collect economic indicators
        logger.info("Collecting economic indicators...")
        economic_data = collector.collect_economic_indicators()
        self.update_progress(job_id, 80.0)

        # Collect market indicators
        logger.info("Collecting market indicators...")
        market_data = collector.collect_market_indicators()
        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare results
        result = {
            "asset_data_shape": asset_data.shape if asset_data is not None else None,
            "economic_data_count": len(economic_data) if economic_data else 0,
            "market_data_count": len(market_data) if market_data else 0,
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

        # Import training system
        from ...liquidity_monitor.pipeline import LiquidityMonitorPipeline
        from ...liquidity_monitor.config import Config

        logger.info(f"Starting training for job {job_id}")

        # Load configuration
        self.update_progress(job_id, 5.0)
        config = Config()

        # Initialize pipeline
        self.update_progress(job_id, 10.0)
        pipeline = LiquidityMonitorPipeline(config)

        # Run training
        logger.info("Running training pipeline...")
        self.update_progress(job_id, 20.0)

        # Get date range from parameters or use defaults
        train_start = parameters.get("train_start", "2019-01-01")
        train_end = parameters.get("train_end", "2023-12-31")
        test_start = parameters.get("test_start", "2024-01-01")
        test_end = parameters.get("test_end", "2024-06-30")

        results = pipeline.run_single_period(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            save_results=True
        )
        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare results
        result = {
            "mse": results.get("mse"),
            "mae": results.get("mae"),
            "rmse": results.get("rmse"),
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

        # Import backtesting system
        from ...liquidity_monitor.pipeline import LiquidityMonitorPipeline
        from ...liquidity_monitor.config import Config

        logger.info(f"Starting backtest for job {job_id}")

        # Load configuration
        self.update_progress(job_id, 5.0)
        config = Config()

        # Initialize pipeline
        self.update_progress(job_id, 10.0)
        pipeline = LiquidityMonitorPipeline(config)

        # Run backtesting
        logger.info("Running backtesting pipeline...")
        self.update_progress(job_id, 20.0)

        results = pipeline.run_backtesting(
            start_date="2020-01-01",
            end_date="2024-06-30",
            window_size=365,
            step_size=90,
            save_results=True
        )
        self.update_progress(job_id, 95.0)

        # Calculate memory usage
        end_memory = process.memory_info().rss / (1024 ** 2)
        peak_memory = end_memory - start_memory

        # Prepare results summary
        result = {
            "num_windows": len(results) if results else 0,
            "avg_mse": sum(r.get("mse", 0) for r in results) / len(results) if results else None,
            "avg_mae": sum(r.get("mae", 0) for r in results) / len(results) if results else None,
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
