# Priority 3 Features Documentation

This document provides comprehensive documentation for the Priority 3 features implemented in the BEACON platform.

## Table of Contents

1. [Notification System](#notification-system)
2. [Model Performance Dashboard](#model-performance-dashboard)
3. [Data Quality Monitoring Dashboard](#data-quality-monitoring-dashboard)

---

## Notification System

### Overview

The Notification System provides real-time alerts and updates for important events across the BEACON platform, including job completions, errors, data quality issues, and system alerts.

### Features

- **Real-time notifications** with automatic polling every 30 seconds
- **Categorized notifications** by type (info, success, warning, error, alert)
- **Priority levels** (low, medium, high, urgent)
- **Action URLs** for direct navigation to relevant pages
- **Mark as read/unread** functionality
- **Batch operations** (mark all as read)
- **Notification bell** with unread count badge in header
- **Auto-expiration** support for time-sensitive notifications

### Backend API

**Base Endpoint:** `/api/v1/notifications`

#### Endpoints

##### 1. List Notifications
```http
GET /api/v1/notifications
```

**Query Parameters:**
- `unread_only` (boolean, default: false) - Filter to show only unread notifications
- `category` (string, optional) - Filter by category (job, data_quality, risk, system, pipeline)
- `priority` (string, optional) - Filter by priority (low, medium, high, urgent)
- `limit` (integer, default: 50) - Maximum number of results
- `offset` (integer, default: 0) - Pagination offset

**Response:**
```json
{
  "notifications": [
    {
      "id": 1,
      "title": "Data Ingestion Completed",
      "message": "Successfully ingested 1,234 records from FDIC source",
      "notification_type": "success",
      "priority": "low",
      "category": "job",
      "is_urgent": false,
      "is_read": false,
      "is_dismissed": false,
      "action_url": "/jobs/123",
      "action_label": "View Job",
      "created_at": "2025-11-07T10:30:00Z",
      "metadata": {}
    }
  ],
  "total_count": 42,
  "unread_count": 5
}
```

##### 2. Get Notification Stats
```http
GET /api/v1/notifications/stats
```

**Response:**
```json
{
  "total_count": 42,
  "unread_count": 5,
  "by_category": {
    "job": 20,
    "data_quality": 10,
    "risk": 8,
    "system": 4
  },
  "by_priority": {
    "low": 30,
    "medium": 8,
    "high": 3,
    "urgent": 1
  },
  "urgent_unread": 1
}
```

##### 3. Mark Notification as Read
```http
POST /api/v1/notifications/{notification_id}/read
```

##### 4. Mark All as Read
```http
POST /api/v1/notifications/read-all?category=job
```

**Query Parameters:**
- `category` (string, optional) - Only mark notifications from this category as read

##### 5. Dismiss Notification
```http
POST /api/v1/notifications/{notification_id}/dismiss
```

##### 6. Delete Notification
```http
DELETE /api/v1/notifications/{notification_id}
```

### Frontend Integration

#### React Hooks

**File:** `frontend/src/hooks/useNotifications.js`

Available hooks:
- `useNotifications(filters)` - Fetch notifications list
- `useNotificationStats()` - Get notification statistics
- `useNotification(id)` - Get single notification
- `useCreateNotification()` - Create new notification
- `useMarkNotificationAsRead()` - Mark as read mutation
- `useMarkAllAsRead()` - Mark all as read mutation
- `useDismissNotification()` - Dismiss mutation
- `useDeleteNotification()` - Delete mutation

Example usage:
```javascript
import { useNotifications, useMarkNotificationAsRead } from '../hooks/useNotifications'

function MyComponent() {
  const { data, isLoading } = useNotifications({ unread_only: true, limit: 20 })
  const markAsReadMutation = useMarkNotificationAsRead()

  const handleMarkAsRead = (id) => {
    markAsReadMutation.mutate(id)
  }

  // ...
}
```

#### UI Component

**Component:** `NotificationBell` (frontend/src/components/NotificationBell.jsx)

The NotificationBell component is integrated into the Header and provides:
- Dropdown notification panel
- Unread count badge
- Time formatting (e.g., "5m ago", "2h ago")
- Icon variations by notification type
- Click to mark as read and navigate
- "Mark all read" button

### Notification Types

| Type | Color | Use Case |
|------|-------|----------|
| `info` | Blue | General information |
| `success` | Green | Successful operations |
| `warning` | Yellow | Warnings requiring attention |
| `error` | Red | Failed operations |
| `alert` | Red (animated) | Critical alerts requiring immediate action |

### Creating Notifications

#### From Backend Services

```python
from backend.services.notification_service import NotificationService
from backend.schemas.notification import NotificationCreate

service = NotificationService(db)

# Create job completion notification
service.create_job_notification(
    job_id=123,
    job_status='completed',
    job_type='data_ingestion'
)

# Create custom notification
notification = service.create_notification(NotificationCreate(
    title="Custom Alert",
    message="Something important happened",
    notification_type="warning",
    priority="high",
    category="system",
    is_urgent=True,
    action_url="/settings",
    action_label="Check Settings"
))
```

#### Helper Methods

The NotificationService provides convenience methods:
- `create_job_notification()` - For job status updates
- `create_risk_alert()` - For risk threshold breaches
- `create_data_quality_alert()` - For data quality issues

---

## Model Performance Dashboard

### Overview

The Model Performance Dashboard provides a centralized view of all machine learning models, their performance metrics, health status, and comparative analysis.

### Access

**URL:** `/performance` (accessible from sidebar navigation)

### Features

#### 1. Summary Metrics

Four key metric cards at the top:
- **Total Models** - Count of all models in the system
- **Average R² Score** - Mean R² across ready models
- **Average RMSE** - Mean RMSE (lower is better)
- **Best Performer** - Name and score of top model

#### 2. Performance Comparison Chart

Visual bar chart showing:
- Top 8 models by R² score
- Horizontal bars with gradient styling
- Both R² and RMSE values displayed
- Quick visual comparison of model performance

#### 3. Model Health Indicators

Color-coded status breakdown:
- **Ready** (Green) - Models ready for production
- **Training** (Blue) - Models currently training
- **Stale** (Yellow) - Models >30 days since training
- **Failed** (Red) - Models with training errors
- **Overall Health %** - Percentage of healthy models

Health calculation:
```javascript
const totalHealth = ((ready / totalModels) * 100).toFixed(0)
```

Color coding:
- Green: ≥80% health
- Yellow: 50-79% health
- Red: <50% health

#### 4. Model Comparison Table

Sortable table with columns:
- **Model Name**
- **Status** (badge: ready/training/failed/draft)
- **R² Score** (sortable)
- **RMSE** (sortable)
- **MAE** (sortable)
- **Last Trained** (sortable)
- **Actions** (View Details button)

**Sorting:**
- Click column headers to sort
- Toggle ascending/descending order
- Visual arrow indicators

### Data Source

The dashboard uses the Models API endpoint:

```http
GET /api/v1/models
```

Response includes:
- `model_id` - Unique identifier
- `name` - Model name
- `status` - ready/training/failed/draft
- `accuracy` or `result.test_r2` - R² score
- `result.test_rmse` - Root Mean Square Error
- `result.test_mae` - Mean Absolute Error
- `last_trained` - Timestamp of last training
- `description` - Model description

### Usage Guidelines

1. **Monitoring Performance**: Check average R² and RMSE to ensure models meet quality thresholds
2. **Identifying Issues**: Look for stale or failed models in health indicators
3. **Comparing Models**: Use the comparison table to identify best/worst performers
4. **Retraining**: Sort by "Last Trained" to find models needing updates

---

## Data Quality Monitoring Dashboard

### Overview

The Data Quality Monitoring Dashboard provides comprehensive insights into data completeness, freshness, and quality across all data sources in the BEACON platform.

### Access

**URL:** `/data-quality` (accessible from sidebar navigation)

### Features

#### 1. Summary Metrics

Four key metric cards:
- **Overall Health** - Percentage of active/healthy sources
- **Avg Quality Score** - Mean quality score from recent jobs
- **Data Completeness** - Average completeness across sources
- **Active Issues** - Count of issues requiring attention

**Color Coding:**
- Excellent: Green (≥80%)
- Good: Blue (≥50%)
- Warning: Yellow (<50%)
- Critical: Red (errors present)

#### 2. Data Freshness Indicator

Visual progress bar showing source freshness distribution:
- **Fresh** (Green) - Updated within 7 days
- **Stale** (Yellow) - Updated 7-30 days ago
- **Outdated** (Red) - Updated >30 days ago
- **Never Synced** (Gray) - Never updated

Includes:
- Visual progress bar with color segments
- Legend with counts for each status
- Overall freshness percentage

#### 3. Anomaly Alerts

Automatic detection and alerting for:
- **Low Quality Jobs** - Jobs with quality score <50%
- **Error Sources** - Data sources in error state
- **Recent Failures** - Failed jobs in past 7 days
- **Stale Sources** - Sources not updated recently

Shows "All Clear" status when no issues detected.

#### 4. Quality Trends Chart

14-day trend visualization showing:
- Daily average quality scores
- Bar chart with color coding:
  - Green: ≥70% quality
  - Yellow: 50-69% quality
  - Red: <50% quality
- X-axis: Dates
- Y-axis: Quality score (0-100%)
- Hover for detailed values

#### 5. Source Details Table

Comprehensive table for all data sources:

| Column | Description |
|--------|-------------|
| Source | Data source name |
| Type | Plugin type (fdic, fred, yahoo, etc.) |
| Status | Active/error/disabled badge |
| Freshness | Days since update with color coding |
| Quality Score | Average from recent jobs |
| Last Updated | Date of last successful fetch |

**Sorting:**
- Automatically sorted by freshness, then quality
- Fresh sources appear first
- Error sources flagged clearly

### Backend API

**Base Endpoint:** `/api/v1/data-quality`

#### Endpoints

##### 1. Get Quality Statistics
```http
GET /api/v1/data-quality/stats
```

**Response:**
```json
{
  "overview": {
    "total_sources": 10,
    "active_sources": 8,
    "error_sources": 1,
    "disabled_sources": 1,
    "overall_health": 85.5,
    "avg_quality_score": 0.8234,
    "avg_completeness": 0.9123
  },
  "freshness": {
    "fresh": 6,
    "stale": 2,
    "outdated": 1,
    "never_synced": 1,
    "freshness_percentage": 60.0
  },
  "quality": {
    "avg_quality_score": 0.8234,
    "avg_completeness": 91.2,
    "low_quality_count": 2,
    "recent_errors": 3,
    "jobs_analyzed": 45
  },
  "anomalies": {
    "low_quality_jobs": 2,
    "error_sources": 1,
    "recent_failures": 3,
    "stale_sources": 3
  }
}
```

##### 2. Get Source Quality Details
```http
GET /api/v1/data-quality/sources
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "FDIC Bank Data",
    "plugin_type": "fdic",
    "status": "active",
    "enabled": true,
    "last_fetch": "2025-11-05T14:30:00Z",
    "days_since_update": 2,
    "freshness_status": "fresh",
    "freshness_color": "green",
    "avg_quality_score": 0.8756,
    "recent_job_count": 5,
    "error_message": null
  }
]
```

##### 3. Get Quality Trends
```http
GET /api/v1/data-quality/trends?days=30
```

**Query Parameters:**
- `days` (integer, default: 30) - Number of days to analyze

**Response:**
```json
{
  "trends": [
    {
      "date": "2025-11-01",
      "avg_quality_score": 0.8234,
      "avg_completeness": 0.9123,
      "job_count": 12,
      "error_count": 1
    }
  ],
  "summary": {
    "total_jobs": 340,
    "days_analyzed": 30,
    "start_date": "2025-10-08T00:00:00Z",
    "end_date": "2025-11-07T00:00:00Z"
  }
}
```

### Quality Score Calculation

Quality scores are calculated by the `DataAnalyzer` module using three factors:

1. **Validation Results** (40% weight)
   - Based on critical errors found during validation
   - Score = 1.0 if no critical errors, 0.0 otherwise

2. **Data Completeness** (30% weight)
   - Percentage of non-null values
   - `completeness = 1.0 - (null_count / total_count)`

3. **Cleaning Success** (30% weight)
   - Based on issues fixed during cleaning
   - `score = 1.0 / (1.0 + fixed_issues / total_rows)`

**Final Score Formula:**
```python
quality_score = (validation_score * 0.4) + (completeness * 0.3) + (cleaning_score * 0.3)
```

### Usage Guidelines

1. **Daily Monitoring**: Check Overall Health and Active Issues daily
2. **Weekly Review**: Review Quality Trends for patterns
3. **Source Maintenance**: Address stale/outdated sources regularly
4. **Quality Threshold**: Investigate jobs with quality score <70%
5. **Freshness Target**: Keep >80% of sources in "fresh" status

### Alerts and Thresholds

| Metric | Warning Threshold | Critical Threshold |
|--------|------------------|-------------------|
| Overall Health | <70% | <50% |
| Quality Score | <70% | <50% |
| Completeness | <85% | <70% |
| Freshness | >14 days | >30 days |
| Error Count | >2 | >5 |

---

## Integration Points

### Notification System Integration

All Priority 3 features are integrated with the notification system:

1. **Model Performance**
   - Notifications when models complete training
   - Alerts for failed training jobs
   - Notifications for model performance degradation

2. **Data Quality**
   - Alerts when quality scores drop below thresholds
   - Notifications for stale data sources
   - Alerts for data ingestion failures

### Navigation

All three features are accessible from the main sidebar:
- **Performance** - Model Performance Dashboard
- **Data Quality** - Data Quality Monitoring Dashboard
- **Notification Bell** - In header (top right)

### Real-time Updates

- **Notifications**: Poll every 30 seconds
- **Data Quality Stats**: Poll every 60 seconds
- **Model Performance**: Standard React Query stale time (5 minutes)

---

## Technical Implementation

### Tech Stack

**Backend:**
- FastAPI for REST APIs
- SQLAlchemy for database models
- Pydantic for schema validation
- PostgreSQL with JSONB support

**Frontend:**
- React 18 with hooks
- React Query for server state
- Zustand for client state
- Tailwind CSS for styling

### File Structure

```
backend/
├── models/
│   └── notification.py
├── schemas/
│   └── notification.py
├── services/
│   └── notification_service.py
├── api/
│   └── routes/
│       ├── notifications.py
│       └── data_quality.py
├── modules/
│   └── data/
│       └── analyzer.py
└── alembic/
    └── versions/
        └── 20251107_152125_add_notifications.py

frontend/
├── src/
│   ├── pages/
│   │   ├── ModelPerformance.jsx
│   │   └── DataQuality.jsx
│   ├── components/
│   │   └── NotificationBell.jsx
│   └── hooks/
│       ├── useNotifications.js
│       └── useDataQuality.js
```

### Database Models

**Notification Table:**
```sql
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    notification_type VARCHAR(50) NOT NULL,
    priority VARCHAR(20) DEFAULT 'medium',
    category VARCHAR(50),
    is_urgent BOOLEAN DEFAULT FALSE,
    is_read BOOLEAN DEFAULT FALSE,
    is_dismissed BOOLEAN DEFAULT FALSE,
    action_url VARCHAR(500),
    action_label VARCHAR(100),
    expires_at TIMESTAMP WITH TIME ZONE,
    metadata JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    read_at TIMESTAMP WITH TIME ZONE,
    dismissed_at TIMESTAMP WITH TIME ZONE
);
```

---

## Future Enhancements

### Planned Features

1. **Notification System**
   - Email/SMS delivery options
   - Custom notification rules
   - Notification history archive
   - Bulk actions UI

2. **Model Performance**
   - Model comparison side-by-side
   - Performance prediction trends
   - Automatic retraining suggestions
   - Model versioning dashboard

3. **Data Quality**
   - Automated quality rules engine
   - Custom quality thresholds per source
   - Quality score predictions
   - Data lineage visualization

---

## Troubleshooting

### Notifications Not Appearing

1. Check backend logs for API errors:
   ```bash
   docker-compose logs backend | grep notifications
   ```

2. Verify notification endpoint is accessible:
   ```bash
   curl http://localhost:8000/api/v1/notifications
   ```

3. Check browser console for frontend errors

4. Verify React Query is properly configured

### Data Quality Dashboard Empty

1. Ensure data sources are configured:
   ```bash
   curl http://localhost:8000/api/v1/data-sources
   ```

2. Verify recent jobs have completed:
   ```bash
   curl http://localhost:8000/api/v1/jobs?status=completed
   ```

3. Check that job results contain quality scores

### Model Performance Dashboard Not Loading

1. Verify models exist in database:
   ```bash
   curl http://localhost:8000/api/v1/models
   ```

2. Check that models have result data populated

3. Verify API response includes required fields (accuracy, result.test_r2, etc.)

---

## Support

For questions or issues with Priority 3 features:

1. Check the [API Documentation](/docs/api_v2.md)
2. Review backend logs: `docker-compose logs backend`
3. Review frontend logs: `docker-compose logs frontend`
4. Check the browser console for JavaScript errors

---

## Changelog

### Version 2.0.0 (2025-11-07)

**Added:**
- Complete notification system with backend API and UI components
- Model Performance Dashboard with performance metrics and comparisons
- Data Quality Monitoring Dashboard with freshness and quality tracking
- Real-time polling for notifications and data quality stats
- Integrated notification bell in header
- Quality score calculation in DataAnalyzer
- Comprehensive API endpoints for all three features

**Changed:**
- Updated Header component to use NotificationBell component
- Added navigation links for Performance and Data Quality pages
- Enhanced model results to include quality metrics

**Technical:**
- Added 18 new API endpoints across notifications and data quality
- Created 3 new database migrations
- Added 7 new React hooks
- Created 2 major dashboard pages
- Implemented WebSocket support for real-time job updates (Priority 2)
