"""Error translation service for user-friendly error messages."""

import re
from typing import Optional


def translate_error(exception: Exception, context: str = "") -> str:
    """
    Translate technical exceptions into user-friendly messages.

    Args:
        exception: The exception to translate
        context: Context about what operation was being performed

    Returns:
        User-friendly error message
    """
    error_str = str(exception)
    error_type = type(exception).__name__

    # Database connection errors
    if "connection" in error_str.lower() or error_type in ["OperationalError", "DatabaseError"]:
        return (
            "Cannot connect to the database. This usually means the database service is not running. "
            "Please contact your system administrator."
        )

    # API key errors
    if "api" in error_str.lower() and ("key" in error_str.lower() or "401" in error_str or "403" in error_str):
        return (
            "The API key for this data source is missing or invalid. "
            "Please check that you've entered the correct API key in the data source configuration."
        )

    # Rate limit errors
    if "rate limit" in error_str.lower() or "429" in error_str or "too many requests" in error_str.lower():
        return (
            "You've made too many requests to the data provider. "
            "The system will automatically retry in a few moments. You can also increase the "
            "'API Rate Limit' setting in the configuration to slow down requests."
        )

    # Network errors
    if any(term in error_str.lower() for term in ["timeout", "network", "connection refused", "unreachable"]):
        return (
            "Cannot reach the data provider's server. This could be due to: "
            "(1) Your internet connection is down, "
            "(2) The data provider's service is temporarily unavailable, or "
            "(3) A firewall is blocking the connection. "
            "Please try again in a few minutes."
        )

    # Data validation errors
    if error_type in ["ValidationError", "ValueError"] and "schema" in error_str.lower():
        return (
            "The data received doesn't match the expected format. "
            "This could mean the data source changed its format or returned incomplete data. "
            "Try collecting data again, or check if the data source is working properly."
        )

    # Out of memory errors
    if "out of memory" in error_str.lower() or "oom" in error_str.lower():
        return (
            "The system ran out of memory. Try reducing the batch size in the training configuration, "
            "or monitor fewer assets at once. You can also check the system status page for "
            "resource usage recommendations."
        )

    # File not found errors
    if error_type in ["FileNotFoundError", "IOError"] or "no such file" in error_str.lower():
        return (
            "A required file is missing. This could mean: "
            "(1) The data hasn't been collected yet - try running a data collection job first, "
            "(2) Previous data was deleted, or "
            "(3) There's a configuration error. "
            f"Context: {context}"
        )

    # Permission errors
    if error_type == "PermissionError" or "permission denied" in error_str.lower():
        return (
            "The system doesn't have permission to access a required file or directory. "
            "Please contact your system administrator to fix file permissions."
        )

    # Duplicate key errors (database)
    if "duplicate" in error_str.lower() or "unique constraint" in error_str.lower():
        # Try to extract the conflicting value
        match = re.search(r"'([^']+)'", error_str)
        value = match.group(1) if match else "this value"
        return (
            f"A {context} with {value} already exists. "
            f"Please choose a different name or symbol."
        )

    # Foreign key constraint errors
    if "foreign key" in error_str.lower() or "constraint" in error_str.lower():
        return (
            f"Cannot complete this operation because it references something that doesn't exist. "
            f"For example, you might be trying to add an asset with a data source that was deleted. "
            f"Please check your configuration and try again."
        )

    # Model/training errors
    if "cuda" in error_str.lower() or "gpu" in error_str.lower():
        return (
            "There's an issue with GPU processing. The system will try to use CPU instead, "
            "but training may be slower. If you have a GPU, make sure the CUDA drivers are installed correctly."
        )

    # Generic fallback based on context
    context_messages = {
        "listing": "There was a problem retrieving the list.",
        "creating": "There was a problem creating the item.",
        "updating": "There was a problem updating the item.",
        "deleting": "There was a problem deleting the item.",
        "testing": "There was a problem testing the connection.",
        "starting": "There was a problem starting the job.",
        "collecting": "There was a problem collecting data.",
        "training": "There was a problem training the model.",
    }

    for key, message in context_messages.items():
        if key in context.lower():
            return (
                f"{message} "
                f"Error details: {error_type}. "
                f"Please try again or contact support if the problem persists."
            )

    # Ultimate fallback
    return (
        f"An unexpected error occurred while {context}. "
        f"Technical details: {error_type}. "
        f"Please try again or contact support if the problem persists."
    )
