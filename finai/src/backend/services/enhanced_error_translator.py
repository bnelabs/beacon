"""Enhanced error translation system with detailed categorization and solutions."""

import re
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass


class ErrorSeverity(Enum):
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for classification."""
    NETWORK = "network"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    RESOURCE = "resource"
    PERMISSION = "permission"
    DATA = "data"
    CONFIGURATION = "configuration"
    SYSTEM = "system"


@dataclass
class ErrorDetails:
    """Structured error information."""
    severity: ErrorSeverity
    category: ErrorCategory
    user_message: str
    technical_message: str
    solutions: List[str]
    recovery_possible: bool
    retry_recommended: bool
    contact_support: bool


class EnhancedErrorTranslator:
    """Advanced error translator with structured error handling."""

    @staticmethod
    def translate(exception: Exception, context: str = "") -> ErrorDetails:
        """
        Translate exception into structured error details.

        Args:
            exception: The exception to translate
            context: Context about what operation was being performed

        Returns:
            ErrorDetails with complete error information
        """
        error_str = str(exception)
        error_type = type(exception).__name__

        # Try specific error patterns first
        patterns = [
            EnhancedErrorTranslator._check_network_errors,
            EnhancedErrorTranslator._check_authentication_errors,
            EnhancedErrorTranslator._check_rate_limit_errors,
            EnhancedErrorTranslator._check_validation_errors,
            EnhancedErrorTranslator._check_resource_errors,
            EnhancedErrorTranslator._check_permission_errors,
            EnhancedErrorTranslator._check_database_errors,
            EnhancedErrorTranslator._check_data_errors,
            EnhancedErrorTranslator._check_configuration_errors,
        ]

        for pattern_checker in patterns:
            result = pattern_checker(error_str, error_type, context)
            if result:
                return result

        # Fallback for unknown errors
        return EnhancedErrorTranslator._create_generic_error(error_str, error_type, context)

    @staticmethod
    def _check_network_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for network-related errors."""
        network_keywords = ["timeout", "network", "connection refused", "unreachable", "dns", "resolve"]

        if any(keyword in error_str.lower() for keyword in network_keywords):
            return ErrorDetails(
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.NETWORK,
                user_message="Cannot connect to the external service",
                technical_message=f"{error_type}: {error_str[:200]}",
                solutions=[
                    "Check your internet connection",
                    "Verify the service URL is correct",
                    "Wait a few minutes and try again (service may be down)",
                    "Check if a firewall is blocking the connection",
                    "Contact your network administrator if the problem persists"
                ],
                recovery_possible=True,
                retry_recommended=True,
                contact_support=False
            )
        return None

    @staticmethod
    def _check_authentication_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for authentication/authorization errors."""
        auth_patterns = [
            (["401", "unauthorized", "unauthenticated"], "API key is missing or invalid"),
            (["403", "forbidden", "access denied"], "API key doesn't have required permissions"),
            (["api key", "api_key", "apikey"], "API key configuration issue")
        ]

        for keywords, message in auth_patterns:
            if any(keyword in error_str.lower() for keyword in keywords):
                return ErrorDetails(
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.AUTHENTICATION,
                    user_message=f"Authentication failed: {message}",
                    technical_message=f"{error_type}: {error_str[:200]}",
                    solutions=[
                        "Verify your API key is entered correctly",
                        "Check if the API key has expired",
                        "Ensure the API key has the required permissions",
                        "Re-generate a new API key from the provider's website",
                        "Test the connection in the Data Sources page"
                    ],
                    recovery_possible=True,
                    retry_recommended=False,
                    contact_support=False
                )
        return None

    @staticmethod
    def _check_rate_limit_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for rate limiting errors."""
        if any(term in error_str.lower() for term in ["rate limit", "429", "too many requests", "quota exceeded"]):
            return ErrorDetails(
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.NETWORK,
                user_message="You've exceeded the API rate limit",
                technical_message=f"{error_type}: {error_str[:200]}",
                solutions=[
                    "Wait a few minutes before trying again",
                    "Increase the 'API Rate Limit' setting in Configuration → Data Collection",
                    "Reduce the number of assets you're monitoring",
                    "Consider upgrading to a paid API tier for higher limits",
                    "Spread out your data collection over a longer time period"
                ],
                recovery_possible=True,
                retry_recommended=True,
                contact_support=False
            )
        return None

    @staticmethod
    def _check_validation_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for data validation errors."""
        if error_type in ["ValidationError", "ValueError"] and "schema" in error_str.lower():
            return ErrorDetails(
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.VALIDATION,
                user_message="Data received doesn't match the expected format",
                technical_message=f"{error_type}: {error_str[:200]}",
                solutions=[
                    "The data provider may have changed their data format",
                    "Try collecting data again - it might be a temporary issue",
                    "Check if the data source is working properly",
                    "Verify the asset symbol/ticker is valid",
                    "Contact support if this error persists"
                ],
                recovery_possible=True,
                retry_recommended=True,
                contact_support=True
            )
        return None

    @staticmethod
    def _check_resource_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for resource exhaustion errors."""
        resource_patterns = [
            (["out of memory", "oom", "memory error"], "memory", [
                "Reduce batch size in Configuration → Training",
                "Monitor fewer assets at once",
                "Close other applications to free up RAM",
                "Check System Status page for current memory usage",
                "Consider upgrading your system RAM"
            ]),
            (["disk space", "no space", "disk full"], "disk", [
                "Free up disk space by deleting old files",
                "Check the results/ and data/ directories",
                "Move old backtest results to external storage",
                "Increase disk space allocation"
            ]),
            (["cuda", "gpu"], "GPU", [
                "System will automatically fall back to CPU",
                "Reduce batch size if training on GPU",
                "Check GPU drivers are installed correctly",
                "Verify CUDA toolkit is installed"
            ])
        ]

        for keywords, resource_type, solutions in resource_patterns:
            if any(keyword in error_str.lower() for keyword in keywords):
                return ErrorDetails(
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.RESOURCE,
                    user_message=f"System {resource_type} resources are exhausted",
                    technical_message=f"{error_type}: {error_str[:200]}",
                    solutions=solutions,
                    recovery_possible=True,
                    retry_recommended=True,
                    contact_support=False
                )
        return None

    @staticmethod
    def _check_permission_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for file permission errors."""
        if error_type == "PermissionError" or "permission denied" in error_str.lower():
            return ErrorDetails(
                severity=ErrorSeverity.ERROR,
                category=ErrorCategory.PERMISSION,
                user_message="The system doesn't have permission to access a required resource",
                technical_message=f"{error_type}: {error_str[:200]}",
                solutions=[
                    "Contact your system administrator",
                    "Check file and directory permissions",
                    "Ensure the application has write access to data/ and results/ folders",
                    "If running in Docker, verify volume mount permissions"
                ],
                recovery_possible=True,
                retry_recommended=False,
                contact_support=True
            )
        return None

    @staticmethod
    def _check_database_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for database-related errors."""
        db_patterns = [
            (["duplicate", "unique constraint"], "Duplicate entry", [
                "This item already exists in the database",
                "Choose a different name or symbol",
                "Check existing items before creating new ones"
            ]),
            (["foreign key", "constraint"], "Referenced item doesn't exist", [
                "The item you're referencing (e.g., data source) may have been deleted",
                "Verify all referenced items exist",
                "Refresh the page and try again"
            ]),
            (["connection", "operational"], "Database connection issue", [
                "The database service may not be running",
                "Wait a moment and try again",
                "Contact your system administrator",
                "Check Docker containers are running: docker-compose ps"
            ])
        ]

        for keywords, issue, solutions in db_patterns:
            if any(keyword in error_str.lower() for keyword in keywords):
                return ErrorDetails(
                    severity=ErrorSeverity.ERROR,
                    category=ErrorCategory.DATA,
                    user_message=f"Database error: {issue}",
                    technical_message=f"{error_type}: {error_str[:200]}",
                    solutions=solutions,
                    recovery_possible=True,
                    retry_recommended=True,
                    contact_support=False
                )
        return None

    @staticmethod
    def _check_data_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for data-related errors."""
        if error_type in ["FileNotFoundError", "IOError"] or "no such file" in error_str.lower():
            return ErrorDetails(
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.DATA,
                user_message="Required data file is missing",
                technical_message=f"{error_type}: {error_str[:200]}",
                solutions=[
                    "Run a data collection job first to download the required data",
                    "Check if previous data was accidentally deleted",
                    "Verify the data/ directory exists and is accessible",
                    "Review recent operations that may have affected data files"
                ],
                recovery_possible=True,
                retry_recommended=True,
                contact_support=False
            )
        return None

    @staticmethod
    def _check_configuration_errors(error_str: str, error_type: str, context: str) -> Optional[ErrorDetails]:
        """Check for configuration errors."""
        if "config" in error_str.lower() or "configuration" in context.lower():
            return ErrorDetails(
                severity=ErrorSeverity.WARNING,
                category=ErrorCategory.CONFIGURATION,
                user_message="There's an issue with the system configuration",
                technical_message=f"{error_type}: {error_str[:200]}",
                solutions=[
                    "Check the Configuration page for invalid settings",
                    "Verify all required fields are filled in",
                    "Reset to default configuration if needed",
                    "Review recent configuration changes"
                ],
                recovery_possible=True,
                retry_recommended=False,
                contact_support=False
            )
        return None

    @staticmethod
    def _create_generic_error(error_str: str, error_type: str, context: str) -> ErrorDetails:
        """Create a generic error when specific pattern doesn't match."""
        return ErrorDetails(
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.SYSTEM,
            user_message=f"An unexpected error occurred while {context or 'processing your request'}",
            technical_message=f"{error_type}: {error_str[:200]}",
            solutions=[
                "Try the operation again",
                "Refresh the page and retry",
                "Check the system logs for more details",
                "Contact support if the problem persists"
            ],
            recovery_possible=True,
            retry_recommended=True,
            contact_support=True
        )


def translate_error_enhanced(exception: Exception, context: str = "") -> Dict[str, Any]:
    """
    Enhanced error translation with structured output.

    Args:
        exception: The exception to translate
        context: Context about what operation was being performed

    Returns:
        Dictionary with error details
    """
    translator = EnhancedErrorTranslator()
    details = translator.translate(exception, context)

    return {
        "severity": details.severity.value,
        "category": details.category.value,
        "user_message": details.user_message,
        "technical_message": details.technical_message,
        "solutions": details.solutions,
        "recovery_possible": details.recovery_possible,
        "retry_recommended": details.retry_recommended,
        "contact_support": details.contact_support
    }
