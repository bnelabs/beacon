"""Pipeline API - Orchestrates DATA → ENGINE → RESULTS flow."""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import uuid
import os

from database import get_db
from models.pipeline_job import PipelineJob, DataJob, EngineJob, ResultJob, PipelineStage, JobStatus
from services.error_logger import ErrorLogger
from auth import fastapi_users, current_active_user
from models.user import User

router = APIRouter()


class PipelineStartRequest(BaseModel):
    """Request to start complete pipeline."""
    name: str
    description: Optional[str] = None
    catalogue_items: List[int]  # List of catalogue item IDs
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    config: dict = {}


class PipelineStatusResponse(BaseModel):
    """Pipeline status response."""
    job_id: str
    name: str
    current_stage: str
    status: str
    progress: float
    current_step: Optional[str]

    data_status: Optional[str]
    engine_status: Optional[str]
    results_status: Optional[str]

    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[float]

    error_message: Optional[str]

    model_config = ConfigDict(from_attributes=True)


@router.post("", response_model=PipelineStatusResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=PipelineStatusResponse, status_code=status.HTTP_201_CREATED)
async def start_pipeline(
    request: PipelineStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Start complete DATA → ENGINE → RESULTS pipeline.

    **For non-technical users:** This starts the complete analysis:
    1. Collects and prepares your selected data
    2. Processes it through our AI models
    3. Generates comprehensive reports and recommendations

    You can monitor progress in real-time!
    """
    try:
        # Create pipeline job
        job_id = f"pipeline_{uuid.uuid4().hex[:12]}"

        pipeline_job = PipelineJob(
            job_id=job_id,
            name=request.name,
            description=request.description,
            current_stage=PipelineStage.DATA,
            status=JobStatus.PENDING,
            config=request.config,
            started_by="user",  # TODO: Get from auth
            started_at=datetime.utcnow()
        )

        db.add(pipeline_job)
        db.commit()
        db.refresh(pipeline_job)

        # Create DATA job
        data_job = DataJob(
            pipeline_job_id=pipeline_job.id,
            catalogue_items=request.catalogue_items,
            start_date=request.start_date,
            end_date=request.end_date,
            status=JobStatus.PENDING
        )

        db.add(data_job)
        db.commit()

        # Start pipeline in background
        background_tasks.add_task(
            _execute_pipeline,
            pipeline_job.id,
            request.catalogue_items,
            request.start_date,
            request.end_date,
            request.config
        )

        return PipelineStatusResponse(
            job_id=job_id,
            name=request.name,
            current_stage=pipeline_job.current_stage.value,
            status=pipeline_job.status.value,
            progress=0.0,
            current_step="Pipeline queued for execution",
            data_status="pending",
            engine_status=None,
            results_status=None,
            started_at=pipeline_job.started_at,
            completed_at=None,
            duration_seconds=None,
            error_message=None
        )

    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="starting pipeline",
            endpoint="/api/v1/pipeline",
            method="POST"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/{job_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Get current pipeline status.

    **For non-technical users:** Check how your analysis is progressing.
    Shows which stage it's in (data collection, AI processing, or report generation)
    and how complete it is.
    """
    try:
        pipeline_job = db.query(PipelineJob).filter(PipelineJob.job_id == job_id).first()

        if not pipeline_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"technical": f"Pipeline job {job_id} not found", "user_friendly": "This analysis job doesn't exist."}
            )

        # Get sub-job statuses
        data_job = db.query(DataJob).filter(DataJob.pipeline_job_id == pipeline_job.id).first()
        engine_job = db.query(EngineJob).filter(EngineJob.pipeline_job_id == pipeline_job.id).first()
        result_job = db.query(ResultJob).filter(ResultJob.pipeline_job_id == pipeline_job.id).first()

        return PipelineStatusResponse(
            job_id=pipeline_job.job_id,
            name=pipeline_job.name,
            current_stage=pipeline_job.current_stage.value,
            status=pipeline_job.status.value,
            progress=pipeline_job.progress,
            current_step=pipeline_job.current_step,
            data_status=data_job.status.value if data_job else None,
            engine_status=engine_job.status.value if engine_job else None,
            results_status=result_job.status.value if result_job else None,
            started_at=pipeline_job.started_at,
            completed_at=pipeline_job.completed_at,
            duration_seconds=pipeline_job.duration_seconds,
            error_message=pipeline_job.error_message
        )

    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context="getting pipeline status",
            endpoint=f"/api/v1/pipeline/{job_id}",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/{job_id}/data", response_model=dict)
async def get_data_report(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Get DATA module quality report.

    **For non-technical users:** See the quality of collected data,
    any issues found, and whether it's ready for AI processing.
    """
    try:
        pipeline_job = db.query(PipelineJob).filter(PipelineJob.job_id == job_id).first()
        if not pipeline_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        data_job = db.query(DataJob).filter(DataJob.pipeline_job_id == pipeline_job.id).first()
        if not data_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data job not found")

        return {
            "job_id": job_id,
            "status": data_job.status.value,
            "quality_score": data_job.quality_score,
            "completeness": data_job.completeness,
            "consistency": data_job.consistency,
            "fit_for_engine": bool(data_job.fit_for_engine),
            "anomalies_detected": data_job.anomalies_detected,
            "anomalies_fixed": data_job.anomalies_fixed,
            "output_path": data_job.output_path
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{job_id}/engine", response_model=dict)
async def get_engine_metrics(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Get ENGINE module performance metrics.

    **For non-technical users:** See how the AI models performed,
    what they computed, and the overall risk level detected.
    """
    try:
        pipeline_job = db.query(PipelineJob).filter(PipelineJob.job_id == job_id).first()
        if not pipeline_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        engine_job = db.query(EngineJob).filter(EngineJob.pipeline_job_id == pipeline_job.id).first()
        if not engine_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engine job not found")

        return {
            "job_id": job_id,
            "status": engine_job.status.value,
            "model": engine_job.model_name,
            "model_version": engine_job.model_version,
            "performance": {
                "mse": engine_job.mse,
                "mae": engine_job.mae,
                "r2": engine_job.r2,
                "accuracy": engine_job.accuracy
            },
            "risk_assessment": {
                "overall_score": engine_job.overall_risk_score,
                "risk_level": engine_job.risk_level
            },
            "compute": {
                "device": engine_job.device,
                "peak_memory_mb": engine_job.peak_memory_mb
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{job_id}/results", response_model=dict)
async def get_results_summary(
    job_id: str,
    db: Session = Depends(get_db)
):
    """
    Get RESULTS module summary.

    **For non-technical users:** Get the final report with risk analysis,
    recommendations, and visualizations.
    """
    try:
        pipeline_job = db.query(PipelineJob).filter(PipelineJob.job_id == job_id).first()
        if not pipeline_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        result_job = db.query(ResultJob).filter(ResultJob.pipeline_job_id == pipeline_job.id).first()
        if not result_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Results not yet generated")

        return {
            "job_id": job_id,
            "status": result_job.status.value,
            "report_version": result_job.report_version,
            "num_recommendations": result_job.num_recommendations,
            "num_visualizations": result_job.num_visualizations,
            "downloads": {
                "json": result_job.report_json_path,
                "pdf": result_job.report_pdf_path,
                "excel": result_job.report_excel_path
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


def _execute_pipeline(
    pipeline_job_id: int,
    catalogue_items: List[int],
    start_date: str,
    end_date: str,
    config: dict
):
    """
    Execute complete pipeline (runs in background).

    This is the main orchestration logic.
    """
    from database import SessionLocal
    from modules.data.orchestrator import DataOrchestrator
    from modules.engine.orchestrator import EngineOrchestrator
    from modules.results.generator import ResultsGenerator, ReportExporter

    db = SessionLocal()

    try:
        pipeline_job = db.query(PipelineJob).filter(PipelineJob.id == pipeline_job_id).first()
        data_job = db.query(DataJob).filter(DataJob.pipeline_job_id == pipeline_job_id).first()

        output_dir = f"/app/data/pipelines/{pipeline_job.job_id}"
        import os
        os.makedirs(output_dir, exist_ok=True)

        # ========== STAGE 1: DATA ==========
        pipeline_job.status = JobStatus.RUNNING
        pipeline_job.current_stage = PipelineStage.DATA
        data_job.status = JobStatus.RUNNING
        db.commit()

        data_orchestrator = DataOrchestrator(db, pipeline_job.job_id, output_dir)
        data_package = data_orchestrator.run(
            catalogue_items=catalogue_items,
            start_date=start_date,
            end_date=end_date,
            user_id="system"
        )

        # Update DATA job
        data_job.status = JobStatus.COMPLETED
        data_job.quality_score = data_package.quality_report.quality_score
        data_job.completeness = data_package.quality_report.completeness
        data_job.consistency = data_package.quality_report.consistency
        data_job.fit_for_engine = 1 if data_package.quality_report.fit_for_engine else 0
        data_job.anomalies_detected = data_package.quality_report.anomalies_detected
        data_job.anomalies_fixed = data_package.quality_report.anomalies_fixed
        data_job.output_path = data_package.timeseries_path
        data_job.completed_at = datetime.utcnow()

        pipeline_job.progress = 33.0
        db.commit()

        # ========== STAGE 2: ENGINE ==========
        pipeline_job.current_stage = PipelineStage.ENGINE
        db.commit()

        engine_job = EngineJob(
            pipeline_job_id=pipeline_job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow()
        )
        db.add(engine_job)
        db.commit()

        engine_orchestrator = EngineOrchestrator(pipeline_job.job_id, output_dir, config)
        engine_result = engine_orchestrator.process(data_package)

        # Update ENGINE job
        engine_job.status = JobStatus.COMPLETED
        engine_job.model_name = engine_result.model_name
        engine_job.model_version = engine_result.model_version
        engine_job.mse = engine_result.performance_metrics.get("mse")
        engine_job.mae = engine_result.performance_metrics.get("mae")
        engine_job.r2 = engine_result.performance_metrics.get("r2")
        engine_job.overall_risk_score = engine_result.risk_scores.overall_score
        engine_job.risk_level = engine_result.risk_scores.risk_level
        engine_job.device = engine_result.compute_stats.get("device")
        engine_job.peak_memory_mb = engine_result.compute_stats.get("memory_peak_mb")
        engine_job.predictions_path = engine_result.predictions_path
        engine_job.completed_at = datetime.utcnow()

        pipeline_job.progress = 66.0
        db.commit()

        # ========== STAGE 3: RESULTS ==========
        pipeline_job.current_stage = PipelineStage.RESULTS
        db.commit()

        result_job = ResultJob(
            pipeline_job_id=pipeline_job_id,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow()
        )
        db.add(result_job)
        db.commit()

        results_generator = ResultsGenerator(pipeline_job.job_id, output_dir)
        report = results_generator.generate(engine_result)

        # Export reports
        exporter = ReportExporter(output_dir)
        json_path = exporter.export_json(report)
        pdf_path = exporter.export_pdf(report)
        excel_path = exporter.export_excel(report)

        # Update RESULTS job
        result_job.status = JobStatus.COMPLETED
        result_job.report_version = report.version
        result_job.num_recommendations = len(report.recommendations)
        result_job.num_visualizations = len(report.visualizations)
        result_job.report_json_path = json_path
        result_job.report_pdf_path = pdf_path
        result_job.report_excel_path = excel_path
        result_job.completed_at = datetime.utcnow()

        # Complete pipeline
        pipeline_job.status = JobStatus.COMPLETED
        pipeline_job.progress = 100.0
        pipeline_job.completed_at = datetime.utcnow()
        pipeline_job.duration_seconds = (pipeline_job.completed_at - pipeline_job.started_at).total_seconds()
        db.commit()

    except Exception as e:
        pipeline_job.status = JobStatus.FAILED
        pipeline_job.error_message = str(e)

        if data_job and data_job.status == JobStatus.RUNNING:
            data_job.status = JobStatus.FAILED

        db.commit()

        import traceback
        print(f"Pipeline failed: {e}")
        print(traceback.format_exc())

    finally:
        db.close()


@router.get("/{job_id}/download/{format}")
async def download_results(
    job_id: str,
    format: str,
    db: Session = Depends(get_db)
):
    """
    Download pipeline results in specified format.

    **Formats**: json, pdf, excel

    **For non-technical users:** Download your complete risk analysis report
    in your preferred format (JSON for data, PDF for reading, Excel for analysis).
    """
    try:
        # Validate format
        if format not in ['json', 'pdf', 'excel']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"technical": f"Invalid format: {format}", "user_friendly": "Please choose json, pdf, or excel format."}
            )

        # Get pipeline job
        pipeline_job = db.query(PipelineJob).filter(PipelineJob.job_id == job_id).first()
        if not pipeline_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"technical": f"Pipeline job {job_id} not found", "user_friendly": "This analysis job doesn't exist."}
            )

        # Get result job
        result_job = db.query(ResultJob).filter(ResultJob.pipeline_job_id == pipeline_job.id).first()
        if not result_job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"technical": "Results not yet generated", "user_friendly": "The analysis results are not ready yet. Please wait for the job to complete."}
            )

        # Get file path based on format
        file_path = None
        media_type = None
        filename = None

        if format == 'json':
            file_path = result_job.report_json_path
            media_type = "application/json"
            filename = f"{job_id}_report.json"
        elif format == 'pdf':
            file_path = result_job.report_pdf_path
            media_type = "application/pdf"
            filename = f"{job_id}_report.pdf"
        elif format == 'excel':
            file_path = result_job.report_excel_path
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"{job_id}_report.xlsx"

        # Check if file exists
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "technical": f"File not found: {file_path}",
                    "user_friendly": f"The {format.upper()} report file is not available. It may still be generating or failed to generate."
                }
            )

        # Return file
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(
            e,
            context=f"downloading {format} results",
            endpoint=f"/api/v1/pipeline/{job_id}/download/{format}",
            method="GET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
