"""API routes for system monitoring."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import psutil
import torch

from database import get_db
from services.error_logger import ErrorLogger

router = APIRouter()


@router.get("/status")
async def get_system_status(db: Session = Depends(get_db)):
    """
    Get system health and resource usage.

    **For non-technical users:** See if the system is running properly and
    how much memory and processing power is being used.
    """
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()

        # Memory usage
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024 ** 3)
        memory_used_gb = memory.used / (1024 ** 3)
        memory_percent = memory.percent

        # GPU usage (if available)
        gpu_info = {}
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            gpu_info = {
                "available": True,
                "count": gpu_count,
                "devices": []
            }
            for i in range(gpu_count):
                gpu_props = torch.cuda.get_device_properties(i)
                memory_allocated = torch.cuda.memory_allocated(i) / (1024 ** 3)
                memory_reserved = torch.cuda.memory_reserved(i) / (1024 ** 3)
                memory_total = gpu_props.total_memory / (1024 ** 3)

                gpu_info["devices"].append({
                    "id": i,
                    "name": gpu_props.name,
                    "memory_allocated_gb": round(memory_allocated, 2),
                    "memory_reserved_gb": round(memory_reserved, 2),
                    "memory_total_gb": round(memory_total, 2),
                    "memory_percent": round((memory_reserved / memory_total) * 100, 1)
                })
        else:
            gpu_info = {"available": False}

        # Disk usage
        disk = psutil.disk_usage('/')
        disk_total_gb = disk.total / (1024 ** 3)
        disk_used_gb = disk.used / (1024 ** 3)
        disk_percent = disk.percent

        return {
            "status": "operational",
            "cpu": {
                "cores": cpu_count,
                "usage_percent": round(cpu_percent, 1)
            },
            "memory": {
                "total_gb": round(memory_total_gb, 2),
                "used_gb": round(memory_used_gb, 2),
                "usage_percent": round(memory_percent, 1)
            },
            "gpu": gpu_info,
            "disk": {
                "total_gb": round(disk_total_gb, 2),
                "used_gb": round(disk_used_gb, 2),
                "usage_percent": round(disk_percent, 1)
            }
        }
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="checking system status", endpoint="/api/v1/system/status", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )


@router.get("/resources/recommendations")
async def get_resource_recommendations(db: Session = Depends(get_db)):
    """
    Get resource usage recommendations.

    **For non-technical users:** Get suggestions on whether you should
    adjust batch sizes or other settings based on your available resources.
    """
    try:
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024 ** 3)

        gpu_memory_gb = 0
        if torch.cuda.is_available():
            gpu_props = torch.cuda.get_device_properties(0)
            gpu_memory_gb = gpu_props.total_memory / (1024 ** 3)

        recommendations = []

        # Memory recommendations
        if memory_total_gb < 16:
            recommendations.append({
                "category": "memory",
                "severity": "warning",
                "message": "Your system has limited RAM. Consider reducing batch size to 16 or lower.",
                "suggested_config": {"batch_size": 16}
            })
        elif memory_total_gb >= 32:
            recommendations.append({
                "category": "memory",
                "severity": "info",
                "message": "You have plenty of RAM. You can use larger batch sizes (32-64) for faster training.",
                "suggested_config": {"batch_size": 32}
            })

        # GPU recommendations
        if not torch.cuda.is_available():
            recommendations.append({
                "category": "gpu",
                "severity": "info",
                "message": "No GPU detected. Training will use CPU and may be slower. Consider using a smaller model (hidden_dim=64).",
                "suggested_config": {"hidden_dim": 64, "num_layers": 2}
            })
        elif gpu_memory_gb < 8:
            recommendations.append({
                "category": "gpu",
                "severity": "warning",
                "message": "Your GPU has limited memory. Reduce batch size or model size if you encounter out-of-memory errors.",
                "suggested_config": {"batch_size": 16, "hidden_dim": 128}
            })
        elif gpu_memory_gb >= 24:
            recommendations.append({
                "category": "gpu",
                "severity": "info",
                "message": "Your GPU has excellent memory. You can use larger models and batch sizes for better accuracy.",
                "suggested_config": {"batch_size": 64, "hidden_dim": 256, "num_layers": 4}
            })

        return {
            "system_resources": {
                "ram_gb": round(memory_total_gb, 1),
                "gpu_memory_gb": round(gpu_memory_gb, 1) if gpu_memory_gb > 0 else None
            },
            "recommendations": recommendations
        }
    except Exception as e:
        error_logger = ErrorLogger(db)
        error_log = error_logger.log_error(e, context="generating recommendations", endpoint="/api/v1/system/resources/recommendations", method="GET")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"technical": error_log.technical_message, "user_friendly": error_log.user_message}
        )
