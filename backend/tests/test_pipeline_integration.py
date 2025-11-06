"""Integration tests that execute the pipeline offline using local CSV data."""

from __future__ import annotations

import os
from datetime import date, timedelta, datetime, UTC
from importlib import reload
from pathlib import Path
from uuid import uuid4

import pandas as pd


def _prepare_csv_dataset(csv_path: Path, asset: str = "TEST_ASSET") -> None:
    """Create a synthetic asset price CSV with deterministic values."""
    rows = []
    start = date(2023, 1, 1)
    for offset in range(60):
        current = start + timedelta(days=offset)
        base = 100 + offset * 0.5
        rows.append(
            {
                "Date": current.isoformat(),
                "Asset": asset,
                "Open": base - 1,
                "High": base + 1,
                "Low": base - 2,
                "Close": base,
                "Volume": 1000 + offset,
            }
        )
    pd.DataFrame(rows).to_csv(csv_path, index=False)


def test_execute_pipeline_end_to_end(tmp_path):
    """Ensure the DATA → ENGINE → RESULTS pipeline completes successfully offline."""
    db_path = tmp_path / "pipeline.sqlite3"
    os.environ["USE_SQLITE"] = "true"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["PIPELINE_DATA_DIR"] = str(tmp_path / "pipelines")

    import backend.database as database

    # Reload database module so engine/session bind to the new SQLite URL
    database = reload(database)
    init_db = database.init_db
    SessionLocal = database.SessionLocal

    # Lazily import models after database reload to bind them to the refreshed Base
    from backend.models.data_source import DataSource
    from backend.models.data_catalogue import (
        DataCatalogueItem,
        DataCategory,
        DataRegion,
        RiskType,
    )
    from backend.models.pipeline_job import (
        PipelineJob,
        DataJob,
        EngineJob,
        ResultJob,
        PipelineStage,
        JobStatus,
    )
    from backend.api.routes.pipeline import _execute_pipeline

    # Initialise database schema for the isolated SQLite database
    database.Base.metadata.drop_all(bind=database.engine)
    init_db()

    csv_path = tmp_path / "asset.csv"
    _prepare_csv_dataset(csv_path)

    session = SessionLocal()

    # Seed minimal data source and catalogue metadata
    source_name = f"CSV Source {uuid4().hex[:8]}"
    data_source = DataSource(
        name=source_name,
        plugin_type="csv",
        config={"file_path": str(csv_path)},
        description="Synthetic CSV source for integration tests",
    )
    session.add(data_source)
    session.commit()
    session.refresh(data_source)

    catalogue_code = f"TEST_SERIES_{uuid4().hex[:8]}"
    catalogue_item = DataCatalogueItem(
        code=catalogue_code,
        name="Test Series",
        description="Synthetic catalogue entry",
        category=DataCategory.EXCHANGE_RATES,
        region=DataRegion.GLOBAL,
        risk_types=[RiskType.MARKET_LIQUIDITY.value],
        data_source_id=data_source.id,
        endpoint="TEST_ASSET",
        frequency="daily",
        granularity="macro",
        unit="index",
        enabled=True,
        default_selected=True,
        priority=1,
        parameters={},
    )
    session.add(catalogue_item)
    session.commit()
    session.refresh(catalogue_item)
    catalogue_id = catalogue_item.id

    pipeline_identifier = f"pipeline_{uuid4().hex[:8]}"
    pipeline_job = PipelineJob(
        job_id=pipeline_identifier,
        name="Integration Test Pipeline",
        description="End-to-end offline run",
        current_stage=PipelineStage.DATA,
        status=JobStatus.PENDING,
        config={"sequence_length": 10, "batch_size": 8, "model": "integration_fallback"},
        started_by="pytest",
        started_at=datetime.now(UTC),
    )
    session.add(pipeline_job)
    session.commit()
    session.refresh(pipeline_job)
    pipeline_id = pipeline_job.id

    data_job = DataJob(
        pipeline_job_id=pipeline_job.id,
        catalogue_items=[catalogue_item.id],
        start_date="2023-01-01",
        end_date="2023-03-01",
        status=JobStatus.PENDING,
    )
    session.add(data_job)
    session.commit()
    session.close()

    # Execute the full pipeline synchronously using the helper
    _execute_pipeline(
        pipeline_id,
        [catalogue_id],
        "2023-01-01",
        "2023-03-01",
        {"sequence_length": 10, "batch_size": 8, "model": "integration_fallback"},
    )

    session = SessionLocal()
    try:
        refreshed_job = session.query(PipelineJob).filter_by(id=pipeline_id).one()
        assert refreshed_job.status == JobStatus.COMPLETED
        assert refreshed_job.progress == 100.0

        stored_data_job = session.query(DataJob).filter_by(pipeline_job_id=pipeline_id).one()
        assert stored_data_job.status == JobStatus.COMPLETED
        assert Path(stored_data_job.output_path).exists()

        stored_engine_job = session.query(EngineJob).filter_by(pipeline_job_id=pipeline_id).one()
        assert stored_engine_job.status == JobStatus.COMPLETED
        assert Path(stored_engine_job.predictions_path).exists()

        stored_result_job = session.query(ResultJob).filter_by(pipeline_job_id=pipeline_id).one()
        assert stored_result_job.status == JobStatus.COMPLETED
        assert Path(stored_result_job.report_json_path).exists()
        assert Path(stored_result_job.report_pdf_path).exists()
        assert Path(stored_result_job.report_excel_path).exists()
    finally:
        session.close()
