# BEACON Production Deployment Guide

**Version:** 2.0.0
**Last Updated:** 2025-11-05
**Status:** Production-Ready with Authentication & Real-time Monitoring

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Authentication Setup](#authentication-setup)
4. [Real-time Monitoring](#real-time-monitoring)
5. [Environment Configuration](#environment-configuration)
6. [Security Hardening](#security-hardening)
7. [Database Migration](#database-migration)
8. [Monitoring & Logging](#monitoring--logging)
9. [Performance Tuning](#performance-tuning)
10. [Backup & Recovery](#backup--recovery)
11. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

**Minimum:**
- CPU: 4 cores
- RAM: 8GB
- Disk: 50GB SSD
- OS: Ubuntu 20.04+ / Debian 11+ / RHEL 8+

**Recommended:**
- CPU: 8+ cores
- RAM: 16GB+
- Disk: 100GB+ SSD
- OS: Ubuntu 22.04 LTS
- GPU: NVIDIA with CUDA 11.8+ (optional, for ML training)

### Software Dependencies

```bash
# Docker & Docker Compose
docker --version  # >= 20.10
docker compose version  # >= v2.0

# Optional: NVIDIA GPU support
nvidia-smi  # Verify CUDA installation
```

---

## Quick Start

### 1. Clone and Configure

```bash
# Clone repository
git clone https://github.com/bnelabs/beacon.git
cd beacon

# Copy environment template
cp .env.example .env

# Edit environment variables (see Environment Configuration section)
nano .env
```

### 2. Install Dependencies

```bash
# Backend dependencies
cd backend
pip install -r requirements.txt

# Frontend dependencies
cd ../frontend
npm install
```

### 3. Start Services

```bash
# Production mode
docker compose up -d

# With GPU support
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# View logs
docker compose logs -f backend
```

### 4. Verify Deployment

```bash
# Health check
curl http://localhost:3456/health

# API documentation
open http://localhost:3456/docs

# Frontend
open http://localhost:9876
```

---

## Authentication Setup

### 🔐 JWT Authentication

BEACON now includes a complete JWT-based authentication system with role-based access control (RBAC).

### Default Accounts

**⚠️ IMPORTANT: Change these passwords immediately in production!**

| Username | Password | Role | Permissions |
|----------|----------|------|-------------|
| `admin` | `admin123` | Admin | Full access, user management |
| `analyst` | `analyst123` | Analyst | Create jobs, manage data sources, view models |
| `viewer` | `viewer123` | Viewer | Read-only access |

### Configuration

```bash
# Required environment variables
export JWT_SECRET_KEY="your-super-secret-key-here-change-me"
export ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24 hours
```

**Generate secure secret key:**

```bash
# Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# OpenSSL
openssl rand -base64 32
```

### API Usage

#### Login

```bash
curl -X POST http://localhost:3456/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# Response:
# {
#   "access_token": "eyJhbGc...",
#   "refresh_token": "eyJhbGc...",
#   "token_type": "bearer"
# }
```

#### Authenticated Requests

```bash
# Use token in subsequent requests
curl http://localhost:3456/api/v1/jobs \
  -H "Authorization: Bearer eyJhbGc..."
```

#### Refresh Token

```bash
curl -X POST http://localhost:3456/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJhbGc..."}'
```

### Role-Based Access Control (RBAC)

**Permissions by Role:**

- **Admin:**
  - All permissions
  - User management
  - System configuration

- **Analyst:**
  - Create and manage jobs
  - Manage data sources
  - View models and results
  - Create scenarios

- **Viewer:**
  - Read-only access to all resources

### Frontend Integration

```javascript
// Login
const login = async (username, password) => {
  const response = await fetch('http://localhost:3456/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  const data = await response.json()

  // Store tokens
  localStorage.setItem('access_token', data.access_token)
  localStorage.setItem('refresh_token', data.refresh_token)
}

// Authenticated API calls
const fetchJobs = async () => {
  const token = localStorage.getItem('access_token')
  const response = await fetch('http://localhost:3456/api/v1/jobs', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })
  return response.json()
}

// Auto-refresh token
const refreshToken = async () => {
  const refresh_token = localStorage.getItem('refresh_token')
  const response = await fetch('http://localhost:3456/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token })
  })
  const data = await response.json()
  localStorage.setItem('access_token', data.access_token)
}
```

### API Key Authentication

For programmatic access (CI/CD, scripts, external systems):

```bash
# Set API keys in environment
export VALID_API_KEYS="key1,key2,key3"

# Use in requests
curl http://localhost:3456/api/v1/jobs \
  -H "X-API-Key: key1"
```

---

## Real-time Monitoring

### 🔄 WebSocket Support

BEACON now supports WebSocket connections for real-time job status updates.

### Connect to Job Updates

```javascript
// Connect to specific job
const jobId = 123
const ws = new WebSocket(`ws://localhost:3456/api/ws/jobs/${jobId}`)

ws.onopen = () => {
  console.log('Connected to job updates')
}

ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  console.log('Job update:', data)

  // Handle different message types
  switch(data.type) {
    case 'status_change':
      console.log(`Job ${data.job_id} status: ${data.status}`)
      break
    case 'progress':
      console.log(`Job ${data.job_id} progress: ${data.progress}%`)
      break
    case 'final':
      console.log(`Job ${data.job_id} completed!`, data.result)
      ws.close()
      break
  }
}

ws.onerror = (error) => {
  console.error('WebSocket error:', error)
}

ws.onclose = () => {
  console.log('WebSocket closed')
}

// Send ping to keep connection alive
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }))
  }
}, 30000)
```

### Test WebSocket Connection

Access test page: http://localhost:3456/api/ws/test

### React Hook Example

```javascript
import { useEffect, useState } from 'react'

function useJobStatus(jobId) {
  const [status, setStatus] = useState(null)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    if (!jobId) return

    const ws = new WebSocket(`ws://localhost:3456/api/ws/jobs/${jobId}`)

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)

      if (data.type === 'status_change' || data.type === 'progress') {
        setStatus(data.status)
        setProgress(data.progress)
      }
    }

    return () => ws.close()
  }, [jobId])

  return { status, progress }
}

// Usage
function JobMonitor({ jobId }) {
  const { status, progress } = useJobStatus(jobId)

  return (
    <div>
      <div>Status: {status}</div>
      <div>Progress: {progress}%</div>
      <progress value={progress} max={100} />
    </div>
  )
}
```

### Production WebSocket Configuration

```nginx
# Nginx configuration for WebSocket proxy
location /api/ws/ {
    proxy_pass http://backend:3456;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400;
}
```

---

## Environment Configuration

### Required Variables

Create `.env` file in project root:

```bash
# =============================================================================
# BEACON Production Environment Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Database Configuration
# -----------------------------------------------------------------------------
DATABASE_URL=postgresql://beacon_user:CHANGE_ME@postgres:5432/beacon_db
POSTGRES_DB=beacon_db
POSTGRES_USER=beacon_user
POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# -----------------------------------------------------------------------------
# Redis Configuration
# -----------------------------------------------------------------------------
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# -----------------------------------------------------------------------------
# Authentication & Security
# -----------------------------------------------------------------------------
JWT_SECRET_KEY=CHANGE_ME_GENERATE_WITH_openssl_rand_base64_32
ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS=7

# API Keys (comma-separated)
VALID_API_KEYS=api_key_1,api_key_2

# -----------------------------------------------------------------------------
# External API Keys (for data sources)
# -----------------------------------------------------------------------------
FRED_API_KEY=your_fred_api_key_here
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key
SEC_API_KEY=your_sec_api_key
FMP_API_KEY=your_fmp_api_key

# -----------------------------------------------------------------------------
# CORS Configuration
# -----------------------------------------------------------------------------
ALLOWED_ORIGINS=https://beacon.yourdomain.com,https://app.yourdomain.com
ALLOW_CREDENTIALS=true

# -----------------------------------------------------------------------------
# Application Settings
# -----------------------------------------------------------------------------
PYTHONPATH=/app
PORT=3456
LANG=C.UTF-8
LC_ALL=C.UTF-8
PYTHONIOENCODING=utf-8

# Frontend build configuration
VITE_API_BASE_URL=https://api.beacon.yourdomain.com

# -----------------------------------------------------------------------------
# Monitoring & Logging
# -----------------------------------------------------------------------------
LOG_LEVEL=INFO
SENTRY_DSN=https://your-sentry-dsn@sentry.io/project-id

# -----------------------------------------------------------------------------
# Performance Tuning
# -----------------------------------------------------------------------------
CELERY_WORKER_CONCURRENCY=4
CELERY_TASK_TIME_LIMIT=3600
CELERY_TASK_SOFT_TIME_LIMIT=3300

# Database connection pool
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# -----------------------------------------------------------------------------
# Backup Configuration
# -----------------------------------------------------------------------------
BACKUP_ENABLED=true
BACKUP_SCHEDULE="0 2 * * *"  # Daily at 2 AM
BACKUP_RETENTION_DAYS=30
BACKUP_STORAGE_PATH=/backups
```

### Secrets Management

**Never commit secrets to version control!**

#### Option 1: Docker Secrets

```yaml
# docker-compose.prod.yml
secrets:
  db_password:
    file: ./secrets/db_password.txt
  jwt_secret:
    file: ./secrets/jwt_secret.txt

services:
  backend:
    secrets:
      - db_password
      - jwt_secret
```

#### Option 2: HashiCorp Vault

```bash
# Store secrets in Vault
vault kv put secret/beacon/prod \
  jwt_secret="your-secret" \
  db_password="your-password"

# Retrieve in application
vault kv get -field=jwt_secret secret/beacon/prod
```

#### Option 3: AWS Secrets Manager

```python
import boto3
import json

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])
```

---

## Security Hardening

### 1. Network Security

```yaml
# docker-compose.prod.yml
services:
  backend:
    networks:
      - internal
    # Don't expose port to host, use reverse proxy
    expose:
      - "3456"

  postgres:
    networks:
      - internal
    # Never expose database to internet
    # expose:
    #   - "5432"  # ONLY for internal network

networks:
  internal:
    driver: bridge
    internal: true
  public:
    driver: bridge
```

### 2. SSL/TLS Configuration

```nginx
# /etc/nginx/sites-available/beacon
server {
    listen 443 ssl http2;
    server_name beacon.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/beacon.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/beacon.yourdomain.com/privkey.pem;

    # Strong SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;

    # API proxy
    location /api/ {
        proxy_pass http://localhost:3456/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Frontend
    location / {
        proxy_pass http://localhost:9876;
        proxy_set_header Host $host;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name beacon.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

### 3. Rate Limiting

```python
# backend/middleware/rate_limit.py
from fastapi import Request, HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

# In main.py
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to endpoints
@router.post("/login")
@limiter.limit("5/minute")  # 5 attempts per minute
async def login(request: Request, credentials: LoginRequest):
    ...
```

### 4. Database Security

```sql
-- Create read-only user for analytics
CREATE USER beacon_readonly WITH PASSWORD 'readonly_password';
GRANT CONNECT ON DATABASE beacon_db TO beacon_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO beacon_readonly;

-- Revoke unnecessary permissions
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE beacon_db FROM PUBLIC;
```

### 5. Input Validation

All input is already validated through Pydantic schemas, but add additional checks:

```python
# backend/validators.py
from pydantic import validator

class JobCreate(BaseModel):
    name: str

    @validator('name')
    def name_must_be_safe(cls, v):
        # Prevent SQL injection attempts
        if any(char in v for char in [';', '--', '/*', '*/']):
            raise ValueError('Invalid characters in name')
        return v
```

---

## Database Migration

### Initial Setup

```bash
cd backend

# Initialize Alembic (if not already done)
alembic init alembic

# Create initial migration
alembic revision --autogenerate -m "Initial schema"

# Apply migrations
alembic upgrade head
```

### Production Migration

```bash
# Backup database first!
docker exec beacon-postgres pg_dump -U beacon_user beacon_db > backup_$(date +%Y%m%d).sql

# Run migrations
docker exec beacon-backend alembic upgrade head

# Verify
docker exec beacon-postgres psql -U beacon_user -d beacon_db -c "\dt"
```

### Rollback

```bash
# Rollback one version
alembic downgrade -1

# Rollback to specific version
alembic downgrade revision_id
```

---

## Monitoring & Logging

### Application Monitoring

#### Option 1: Sentry (Error Tracking)

```bash
pip install sentry-sdk[fastapi]
```

```python
# backend/api/main.py
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[FastApiIntegration()],
    traces_sample_rate=1.0,
    environment="production"
)
```

#### Option 2: Prometheus + Grafana

```yaml
# docker-compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
```

```python
# Add metrics endpoint
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests')
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency')

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

### Logging Configuration

```python
# backend/logging_config.py
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logging():
    logHandler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s'
    )
    logHandler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.addHandler(logHandler)
    logger.setLevel(logging.INFO)
```

### Log Aggregation

```yaml
# docker-compose.logging.yml
services:
  loki:
    image: grafana/loki
    ports:
      - "3100:3100"

  promtail:
    image: grafana/promtail
    volumes:
      - /var/log:/var/log
      - ./promtail-config.yml:/etc/promtail/config.yml
```

---

## Performance Tuning

### 1. Database Optimization

```sql
-- Add indexes for frequently queried fields
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX idx_catalogue_region ON data_catalogue_items(region);
CREATE INDEX idx_catalogue_enabled ON data_catalogue_items(enabled) WHERE enabled = true;

-- Analyze and vacuum
ANALYZE;
VACUUM ANALYZE;

-- Enable query optimization
ALTER DATABASE beacon_db SET random_page_cost = 1.1;
ALTER DATABASE beacon_db SET effective_cache_size = '4GB';
```

### 2. Redis Configuration

```conf
# redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

### 3. Celery Optimization

```python
# backend/tasks/celery_app.py
app = Celery('beacon')
app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,

    # Optimization
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=100,
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Result backend optimization
    result_expires=3600,
    result_backend_transport_options={
        'master_name': 'mymaster',
    }
)
```

### 4. Frontend Optimization

```javascript
// vite.config.js
export default {
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['react', 'react-dom'],
          'three': ['three', '@react-three/fiber', '@react-three/drei'],
          'ui': ['@tanstack/react-query', 'zustand']
        }
      }
    },
    chunkSizeWarningLimit: 1000
  }
}
```

---

## Backup & Recovery

### Automated Backups

```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"
RETENTION_DAYS=30

# Backup PostgreSQL
docker exec beacon-postgres pg_dump -U beacon_user -Fc beacon_db > \
  "$BACKUP_DIR/beacon_db_$DATE.dump"

# Backup uploaded files and results
tar -czf "$BACKUP_DIR/beacon_files_$DATE.tar.gz" \
  ./data ./results ./models

# Backup Redis
docker exec beacon-redis redis-cli BGSAVE
docker cp beacon-redis:/data/dump.rdb "$BACKUP_DIR/redis_$DATE.rdb"

# Remove old backups
find "$BACKUP_DIR" -name "beacon_*" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $DATE"
```

```bash
# Add to crontab
crontab -e
# 0 2 * * * /opt/beacon/backup.sh >> /var/log/beacon_backup.log 2>&1
```

### Restore from Backup

```bash
#!/bin/bash
# restore.sh

BACKUP_FILE=$1

# Stop services
docker compose stop backend celery-worker

# Restore database
docker exec -i beacon-postgres pg_restore -U beacon_user -d beacon_db -c < "$BACKUP_FILE"

# Restore files
tar -xzf "$(dirname $BACKUP_FILE)/beacon_files_*.tar.gz"

# Restart services
docker compose start backend celery-worker

echo "Restore completed"
```

### Disaster Recovery Plan

1. **RTO (Recovery Time Objective):** 4 hours
2. **RPO (Recovery Point Objective):** 24 hours

**Steps:**
1. Provision new infrastructure
2. Restore from latest backup
3. Update DNS records
4. Verify functionality
5. Notify users

---

## Troubleshooting

### Common Issues

#### 1. Authentication Failing

```bash
# Check JWT secret is set
echo $JWT_SECRET_KEY

# Verify token
python -c "from jose import jwt; print(jwt.decode('token', 'secret', algorithms=['HS256']))"

# Check logs
docker compose logs backend | grep -i auth
```

#### 2. WebSocket Not Connecting

```bash
# Check if WebSocket route is accessible
curl -i -N -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
  http://localhost:3456/api/ws

# Check Nginx WebSocket proxy (if using)
nginx -t
```

#### 3. Database Connection Issues

```bash
# Test connection
docker exec beacon-postgres psql -U beacon_user -d beacon_db -c "SELECT 1"

# Check connections
docker exec beacon-postgres psql -U beacon_user -d beacon_db \
  -c "SELECT count(*) FROM pg_stat_activity"

# Increase connection limit
docker exec beacon-postgres psql -U postgres -c \
  "ALTER SYSTEM SET max_connections = 200"
```

#### 4. Celery Workers Not Processing

```bash
# Check worker status
docker exec beacon-celery-worker celery -A tasks.celery_app inspect active

# Check queue length
docker exec beacon-redis redis-cli LLEN celery

# Restart workers
docker compose restart celery-worker
```

#### 5. High Memory Usage

```bash
# Check memory usage
docker stats

# Identify memory hogs
docker exec beacon-backend ps aux --sort=-%mem | head

# Restart service
docker compose restart backend
```

### Health Check Endpoints

```bash
# Application health
curl http://localhost:3456/health

# Database health
curl http://localhost:3456/api/v1/system/health

# Redis health
docker exec beacon-redis redis-cli PING
```

### Performance Profiling

```bash
# Enable query logging
docker exec beacon-postgres psql -U postgres -c \
  "ALTER SYSTEM SET log_statement = 'all'"

# Analyze slow queries
docker exec beacon-postgres psql -U beacon_user -d beacon_db \
  -c "SELECT query, calls, total_time FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10"
```

---

## Production Checklist

### Pre-Deployment

- [ ] Change all default passwords
- [ ] Generate and set JWT_SECRET_KEY
- [ ] Configure SSL/TLS certificates
- [ ] Set up database backups
- [ ] Configure monitoring and alerting
- [ ] Set up log aggregation
- [ ] Review and set rate limits
- [ ] Configure CORS for production domains
- [ ] Test disaster recovery procedures
- [ ] Document runbooks for common issues

### Post-Deployment

- [ ] Verify all endpoints are accessible
- [ ] Test authentication flow
- [ ] Test WebSocket connections
- [ ] Create initial admin user
- [ ] Run smoke tests
- [ ] Monitor error rates
- [ ] Check resource usage
- [ ] Verify backups are running
- [ ] Test alert notifications

### Ongoing Maintenance

- [ ] Weekly: Review error logs
- [ ] Weekly: Check backup integrity
- [ ] Monthly: Update dependencies
- [ ] Monthly: Review access logs
- [ ] Quarterly: Security audit
- [ ] Quarterly: Performance review
- [ ] Annually: Disaster recovery drill

---

## Support & Resources

### Documentation
- API Documentation: http://your-domain.com/docs
- Frontend Guide: `/frontend/README.md`
- Architecture: `/ROADMAP.md`
- EU AI Act Compliance: `/EU_AI_ACT_COMPLIANCE.md`

### Monitoring Dashboards
- Prometheus: http://your-domain.com:9090
- Grafana: http://your-domain.com:3000
- Sentry: https://sentry.io/your-org/beacon

### Emergency Contacts
- DevOps Team: devops@yourdomain.com
- Security Team: security@yourdomain.com
- On-call: +1-XXX-XXX-XXXX

---

**Document Version:** 2.0.0
**Last Review:** 2025-11-05
**Next Review:** 2026-02-05
