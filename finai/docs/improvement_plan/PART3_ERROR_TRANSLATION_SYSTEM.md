# PRODUCTION-GRADE IMPROVEMENT PLAN - PART 3
## Error Translation & User-Friendly Messaging System

**Document Version:** 1.0
**Last Updated:** December 2024
**Prerequisite Reading:** Parts 1-2

---

## TABLE OF CONTENTS

1. [Error Translation Philosophy](#error-translation-philosophy)
2. [Error Message Structure](#error-message-structure)
3. [Common Error Scenarios](#common-error-scenarios)
4. [Implementation Guide](#implementation-guide)
5. [Testing Error Messages](#testing-error-messages)

---

## ERROR TRANSLATION PHILOSOPHY

### Core Principles

1. **Assume Zero Technical Knowledge**: User may not know what Python, API, or even "backend" means
2. **Explain Impact First**: What does this mean for their work?
3. **Provide Actionable Solutions**: What can they do right now?
4. **Progressive Disclosure**: Show simple explanation first, technical details on request
5. **Empathetic Tone**: Acknowledge frustration, don't blame user

### Bad vs Good Error Messages

#### ❌ BAD (Technical)
```
AssertionError: Batch size mismatch: expected 16, got 12
File "hgt.py", line 143, in forward
  assert B == batch_size, f"Batch size mismatch: expected {batch_size}, got {B}"
Traceback (most recent call last):
  ...stack trace...
```

**Problems:**
- Assumes user knows what "batch size" and "assertion" mean
- Shows file paths and code line numbers
- No explanation of why this happened
- No guidance on how to fix
- Blames the system, not helpful

#### ✅ GOOD (User-Friendly)
```
⚠️ DATA PREPARATION ISSUE

What happened:
The system tried to prepare 12 data samples for training, but was
configured to expect exactly 16 samples at a time.

Why this matters:
Training cannot continue because the model requires consistent
batch sizes to learn effectively. This is like trying to fill a
container designed for 16 items with only 12 items - it doesn't fit.

Why it happened:
Some assets don't have enough historical data (at least 30 days).
When these assets were filtered out, we ended up with fewer samples
than expected.

What you can do:
✓ Recommended: Let the system automatically adjust batch size to 12
  [Fix Automatically]

○ Remove assets with insufficient data (23 assets would be removed)
  [View Affected Assets] [Apply This Fix]

○ Change configuration to require more historical data
  [Configure Settings]

Need help? [Contact Support] [View Documentation]
```

**Why this is better:**
- Plain English, no jargon
- Explains impact on user's work
- Uses analogy (container analogy)
- Explains root cause
- Provides 3 concrete solutions
- Default recommendation highlighted
- Support options available

---

## ERROR MESSAGE STRUCTURE

### Standard Error Object Schema

```typescript
interface UserFriendlyError {
  // Basic Info
  severity: "info" | "warning" | "error" | "critical";
  title: string;  // Short (5-10 words)
  category: ErrorCategory;
  timestamp: Date;

  // User-Facing Content
  plainEnglish: {
    what: string;      // What happened (1-2 sentences)
    impact: string;    // Why this matters to user (1-2 sentences)
    why: string;       // Root cause explanation (2-4 sentences)
    analogy?: string;  // Optional real-world analogy
  };

  // Solutions
  solutions: Array<{
    label: string;        // Short description (5-10 words)
    description: string;  // Detailed explanation (1-2 sentences)
    action: ActionType;   // How system should respond
    params?: object;      // Action parameters
    recommended?: boolean;  // Is this the suggested fix?
    warning?: string;     // Potential downside of this solution
  }>;

  // Context (for debugging)
  context: {
    component: string;   // Which part of system failed
    operation: string;   // What operation was being performed
    affectedAssets?: string[];  // Which assets were involved
    configuration?: object;     // Relevant config settings
  };

  // Technical Details (collapsible)
  technical: {
    exceptionType: string;
    exceptionMessage: string;
    stackTrace: string;
    systemState: object;  // Memory, CPU, etc. at time of error
  };

  // Help Resources
  help: {
    documentation?: string;  // Link to relevant docs
    supportEmail?: string;
    similarIssues?: string[];  // Links to similar reported issues
  };
}

enum ErrorCategory {
  DATA_SOURCE = "Data Source Issue",
  CONFIGURATION = "Configuration Problem",
  RESOURCE = "System Resource Issue",
  MODEL = "Model Training/Prediction Issue",
  NETWORK = "Network/Connectivity Issue",
  AUTHENTICATION = "Authentication/Permission Issue",
  DATA_QUALITY = "Data Quality Issue",
  UNKNOWN = "Unexpected Error"
}

enum ActionType {
  UPDATE_CONFIG = "update_config",        // Modify configuration setting
  DISABLE_SOURCE = "disable_source",      // Disable a data source
  FILTER_ASSETS = "filter_assets",        // Remove problematic assets
  RETRY = "retry",                        // Try operation again
  WAIT = "wait",                          // Wait and retry later
  CONTACT_SUPPORT = "contact_support",    // Escalate to human support
  VIEW_DETAILS = "view_details",          // Show more information
  DOWNLOAD_LOGS = "download_logs",        // Download diagnostic logs
  UI_REDIRECT = "ui_redirect",            // Navigate to config screen
  CUSTOM_SCRIPT = "custom_script"         // Run automated fix script
}
```

### Example: Complete Error Object

```json
{
  "severity": "error",
  "title": "Stock Price Download Failed",
  "category": "DATA_SOURCE",
  "timestamp": "2024-12-15T14:32:18Z",

  "plainEnglish": {
    "what": "The system could not download stock price data from Yahoo Finance for 23 assets.",
    "impact": "Liquidity predictions for these 23 stocks will be unavailable or based on outdated data. This represents 15% of your monitored assets.",
    "why": "Yahoo Finance is limiting how fast we can download data. We exceeded their maximum request limit of 2000 per hour. This typically happens when monitoring too many assets or downloading too frequently.",
    "analogy": "Think of it like a library that only allows you to check out 10 books per day. If you try to take 20, they'll stop you at 10."
  },

  "solutions": [
    {
      "label": "Wait 30 minutes and retry automatically",
      "description": "The system will wait until Yahoo Finance's rate limit resets, then automatically retry the download.",
      "action": "WAIT",
      "params": {"delay_minutes": 30, "auto_retry": true},
      "recommended": true
    },
    {
      "label": "Reduce download frequency",
      "description": "Change from every 15 minutes to every 30 minutes. This will stay within rate limits but predictions will update less frequently.",
      "action": "UPDATE_CONFIG",
      "params": {"data.update_frequency": 30},
      "warning": "Predictions will be 15 minutes less current"
    },
    {
      "label": "Split downloads across multiple time periods",
      "description": "Download different asset groups at different times of day to spread out requests.",
      "action": "UI_REDIRECT",
      "params": {"module": "scheduler", "task": "stagger_downloads"}
    }
  ],

  "context": {
    "component": "DataCollector",
    "operation": "download_asset_data",
    "affectedAssets": ["JPM", "BAC", "WFC", ...],
    "configuration": {
      "batch_size": 20,
      "rate_limit": 2000,
      "update_frequency": 15
    }
  },

  "technical": {
    "exceptionType": "RateLimitError",
    "exceptionMessage": "429 Too Many Requests: Rate limit exceeded for Yahoo Finance API",
    "stackTrace": "...",
    "systemState": {
      "memory_usage_mb": 4823,
      "cpu_usage_percent": 45,
      "active_downloads": 8
    }
  },

  "help": {
    "documentation": "https://docs.example.com/data-sources/rate-limits",
    "supportEmail": "support@example.com",
    "similarIssues": [
      "https://github.com/project/issues/123",
      "https://community.example.com/rate-limit-solutions"
    ]
  }
}
```

---

## COMMON ERROR SCENARIOS

### 1. API Authentication Errors

```python
{
  "severity": "error",
  "title": "Cannot Access Economic Data",
  "category": "AUTHENTICATION",

  "plainEnglish": {
    "what": "The system cannot connect to the Federal Reserve Economic Data (FRED) service.",
    "impact": "Economic indicators like GDP, unemployment rate, and interest rates will not be available. Liquidity predictions will be less accurate without this context.",
    "why": "Your FRED API key is either invalid, expired, or wasn't entered correctly. API keys are like passwords - they must match exactly.",
    "analogy": "It's like trying to enter a building with an expired access card. The door won't open even if you have the card."
  },

  "solutions": [
    {
      "label": "Check and update API key",
      "description": "The API key might have typos or be expired. We'll help you verify and update it.",
      "action": "UI_REDIRECT",
      "params": {"module": "data_sources", "source_id": "fred_1"},
      "recommended": true
    },
    {
      "label": "Generate a new API key",
      "description": "Create a fresh API key from FRED's website. It's free and takes 2 minutes.",
      "action": "VIEW_DETAILS",
      "params": {"guide": "fred_api_key_registration"}
    },
    {
      "label": "Continue without economic data",
      "description": "Disable FRED temporarily and use only stock price data for predictions.",
      "action": "DISABLE_SOURCE",
      "params": {"source_id": "fred_1"},
      "warning": "Predictions may be 15-20% less accurate without economic context"
    }
  ]
}
```

### 2. Memory/Resource Errors

```python
{
  "severity": "critical",
  "title": "System Running Out of Memory",
  "category": "RESOURCE",

  "plainEnglish": {
    "what": "The computer doesn't have enough memory (RAM) to complete model training.",
    "impact": "Training stopped at 34% completion. The model cannot learn from data until this is fixed. Predictions are using the old model from 3 days ago.",
    "why": "You're training on 150 assets with 30-day history, which requires about 14 GB of memory. Your system only has 12 GB available. Modern ML models need substantial memory to process large datasets.",
    "analogy": "Imagine trying to solve a 1000-piece puzzle on a table that can only fit 500 pieces. You need more space to work."
  },

  "solutions": [
    {
      "label": "Reduce batch size from 16 to 8",
      "description": "Process fewer assets at once. Training will take 2x longer but will succeed.",
      "action": "UPDATE_CONFIG",
      "params": {"model.batch_size": 8},
      "recommended": true
    },
    {
      "label": "Monitor fewer assets (reduce from 150 to 100)",
      "description": "Remove less critical assets to free up memory. We'll suggest which ones based on importance.",
      "action": "UI_REDIRECT",
      "params": {"module": "asset_manager", "action": "suggest_removal"}
    },
    {
      "label": "Upgrade to a machine with more RAM",
      "description": "For best results, use a computer with at least 16 GB RAM when monitoring 150+ assets.",
      "action": "VIEW_DETAILS",
      "params": {"guide": "system_requirements"}
    },
    {
      "label": "Use cloud resources temporarily",
      "description": "Rent a cloud machine with more RAM for $1-2/hour to complete training.",
      "action": "VIEW_DETAILS",
      "params": {"guide": "cloud_deployment"}
    }
  ]
}
```

### 3. Data Quality Errors

```python
{
  "severity": "warning",
  "title": "Missing Data Detected",
  "category": "DATA_QUALITY",

  "plainEnglish": {
    "what": "45 assets have gaps in their price history. Some dates are missing data.",
    "impact": "Predictions for these 45 assets may be less reliable. The model will try to fill gaps automatically, but accuracy could drop by 5-10%.",
    "why": "This usually happens when: (1) Markets were closed (holidays/weekends), (2) Trading was halted, or (3) The stock was delisted. Some international markets have different trading calendars.",
    "analogy": "It's like trying to follow a recipe with some steps missing. You can guess what goes in between, but it might not turn out exactly right."
  },

  "solutions": [
    {
      "label": "Fill gaps automatically using interpolation",
      "description": "The system will estimate missing values based on surrounding data. Works well for small gaps (1-3 days).",
      "action": "UPDATE_CONFIG",
      "params": {"data.fill_method": "interpolation"},
      "recommended": true
    },
    {
      "label": "Remove assets with >10% missing data (8 assets)",
      "description": "Exclude heavily incomplete data to maintain prediction quality.",
      "action": "FILTER_ASSETS",
      "params": {"max_missing_percent": 10}
    },
    {
      "label": "Download from alternative source",
      "description": "Try Alpha Vantage or IEX Cloud for better data coverage.",
      "action": "VIEW_DETAILS",
      "params": {"guide": "alternative_data_sources"}
    },
    {
      "label": "Accept lower accuracy and continue",
      "description": "Proceed with current data quality. Predictions will still be useful but less precise.",
      "action": "RETRY",
      "params": {"ignore_warnings": true}
    }
  ]
}
```

### 4. Configuration Errors

```python
{
  "severity": "error",
  "title": "Invalid Training Settings",
  "category": "CONFIGURATION",

  "plainEnglish": {
    "what": "The model training settings contain conflicting or impossible values.",
    "impact": "Training cannot start until these settings are fixed. Predictions are still using the model from yesterday.",
    "why": "You set 'look_back_days' to 60, but 'min_data_points' to 30. The system needs at least 60 days of history per asset to create 60-day look-back sequences, but is told to accept assets with only 30 days.",
    "analogy": "It's like setting a washing machine to '60-minute wash' but also setting a timer that stops it at 30 minutes. The instructions contradict each other."
  },

  "solutions": [
    {
      "label": "Set min_data_points to match look_back_days (60)",
      "description": "Require all assets to have at least 60 days of history. This ensures consistent training data.",
      "action": "UPDATE_CONFIG",
      "params": {"data.min_data_points": 60},
      "recommended": true,
      "warning": "17 assets will be excluded due to insufficient history"
    },
    {
      "label": "Reduce look_back_days to 30",
      "description": "Use shorter historical windows. Model will be less context-aware but can include all assets.",
      "action": "UPDATE_CONFIG",
      "params": {"data.look_back_days": 30}
    },
    {
      "label": "Review all settings in configuration panel",
      "description": "Manually check all settings for conflicts or issues.",
      "action": "UI_REDIRECT",
      "params": {"module": "configuration", "section": "model"}
    }
  ]
}
```

### 5. Network/Connectivity Errors

```python
{
  "severity": "error",
  "title": "Cannot Connect to Data Source",
  "category": "NETWORK",

  "plainEnglish": {
    "what": "The system cannot reach Yahoo Finance to download stock prices.",
    "impact": "No new price data is being collected. Predictions are based on data from 6 hours ago and getting stale.",
    "why": "This could be: (1) Your internet connection is down, (2) Yahoo Finance is experiencing an outage, (3) A firewall is blocking access. Network problems are usually temporary.",
    "analogy": "Like trying to call someone whose phone is off. You'll need to try again when the connection is available."
  },

  "solutions": [
    {
      "label": "Retry connection now",
      "description": "Test if the connection is working again. Network issues often resolve on their own.",
      "action": "RETRY",
      "params": {"max_retries": 3, "delay_seconds": 10},
      "recommended": true
    },
    {
      "label": "Check internet connection",
      "description": "Open a web browser and try accessing finance.yahoo.com to verify connectivity.",
      "action": "VIEW_DETAILS",
      "params": {"url": "https://finance.yahoo.com"}
    },
    {
      "label": "Use cached data for now",
      "description": "Continue with last successfully downloaded data while waiting for connection to restore.",
      "action": "UPDATE_CONFIG",
      "params": {"data.use_cached_on_failure": true},
      "warning": "Predictions will use data up to 6 hours old"
    },
    {
      "label": "Check Yahoo Finance status",
      "description": "See if Yahoo Finance is reporting system-wide outages.",
      "action": "VIEW_DETAILS",
      "params": {"url": "https://status.yahoo.com"}
    }
  ]
}
```

---

## IMPLEMENTATION GUIDE

### Step 1: Create Error Translator Service

```python
# src/liquidity_monitor/utils/error_translator.py

from typing import Dict, Any, Optional
from enum import Enum
import re
import traceback

class ErrorSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class ErrorCategory(Enum):
    DATA_SOURCE = "Data Source Issue"
    CONFIGURATION = "Configuration Problem"
    RESOURCE = "System Resource Issue"
    MODEL = "Model Training/Prediction Issue"
    NETWORK = "Network/Connectivity Issue"
    AUTHENTICATION = "Authentication/Permission Issue"
    DATA_QUALITY = "Data Quality Issue"
    UNKNOWN = "Unexpected Error"

class ErrorTranslator:
    """
    Translates technical exceptions to user-friendly messages.

    Usage:
        try:
            risky_operation()
        except Exception as e:
            translator = ErrorTranslator()
            user_error = translator.translate(
                exception=e,
                context={"operation": "data_collection", "assets": ["JPM", "BAC"]}
            )
            return user_error
    """

    def __init__(self):
        # Load error patterns from configuration or database
        self.patterns = self._load_error_patterns()

    def translate(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Translate exception to user-friendly error object.

        Args:
            exception: The exception that was raised
            context: Additional context (operation, assets, config, etc.)

        Returns:
            User-friendly error dictionary
        """
        context = context or {}

        # Match exception to known pattern
        pattern = self._match_pattern(exception)

        if pattern:
            return self._build_error_from_pattern(exception, pattern, context)
        else:
            return self._build_generic_error(exception, context)

    def _match_pattern(self, exception: Exception) -> Optional[Dict]:
        """Match exception to known error pattern."""
        exc_type = type(exception).__name__
        exc_message = str(exception).lower()

        for pattern_name, pattern_config in self.patterns.items():
            # Check if exception type matches
            if pattern_config.get("exception_types"):
                if exc_type not in pattern_config["exception_types"]:
                    continue

            # Check if message matches regex
            if pattern_config.get("message_regex"):
                if not re.search(pattern_config["message_regex"], exc_message, re.IGNORECASE):
                    continue

            # Match found
            return pattern_config

        return None

    def _build_error_from_pattern(
        self,
        exception: Exception,
        pattern: Dict,
        context: Dict
    ) -> Dict[str, Any]:
        """Build user-friendly error from pattern template."""

        # Fill in template variables
        variables = {
            **context,
            "exception_message": str(exception),
            "exception_type": type(exception).__name__
        }

        # Format strings with variables
        plain_english = {
            key: value.format(**variables)
            for key, value in pattern["plain_english"].items()
        }

        solutions = [
            {
                **solution,
                "label": solution["label"].format(**variables),
                "description": solution["description"].format(**variables)
            }
            for solution in pattern["solutions"]
        ]

        return {
            "severity": pattern["severity"],
            "title": pattern["title"].format(**variables),
            "category": pattern["category"],
            "plainEnglish": plain_english,
            "solutions": solutions,
            "context": context,
            "technical": {
                "exceptionType": type(exception).__name__,
                "exceptionMessage": str(exception),
                "stackTrace": traceback.format_exc()
            },
            "help": pattern.get("help", {})
        }

    def _build_generic_error(
        self,
        exception: Exception,
        context: Dict
    ) -> Dict[str, Any]:
        """Build generic error for unknown exception types."""
        return {
            "severity": ErrorSeverity.ERROR.value,
            "title": "Unexpected System Error",
            "category": ErrorCategory.UNKNOWN.value,
            "plainEnglish": {
                "what": "Something unexpected went wrong that the system hasn't seen before.",
                "impact": "The current operation could not complete. Your data and previous work are safe.",
                "why": "This is a new type of error. It might be a bug in the software or an unusual situation.",
                "analogy": None
            },
            "solutions": [
                {
                    "label": "Try the operation again",
                    "description": "Sometimes errors are temporary. Trying again may work.",
                    "action": "RETRY",
                    "recommended": True
                },
                {
                    "label": "Contact support with error details",
                    "description": "Our team can investigate this specific error and provide a fix.",
                    "action": "CONTACT_SUPPORT"
                },
                {
                    "label": "View technical details",
                    "description": "See the full error message (for technical users).",
                    "action": "VIEW_DETAILS"
                }
            ],
            "context": context,
            "technical": {
                "exceptionType": type(exception).__name__,
                "exceptionMessage": str(exception),
                "stackTrace": traceback.format_exc()
            },
            "help": {
                "supportEmail": "support@example.com"
            }
        }

    def _load_error_patterns(self) -> Dict[str, Dict]:
        """
        Load error patterns from configuration.

        In production, this would load from database or YAML files.
        Patterns can be added/updated by administrators without code changes.
        """
        return {
            "rate_limit_yfinance": {
                "exception_types": ["RateLimitError", "ConnectionError", "HTTPError"],
                "message_regex": r"(rate limit|429|too many requests)",
                "severity": ErrorSeverity.WARNING.value,
                "title": "Download Limit Reached",
                "category": ErrorCategory.DATA_SOURCE.value,
                "plain_english": {
                    "what": "Yahoo Finance is limiting how fast we can download data. We exceeded their maximum request limit.",
                    "impact": "Data collection for {affected_asset_count} assets is incomplete. Predictions for these assets will be skipped or use older data.",
                    "why": "Yahoo Finance allows ~2000 requests per hour. You're monitoring {total_asset_count} assets, which exceeded this limit when downloading every {update_frequency} minutes.",
                    "analogy": "Think of it like a library that only lets you check out 10 books per day. If you try to take 20, they'll stop you at 10."
                },
                "solutions": [
                    {
                        "label": "Wait {wait_time} minutes and retry automatically",
                        "description": "The system will pause until the rate limit resets, then automatically continue.",
                        "action": "WAIT",
                        "params": {"delay_minutes": 30, "auto_retry": True},
                        "recommended": True
                    },
                    {
                        "label": "Increase update frequency to {recommended_frequency} minutes",
                        "description": "Download less frequently to stay within rate limits.",
                        "action": "UPDATE_CONFIG",
                        "params": {"data.update_frequency": 30}
                    },
                    {
                        "label": "Reduce monitored assets to {recommended_asset_count}",
                        "description": "Monitor fewer assets to reduce API usage.",
                        "action": "UI_REDIRECT",
                        "params": {"module": "asset_manager"}
                    }
                ],
                "help": {
                    "documentation": "https://docs.example.com/data-sources/rate-limits"
                }
            },

            "memory_error": {
                "exception_types": ["MemoryError", "RuntimeError"],
                "message_regex": r"(out of memory|cannot allocate|memory|OOM)",
                "severity": ErrorSeverity.CRITICAL.value,
                "title": "System Running Out of Memory",
                "category": ErrorCategory.RESOURCE.value,
                "plain_english": {
                    "what": "The computer doesn't have enough memory (RAM) to complete this operation.",
                    "impact": "{operation} stopped at {progress_percent}% completion. Results are incomplete.",
                    "why": "You're processing {asset_count} assets with {look_back} days of history, which requires approximately {required_gb} GB of memory. Your system only has {available_gb} GB available.",
                    "analogy": "Imagine trying to solve a 1000-piece puzzle on a table that can only fit 500 pieces. You need more space to work."
                },
                "solutions": [
                    {
                        "label": "Reduce batch size from {current_batch_size} to {recommended_batch_size}",
                        "description": "Process fewer assets at once. Training will take longer but will succeed.",
                        "action": "UPDATE_CONFIG",
                        "params": {"model.batch_size": "auto"},
                        "recommended": True
                    },
                    {
                        "label": "Reduce look-back period from {current_look_back} to {recommended_look_back} days",
                        "description": "Use less historical data per asset to reduce memory usage.",
                        "action": "UPDATE_CONFIG",
                        "params": {"data.look_back": "auto"}
                    },
                    {
                        "label": "Monitor fewer assets",
                        "description": "Remove less critical assets to free up memory.",
                        "action": "UI_REDIRECT",
                        "params": {"module": "asset_manager"}
                    }
                ],
                "help": {
                    "documentation": "https://docs.example.com/troubleshooting/memory-issues"
                }
            },

            "api_authentication": {
                "exception_types": ["AuthenticationError", "PermissionError", "HTTPError"],
                "message_regex": r"(api key|authentication|unauthorized|401|403)",
                "severity": ErrorSeverity.ERROR.value,
                "title": "Cannot Access Data Source",
                "category": ErrorCategory.AUTHENTICATION.value,
                "plain_english": {
                    "what": "The system cannot connect to {source_name} because of an authentication problem.",
                    "impact": "Data from {source_name} is not available. Predictions will be less accurate without this data.",
                    "why": "Your API key for {source_name} is invalid, expired, or wasn't entered correctly. API keys are like passwords - they must match exactly.",
                    "analogy": "It's like trying to enter a building with an expired access card. The door won't open even if you have the card."
                },
                "solutions": [
                    {
                        "label": "Check and update API key",
                        "description": "Verify the API key is entered correctly without extra spaces or characters.",
                        "action": "UI_REDIRECT",
                        "params": {"module": "data_sources", "source_id": "{source_id}"},
                        "recommended": True
                    },
                    {
                        "label": "Generate a new API key",
                        "description": "Create a fresh API key from {source_name}'s website.",
                        "action": "VIEW_DETAILS",
                        "params": {"guide": "{source_name}_api_key"}
                    },
                    {
                        "label": "Disable this data source temporarily",
                        "description": "Continue without {source_name} data. System will use other available sources.",
                        "action": "DISABLE_SOURCE",
                        "params": {"source_id": "{source_id}"},
                        "warning": "Predictions may be less accurate"
                    }
                ],
                "help": {
                    "documentation": "https://docs.example.com/data-sources/{source_name}"
                }
            }

            # Add more patterns...
        }
```

### Step 2: Integrate with Exception Handling

```python
# src/liquidity_monitor/data/collection.py

from ..utils.error_translator import ErrorTranslator
from ..utils.logger import get_logger

logger = get_logger(__name__)
translator = ErrorTranslator()

def download_asset_data(assets, start_date, end_date):
    """Download asset data with user-friendly error handling."""
    try:
        # Attempt download
        data = yfinance_download(assets, start_date, end_date)
        return {"success": True, "data": data}

    except Exception as e:
        # Translate to user-friendly error
        user_error = translator.translate(
            exception=e,
            context={
                "operation": "download_asset_data",
                "component": "DataCollector",
                "affected_assets": assets,
                "total_asset_count": len(assets),
                "update_frequency": get_config("data.update_frequency"),
                "source_name": "Yahoo Finance",
                "source_id": "yfinance_1"
            }
        )

        # Log technical details for debugging
        logger.error(
            f"Data collection failed: {e}",
            extra=user_error["technical"]
        )

        # Return user-friendly error
        return {
            "success": False,
            "error": user_error
        }
```

### Step 3: Display in UI

```javascript
// frontend/src/components/ErrorDisplay.jsx

import React from 'react';
import { Alert, Button, Collapse, Typography } from '@mui/material';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import WarningIcon from '@mui/icons-material/Warning';
import InfoIcon from '@mui/icons-material/Info';

function ErrorDisplay({ error }) {
  const [showTechnical, setShowTechnical] = React.useState(false);

  const severityIcons = {
    critical: <ErrorOutlineIcon color="error" />,
    error: <ErrorOutlineIcon color="error" />,
    warning: <WarningIcon color="warning" />,
    info: <InfoIcon color="info" />
  };

  return (
    <Alert
      severity={error.severity}
      icon={severityIcons[error.severity]}
      sx={{ mb: 2 }}
    >
      <Typography variant="h6" gutterBottom>
        {error.title}
      </Typography>

      {/* What happened */}
      <Typography variant="body1" paragraph>
        <strong>What happened:</strong><br />
        {error.plainEnglish.what}
      </Typography>

      {/* Impact */}
      <Typography variant="body1" paragraph>
        <strong>Why this matters:</strong><br />
        {error.plainEnglish.impact}
      </Typography>

      {/* Why it happened */}
      <Typography variant="body1" paragraph>
        <strong>Why it happened:</strong><br />
        {error.plainEnglish.why}
      </Typography>

      {/* Analogy (if available) */}
      {error.plainEnglish.analogy && (
        <Typography variant="body2" paragraph sx={{ fontStyle: 'italic' }}>
          {error.plainEnglish.analogy}
        </Typography>
      )}

      {/* Solutions */}
      <Typography variant="h6" gutterBottom sx={{ mt: 2 }}>
        What you can do:
      </Typography>

      {error.solutions.map((solution, index) => (
        <SolutionButton
          key={index}
          solution={solution}
          isRecommended={solution.recommended}
        />
      ))}

      {/* Technical details (collapsible) */}
      <Button
        size="small"
        onClick={() => setShowTechnical(!showTechnical)}
        sx={{ mt: 2 }}
      >
        {showTechnical ? 'Hide' : 'Show'} Technical Details
      </Button>

      <Collapse in={showTechnical}>
        <Typography variant="body2" sx={{ mt: 2, fontFamily: 'monospace' }}>
          <strong>Exception:</strong> {error.technical.exceptionType}<br />
          <strong>Message:</strong> {error.technical.exceptionMessage}<br />
          <strong>Stack Trace:</strong><br />
          <pre style={{ fontSize: '0.8em', overflow: 'auto' }}>
            {error.technical.stackTrace}
          </pre>
        </Typography>
      </Collapse>

      {/* Help resources */}
      {error.help && (
        <Typography variant="body2" sx={{ mt: 2 }}>
          <strong>Need help?</strong>{' '}
          {error.help.documentation && (
            <a href={error.help.documentation} target="_blank" rel="noopener">
              View Documentation
            </a>
          )}
          {error.help.supportEmail && (
            <> | <a href={`mailto:${error.help.supportEmail}`}>Contact Support</a></>
          )}
        </Typography>
      )}
    </Alert>
  );
}

function SolutionButton({ solution, isRecommended }) {
  const handleAction = async () => {
    // Call API to execute solution action
    await fetch(`/api/actions/${solution.action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(solution.params || {})
    });
  };

  return (
    <div style={{ marginBottom: '12px' }}>
      <Button
        variant={isRecommended ? 'contained' : 'outlined'}
        color={isRecommended ? 'primary' : 'default'}
        onClick={handleAction}
        startIcon={isRecommended ? '✓' : '○'}
      >
        {solution.label}
      </Button>
      <Typography variant="body2" sx={{ mt: 0.5, ml: 1 }}>
        {solution.description}
      </Typography>
      {solution.warning && (
        <Typography variant="caption" color="warning.main" sx={{ ml: 1 }}>
          ⚠ {solution.warning}
        </Typography>
      )}
    </div>
  );
}

export default ErrorDisplay;
```

---

## TESTING ERROR MESSAGES

### Test Checklist

For each error message, verify:

**Clarity**:
- [ ] Can a non-technical person understand what happened?
- [ ] Is the explanation jargon-free?
- [ ] Is the impact on their work clear?

**Actionability**:
- [ ] Are there at least 2-3 concrete solutions?
- [ ] Is one solution marked as recommended?
- [ ] Can solutions be executed from the UI (no command line needed)?

**Completeness**:
- [ ] Is the root cause explained (not just symptoms)?
- [ ] Are potential consequences mentioned?
- [ ] Are help resources provided?

**Tone**:
- [ ] Is the message empathetic (not blaming)?
- [ ] Is it reassuring (data is safe, temporary issue, etc.)?
- [ ] Is it professional (appropriate for regulators)?

### User Testing Script

```
Scenario: Test user-friendliness of error messages

Setup:
1. Recruit 3-5 non-technical users (e.g., business analysts, managers)
2. Give them access to test system
3. Trigger various errors deliberately

Test Cases:
1. Invalid API key → Show authentication error
2. Rate limit exceeded → Show rate limit error
3. Out of memory → Show resource error
4. Missing data → Show data quality warning

For Each Error, Ask:
1. What do you think happened? (Test understanding)
2. What would you do next? (Test actionability)
3. How concerned are you? (Test severity communication)
4. Is anything confusing? (Test clarity)
5. What would make this message better? (Open feedback)

Success Criteria:
- 80%+ users correctly understand what happened
- 80%+ users can identify at least one solution
- No users need to contact support for clarification
```

---

**END OF PART 3**

## NEXT SECTIONS

- **Part 4**: Resource Optimization Strategies
- **Part 5**: Implementation Roadmap (Phases, Timeline, Priorities)
- **Part 6**: Deployment Architecture (Docker, Scaling, Monitoring)
- **Part 7**: Maintenance and Operations Guide
