# Liquidity Monitor - Quick Start Guide

Welcome to Liquidity Monitor v2.0 - a production-grade financial liquidity risk monitoring system designed for regulatory use.

## 🚀 Quick Start (5 minutes)

### Prerequisites
- **Docker Desktop** (includes Docker Compose)
- **8GB RAM minimum** (24GB recommended)
- **10GB free disk space**

### Installation

1. **Install Docker Desktop**
   - Download from: https://www.docker.com/products/docker-desktop
   - Install and start Docker Desktop
   - Verify: `docker --version` and `docker-compose --version`

2. **Clone or download this repository**
   ```bash
   cd /path/to/liquidity-monitor
   ```

3. **Start the system**
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

   This will:
   - Create required directories
   - Build Docker images
   - Start all services (database, API, worker, frontend)
   - Initialize the system

4. **Open the dashboard**
   - Navigate to: http://localhost:3000
   - You should see the Liquidity Monitor dashboard

## 📋 First Time Setup

### Step 1: Add a Data Source

1. Click **"Data Sources"** in the sidebar
2. Click **"Add Data Source"**
3. Fill in the form:
   - **Name**: Yahoo Finance
   - **Plugin Type**: Yahoo Finance (Free, no key needed)
   - **Enabled**: ✓ (checked)
4. Click **"Add"**

**Result**: You now have a free data source configured. Yahoo Finance doesn't require an API key!

### Step 2: Add Assets to Monitor

1. Click **"Assets"** in the sidebar
2. Click **"Add Asset"**
3. Fill in the form:
   - **Symbol**: JPM (or any stock ticker)
   - **Name**: JPMorgan Chase (optional)
   - **Asset Type**: stock
   - **Data Source**: Select "Yahoo Finance"
   - **Enabled**: ✓ (checked)
4. Click **"Add"**
5. Repeat for more assets (recommended: 5-10 financial stocks)

**Example tickers**: JPM, BAC, GS, MS, WFC, C, BLK

### Step 3: Collect Data

1. Click **"Jobs"** in the sidebar
2. Click **"Start New Job"**
3. Select **"Data Collection"**
4. Click **"Start"**

**Wait time**: 1-5 minutes depending on number of assets

**Result**: The system downloads historical price data for your assets.

### Step 4: Train the Model

1. Go to **"Jobs"**
2. Click **"Start New Job"**
3. Select **"Training"**
4. Click **"Start"**

**Wait time**: 5-15 minutes depending on your hardware

**Result**: The AI model learns to predict liquidity risk from historical patterns.

### Step 5: View Results

1. Return to **"Dashboard"**
2. View system status, data sources, and job progress
3. Check for any errors or warnings

## 🎯 What This System Does

**For Non-Technical Users:**

This system monitors financial assets (stocks, bonds, etc.) and predicts liquidity risk - which is how easy it is to buy or sell an asset without affecting its price.

**Key Concepts:**

- **Data Sources**: Where we get market data (Yahoo Finance, FRED, etc.)
- **Assets**: The stocks or bonds we're monitoring
- **Jobs**: Background tasks that collect data, train the model, or make predictions
- **Configuration**: Settings for the AI model and data collection

**Predictions**: The system forecasts liquidity risk 7 days ahead, helping regulators identify potential market stress before it happens.

## 🔧 Configuration

### Adding API Keys (Optional)

Some data sources require API keys. To add them:

1. Edit the `.env` file in the project root:
   ```bash
   nano .env
   ```

2. Add your keys:
   ```
   FRED_API_KEY=your_key_here
   SEC_API_KEY=your_key_here
   ```

3. Restart the system:
   ```bash
   docker-compose restart
   ```

**Where to get free API keys:**
- FRED: https://fred.stlouisfed.org/docs/api/api_key.html
- Alpha Vantage: https://www.alphavantage.co/support/#api-key

### Adjusting Resource Usage

If you have limited RAM or want to optimize performance:

1. Open the dashboard: http://localhost:3000
2. Go to **"System Status"**
3. Click **"View Recommendations"**
4. The system will suggest optimal batch sizes and model settings for your hardware

## 🛠️ Common Tasks

### View Logs
```bash
docker-compose logs -f
```

### Stop the System
```bash
./stop.sh
# or
docker-compose stop
```

### Restart Services
```bash
docker-compose restart
```

### Update the System
```bash
docker-compose down
git pull  # if using git
docker-compose build --no-cache
docker-compose up -d
```

### Backup Data
```bash
# Backup database
docker exec liquidity_monitor_postgres pg_dump -U liquidity liquidity_monitor > backup.sql

# Backup files
tar -czf backup_data.tar.gz data/ results/ models/
```

### Clean Start (Remove All Data)
```bash
docker-compose down -v
rm -rf data/* results/* models/*
./start.sh
```

## 📊 Understanding the Dashboard

### Dashboard Overview
- **System Status**: CPU, RAM, GPU usage
- **Data Sources**: Number of active data feeds
- **Monitored Assets**: How many stocks/bonds you're tracking
- **Background Jobs**: Current and recent tasks

### Data Sources Page
- Add/remove data feeds
- Test connections
- View last successful update

### Assets Page
- Add/remove stocks/bonds to monitor
- Set liquidity alert thresholds
- Enable/disable monitoring per asset

### Jobs Page
- Start new jobs (data collection, training, predictions)
- Monitor job progress
- View job results and errors

### Configuration Page
- Adjust model parameters
- Change data collection settings
- Modify training options

### System Status Page
- Real-time resource monitoring
- Performance recommendations
- System health checks

## 🚨 Troubleshooting

### Services Won't Start
```bash
# Check if ports are in use
lsof -i :3000  # Frontend
lsof -i :8000  # Backend
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis

# Stop any conflicting services
docker-compose down
./start.sh
```

### "Out of Memory" Errors
1. Go to Configuration
2. Reduce **Batch Size** to 16 or 8
3. Reduce **Hidden Dimension** to 64
4. Restart training job

### Data Collection Fails
- Check internet connection
- Verify API keys in `.env` file
- Check data source status in dashboard
- View detailed error in Jobs page (click on failed job)

### Cannot Access Dashboard
- Verify frontend is running: `docker ps`
- Check logs: `docker-compose logs frontend`
- Try different browser
- Clear browser cache

### API Connection Errors
- Verify backend is running: `docker ps`
- Check logs: `docker-compose logs backend`
- Check API health: http://localhost:8000/health

## 📱 Accessing from Other Devices

To access the dashboard from another computer on your network:

1. Find your machine's IP address:
   ```bash
   # macOS/Linux
   ifconfig | grep "inet "

   # Windows
   ipconfig
   ```

2. On another device, open:
   - Dashboard: http://YOUR_IP:3000
   - API: http://YOUR_IP:8000

**Security Note**: This is for local network use only. For production deployment with internet access, additional security measures are required.

## 🆘 Getting Help

### Check Logs
Most issues can be diagnosed from logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs backend
docker-compose logs celery_worker
docker-compose logs frontend
```

### Common Error Messages

**"Cannot connect to database"**
- Wait 30 seconds for database to initialize
- Restart: `docker-compose restart backend`

**"API key invalid"**
- Check `.env` file for correct key
- Verify key is active at provider's website
- Restart: `docker-compose restart`

**"Out of memory"**
- Reduce batch size in Configuration
- Monitor fewer assets
- Add more RAM to your machine

**"Connection timeout"**
- Check internet connection
- Increase rate limit in Configuration
- Wait and retry (may be temporary provider issue)

## 🎓 Next Steps

Once you're comfortable with the basics:

1. **Add more data sources**: FRED for economic indicators
2. **Increase asset coverage**: Monitor more stocks/bonds
3. **Run backtests**: Test model performance on historical data
4. **Customize thresholds**: Set liquidity alert levels per asset
5. **Schedule jobs**: Set up automated data collection and predictions

## 📚 Additional Resources

- **API Documentation**: http://localhost:8000/docs
- **Architecture Details**: See `docs/improvement_plan/` folder
- **Configuration Reference**: See `configs/config.yaml`

## 🔐 Security Notes

**This is a development/local deployment setup.** For production use:

- Change default database passwords in `docker-compose.yml`
- Use environment variables for sensitive data
- Enable HTTPS/TLS
- Implement authentication
- Use firewall rules
- Regular security updates

## 📝 License

This system is provided for regulatory and risk management purposes only. Not for automated trading.

---

**Questions?** Check the logs first, then review this guide. Most issues are resolved by restarting services or adjusting configuration.
