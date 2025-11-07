# Real-Time Job Updates & Batch Operations - Documentation

## Overview
This document describes the implementation of real-time WebSocket updates and batch operations for job management in BEACON.

---

## Features Implemented

### 1. Real-Time WebSocket Updates
**Location**: Jobs page - `http://localhost:9876` (navigate to Jobs)

#### Features
- **Live Job Updates**: Jobs automatically update their status and progress without page refresh
- **WebSocket Connection**: Persistent connection to backend for push notifications
- **Automatic Reconnection**: Reconnects automatically if connection drops (max 5 attempts)
- **Fallback to Polling**: Falls back to 5-second polling if WebSocket fails
- **Connection Indicator**: Green "Live updates active" badge when connected

#### Technical Implementation

**Backend Components**:
- `backend/api/routes/jobs_ws.py` - WebSocket endpoint at `/api/v1/jobs/ws`
- Connection manager for broadcasting to all connected clients
- Heartbeat/ping-pong mechanism to keep connections alive
- Serialization of job data for transmission

**Frontend Components**:
- `frontend/src/hooks/useJobsWebSocket.js` - React hook for WebSocket management
- Automatic cache updates via React Query
- Connection state management with reconnection logic

**Key Features**:
```javascript
// WebSocket URL format
ws://localhost:8000/api/v1/jobs/ws  // Development
wss://your-domain.com/api/v1/jobs/ws  // Production

// Message format
{
  "type": "job_update",
  "job": {
    "id": 1,
    "status": "running",
    "progress": 45,
    ...
  }
}
```

#### Usage
1. Navigate to Jobs page
2. Look for green "Live updates active" indicator in header
3. Job cards automatically update as backend processes them
4. No manual refresh needed

---

### 2. Batch Operations
**Location**: Jobs page - Click "Batch Operations" button

#### Features
- **Multi-Select Mode**: Enable checkboxes on job cards
- **Select All/Deselect All**: Quick selection controls
- **Batch Cancel**: Cancel multiple jobs simultaneously
- **Progress Feedback**: Shows success/failure counts for bulk operations
- **Smart Filtering**: Only shows cancellable jobs (pending/running) in selection

#### API Endpoint

**POST** `/api/v1/jobs/batch/cancel`

**Request Body**:
```json
{
  "job_ids": [1, 2, 3, 4, 5]
}
```

**Response**:
```json
{
  "cancelled": [1, 2, 3],
  "failed": [
    {
      "job_id": 4,
      "reason": "Job not found or already completed"
    },
    {
      "job_id": 5,
      "reason": "Job not found or already completed"
    }
  ],
  "total_requested": 5,
  "total_cancelled": 3
}
```

**Constraints**:
- Maximum 50 jobs per batch request
- Only cancels jobs in "pending" or "running" status
- Returns partial success with detailed failure reasons

#### Frontend Components
- `useBatchCancelJobs()` hook in `useApi.js`
- Batch mode UI state management
- Selection bar with action buttons
- Checkboxes integrated into JobRow component

#### Usage
1. Click "Batch Operations" button to enable batch mode
2. Checkboxes appear on all job cards
3. Select jobs individually or use "Select All"
4. Click "Cancel Selected" button
5. Confirm the operation
6. View results summary showing successes and failures
7. Click "Exit Batch Mode" to return to normal view

---

## Implementation Details

### WebSocket Hook API

```javascript
import { useJobsWebSocket } from '../hooks/useJobsWebSocket'

// In your component
const { isConnected, reconnect, disconnect } = useJobsWebSocket({
  enabled: true,  // Enable/disable WebSocket
  onUpdate: (jobUpdate) => {
    // Called when job updates received
    console.log('Job updated:', jobUpdate)
  },
  onError: (error) => {
    // Called on connection errors
    console.error('WebSocket error:', error)
  }
})

// Check connection status
if (isConnected) {
  // WebSocket is active
}

// Manual reconnection
reconnect()

// Manual disconnection
disconnect()
```

### Batch Cancel Hook API

```javascript
import { useBatchCancelJobs } from '../hooks/useApi'

// In your component
const batchCancelMutation = useBatchCancelJobs()

// Cancel multiple jobs
const result = await batchCancelMutation.mutateAsync([1, 2, 3, 4, 5])

// Check result
console.log(`Cancelled: ${result.total_cancelled}`)
console.log(`Failed: ${result.failed.length}`)

// Access mutation state
if (batchCancelMutation.isPending) {
  // Show loading state
}
```

---

## Backend Schema Changes

### New Pydantic Schemas

**File**: `backend/schemas/job.py`

```python
class BatchCancelRequest(BaseModel):
    """Schema for batch canceling jobs."""
    job_ids: list[int] = Field(
        ...,
        description="List of job IDs to cancel",
        min_length=1,
        max_length=50
    )

class BatchCancelResponse(BaseModel):
    """Schema for batch cancel response."""
    cancelled: list[int]
    failed: list[dict[str, Any]]
    total_requested: int
    total_cancelled: int
```

---

## WebSocket Protocol

### Connection Lifecycle

1. **Client connects**: `ws://localhost:8000/api/v1/jobs/ws`
2. **Server responds**: `{"type": "connected", "message": "Connected to job updates stream"}`
3. **Client sends ping**: `"ping"` (every 30 seconds for keepalive)
4. **Server responds**: `{"type": "pong"}`
5. **Server broadcasts updates**: `{"type": "job_update", "job": {...}}`
6. **Connection closes**: Automatic reconnection attempted

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `connected` | Server → Client | Connection established |
| `ping` | Client → Server | Keepalive request |
| `pong` | Server → Client | Keepalive response |
| `job_update` | Server → Client | Job status/progress changed |

### Reconnection Strategy

1. **Initial disconnect**: Wait 3 seconds, attempt reconnect
2. **Retry count**: Maximum 5 reconnection attempts
3. **Fallback**: After 5 failures, switch to 5-second polling
4. **Polling**: Invalidates React Query cache periodically

---

## UI Components

### Jobs Page Enhancements

**New Props for JobRow**:
```javascript
<JobRow
  job={job}
  onSelect={handleSelect}
  isSelected={selected}
  showCheckbox={batchMode}           // NEW: Show checkbox
  isChecked={isChecked}              // NEW: Checkbox state
  onCheckboxChange={handleChange}    // NEW: Checkbox handler
/>
```

**New State Variables**:
```javascript
const [selectedJobIds, setSelectedJobIds] = useState([])
const [batchMode, setBatchMode] = useState(false)
```

**Visual Indicators**:
- Green pulsing dot + "Live updates active" = WebSocket connected
- Blue card with selection controls = Batch mode active
- Checkboxes on job cards = Individual selection
- "Cancel Selected" button = Batch action trigger

---

## Performance Considerations

### WebSocket
- **Connection pooling**: Single connection shared by all components
- **Automatic cleanup**: useEffect cleanup disconnects WebSocket
- **Message throttling**: Backend can implement rate limiting if needed
- **Bandwidth**: Minimal - only sends job updates when changes occur

### Batch Operations
- **Max batch size**: 50 jobs per request to prevent timeout
- **Optimistic updates**: UI updates immediately, rolls back on error
- **Cache invalidation**: Only invalidates affected job queries
- **Parallel processing**: Backend processes cancellations concurrently

---

## Error Handling

### WebSocket Errors
```javascript
// Connection failed
onError: (error) => {
  console.error('WebSocket error:', error)
  // Hook automatically falls back to polling
}

// Max reconnections reached
console.warn('[JobsWebSocket] Max reconnection attempts reached, falling back to polling')
```

### Batch Cancel Errors
```javascript
try {
  const result = await batchCancelMutation.mutateAsync(jobIds)
  // Check result.failed for partial failures
} catch (error) {
  // Complete failure (network error, etc.)
  alert(`Batch cancel failed: ${error.message}`)
}
```

**Partial Success Handling**:
- Shows detailed message: "Cancelled 3 job(s). Failed to cancel 2 job(s)."
- Failed jobs include reason for failure
- Successfully cancelled jobs are removed from selection

---

## Testing Checklist

### WebSocket Testing
- [ ] Open Jobs page, verify "Live updates active" indicator
- [ ] Open browser DevTools → Network → WS tab
- [ ] Verify WebSocket connection to `ws://localhost:8000/api/v1/jobs/ws`
- [ ] Create a new job, verify card updates automatically
- [ ] Simulate disconnect (stop backend), verify reconnection attempts
- [ ] Verify fallback to polling after max reconnections

### Batch Operations Testing
- [ ] Click "Batch Operations" button
- [ ] Verify checkboxes appear on job cards
- [ ] Select multiple jobs
- [ ] Verify selection count updates
- [ ] Click "Select All", verify only cancellable jobs selected
- [ ] Click "Cancel Selected"
- [ ] Verify confirmation dialog
- [ ] Confirm and check success message
- [ ] Verify jobs are cancelled in database
- [ ] Test with 50+ jobs (should limit to 50)
- [ ] Test canceling already completed jobs (should fail gracefully)

---

## Security Considerations

### WebSocket Security
- **Protocol**: Use `wss://` in production (WebSocket Secure)
- **Authentication**: Add token-based auth if needed (not implemented)
- **CORS**: Backend CORS settings apply to WebSocket upgrade requests
- **Rate limiting**: Consider implementing per-connection message limits

### Batch Operations Security
- **Max batch size**: Hardcoded limit of 50 to prevent abuse
- **Permission checks**: JobService validates each cancellation
- **Atomic operations**: Each job cancellation is independent
- **Audit trail**: Job cancellations should be logged (future enhancement)

---

## Production Deployment

### Environment Configuration

**Backend**:
```python
# WebSocket URL will auto-detect protocol
protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
```

**NGINX Configuration** (if using reverse proxy):
```nginx
location /api/v1/jobs/ws {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400;  # 24 hours
}
```

**ALLOWED_ORIGINS** Environment Variable:
```bash
# Add your production domain
ALLOWED_ORIGINS="https://beacon.yourdomain.com,https://app.yourdomain.com"
```

---

## Monitoring & Debugging

### Backend Logs
```bash
# Check WebSocket connections
docker-compose logs backend | grep WebSocket

# Monitor connection count
docker-compose logs backend | grep "Total connections"

# Check disconnections
docker-compose logs backend | grep "disconnected"
```

### Frontend Debugging
```javascript
// Browser console shows:
[JobsWebSocket] Connected
[JobsWebSocket] Disconnected
[JobsWebSocket] Reconnecting (attempt 1/5)
Job update received: {...}
```

### API Testing
```bash
# Test batch cancel endpoint
curl -X POST http://localhost:3456/api/v1/jobs/batch/cancel \
  -H "Content-Type: application/json" \
  -d '{"job_ids": [1, 2, 3]}'

# Expected response:
{
  "cancelled": [1, 2],
  "failed": [{"job_id": 3, "reason": "Job not found"}],
  "total_requested": 3,
  "total_cancelled": 2
}
```

---

## Known Limitations

1. **WebSocket Scaling**: Current implementation uses in-memory connection storage
   - For multi-instance deployment, use Redis Pub/Sub or similar
   - Single instance limit: ~10,000 concurrent connections

2. **Batch Size**: Hard limit of 50 jobs per batch request
   - For larger batches, split into multiple requests
   - Consider background job for very large bulk operations

3. **Authentication**: WebSocket connections don't currently require auth
   - Future enhancement: JWT-based authentication
   - Consider implementing connection whitelisting

4. **Browser Support**: WebSocket requires modern browsers
   - IE 11+, Chrome 14+, Firefox 11+, Safari 7+
   - Fallback polling works on all browsers

---

## Future Enhancements

### Short-term
- [ ] Add authentication to WebSocket connections
- [ ] Implement progress bars for batch operations
- [ ] Add batch resume/retry functionality
- [ ] Export batch operation results as CSV

### Long-term
- [ ] Redis-based WebSocket scaling for multi-instance
- [ ] WebSocket broadcasts for all entity types (not just jobs)
- [ ] Advanced batch operations (pause, resume, prioritize)
- [ ] Real-time collaboration features

---

## API Reference

### WebSocket Endpoint
**URL**: `/api/v1/jobs/ws`
**Protocol**: WebSocket
**Authentication**: None (currently)

### Batch Cancel Endpoint
**URL**: `/api/v1/jobs/batch/cancel`
**Method**: POST
**Authentication**: None (currently)
**Rate Limit**: None (currently)

**Request**:
```json
{
  "job_ids": [1, 2, 3]  // Array of integers, 1-50 items
}
```

**Success Response** (200 OK):
```json
{
  "cancelled": [1, 2],
  "failed": [
    {
      "job_id": 3,
      "reason": "Job not found or already completed"
    }
  ],
  "total_requested": 3,
  "total_cancelled": 2
}
```

**Error Response** (400 Bad Request):
```json
{
  "detail": "job_ids must contain between 1 and 50 items"
}
```

---

## Troubleshooting

### WebSocket Not Connecting

**Symptom**: No "Live updates active" indicator

**Solutions**:
1. Check backend is running: `docker-compose ps backend`
2. Verify WebSocket route loaded: `docker-compose logs backend | grep websocket`
3. Check browser console for errors
4. Verify firewall allows WebSocket connections
5. Try accessing `ws://localhost:8000/api/v1/jobs/ws` directly

### Batch Cancel Not Working

**Symptom**: "Cancel Selected" button doesn't work

**Solutions**:
1. Check selected jobs are cancellable (pending/running status)
2. Verify backend endpoint exists: `curl http://localhost:3456/docs`
3. Check browser console for API errors
4. Verify job IDs are valid integers
5. Check batch size is ≤ 50 jobs

### Jobs Not Updating in Real-Time

**Symptom**: Jobs don't update automatically

**Solutions**:
1. Verify WebSocket connection (see above)
2. Check if fallback polling is active (console logs)
3. Verify backend is broadcasting updates
4. Check React Query cache invalidation
5. Try manual page refresh

---

## File Structure

```
beacon/
├── backend/
│   ├── api/
│   │   ├── main.py                     # WebSocket router integration
│   │   └── routes/
│   │       ├── jobs.py                 # Batch cancel endpoint
│   │       └── jobs_ws.py              # WebSocket endpoint (NEW)
│   └── schemas/
│       └── job.py                      # Batch request/response schemas
│
├── frontend/
│   ├── src/
│   │   ├── hooks/
│   │   │   ├── useApi.js               # useBatchCancelJobs hook
│   │   │   └── useJobsWebSocket.js     # WebSocket hook (NEW)
│   │   └── pages/
│   │       └── Jobs.jsx                # Batch UI + WebSocket integration
│
└── REAL_TIME_JOBS_DOCUMENTATION.md     # This file
```

---

## Summary

### What Was Implemented
1. **Real-Time WebSocket Updates** - Jobs update automatically without refresh
2. **Batch Cancel Operations** - Cancel multiple jobs simultaneously
3. **Smart Reconnection** - Automatic fallback to polling on failure
4. **Batch Selection UI** - Checkboxes and bulk action controls
5. **Connection Indicators** - Visual feedback for connection status

### Benefits
- **Better UX**: No manual refresh needed for job monitoring
- **Efficiency**: Cancel multiple jobs in one operation
- **Reliability**: Automatic fallback ensures functionality
- **Performance**: WebSocket reduces server load vs polling
- **Scalability**: Backend can broadcast to unlimited clients

---

**End of Documentation**
