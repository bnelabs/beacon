"""Data validation utilities using pandera."""

import pandera as pa
from pandera import Column, DataFrameModel
from datetime import datetime
from typing import Dict, Any


class AssetDataSchema(pa.DataFrameModel):
    """Schema for asset price data.

    Validates that all price data meets expected constraints:
    - All prices must be non-negative
    - Volume must be a non-negative integer (note: may overflow for very large volumes)
    - Date and Asset fields are required
    """

    Date: Column[datetime] = pa.Field(required=True)
    Asset: Column[str] = pa.Field(required=True)
    Close: Column[float] = pa.Field(ge=0, required=True)
    High: Column[float] = pa.Field(ge=0, required=True)
    Low: Column[float] = pa.Field(ge=0, required=True)
    Open: Column[float] = pa.Field(ge=0, required=True)
    Volume: Column[int] = pa.Field(ge=0, required=True)


class IndicatorDataSchema(pa.DataFrameModel):
    """Schema for market indicator data."""
    
    Date: Column[datetime] = pa.Field(required=True)
    Value: Column[float] = pa.Field(required=True)


class FredDataSchema(pa.DataFrameModel):
    """Schema for FRED economic data."""
    
    Date: Column[datetime] = pa.Field(required=True)
    
    class Config:
        """Schema configuration."""
        strict = False  # Allow additional columns for different indicators


def validate_asset_data(df: pa.DataFrame) -> Dict[str, Any]:
    """
    Validate asset data against schema.

    Args:
        df: DataFrame to validate

    Returns:
        Validation results with keys:
        - valid: bool indicating if validation passed
        - data: validated DataFrame if valid, None otherwise
        - errors: failure cases if validation failed, None otherwise
    """
    try:
        validated_df = AssetDataSchema.validate(df, lazy=True)
        return {"valid": True, "data": validated_df, "errors": None}
    except pa.errors.SchemaErrors as e:
        # Return detailed error information for debugging
        error_summary = f"Found {len(e.failure_cases)} validation errors"
        return {
            "valid": False,
            "data": None,
            "errors": e.failure_cases,
            "error_summary": error_summary
        }


def validate_indicator_data(df: pa.DataFrame) -> Dict[str, Any]:
    """
    Validate indicator data against schema.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Validation results
    """
    try:
        validated_df = IndicatorDataSchema.validate(df, lazy=True)
        return {"valid": True, "data": validated_df, "errors": None}
    except pa.errors.SchemaErrors as e:
        return {"valid": False, "data": None, "errors": e.failure_cases}


def validate_fred_data(df: pa.DataFrame) -> Dict[str, Any]:
    """
    Validate FRED data against schema.
    
    Args:
        df: DataFrame to validate
        
    Returns:
        Validation results
    """
    try:
        validated_df = FredDataSchema.validate(df, lazy=True)
        return {"valid": True, "data": validated_df, "errors": None}
    except pa.errors.SchemaErrors as e:
        return {"valid": False, "data": None, "errors": e.failure_cases}
