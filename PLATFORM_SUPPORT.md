# Platform Support

BEACON supports multiple platforms with automatic configuration detection.

## Supported Platforms

### ✅ macOS Apple Silicon (M1/M2/M3)
- **Auto-detected**: Yes
- **GPU Support**: No (CPU-only)
- **Configuration**: Automatically uses `docker-compose.cpu.yml`
- **Docker Image**: Python 3.10 slim (no CUDA)

### ✅ macOS Intel
- **Auto-detected**: Yes
- **GPU Support**: No (CPU-only)
- **Configuration**: Automatically uses `docker-compose.cpu.yml`
- **Docker Image**: Python 3.10 slim (no CUDA)

### ✅ Linux with NVIDIA GPU
- **Auto-detected**: Yes (if nvidia-smi available)
- **GPU Support**: Yes (requires nvidia-container-toolkit)
- **Configuration**: Automatically uses `docker-compose.gpu.yml`
- **Docker Image**: NVIDIA CUDA 12.6.0 with cuDNN

### ✅ Linux without GPU
- **Auto-detected**: Yes
- **GPU Support**: No (CPU-only)
- **Configuration**: Automatically uses `docker-compose.cpu.yml`
- **Docker Image**: Python 3.10 slim (no CUDA)

## How It Works

The `start.sh` script automatically detects your platform and selects the appropriate Docker configuration:

1. **Platform Detection**: Checks OS (macOS/Linux) and architecture (ARM64/x86_64)
2. **GPU Detection**: On Linux, checks for NVIDIA GPU and Docker runtime
3. **Compose File Selection**: Automatically selects CPU or GPU configuration
4. **Build Optimization**: Uses appropriate Dockerfile for your system

## Docker Compose Files

### Base Configuration
- **`docker-compose.yml`**: Base configuration (defaults to CPU-only)
  - PostgreSQL database
  - Redis cache
  - Backend API (CPU)
  - Celery worker (CPU)
  - Frontend

### CPU-Only Override
- **`docker-compose.cpu.yml`**: CPU-only configuration
  - Uses `Dockerfile.cpu` (Python 3.10 slim)
  - No GPU resources allocated
  - Works on macOS and Linux

### GPU-Enabled Override
- **`docker-compose.gpu.yml`**: GPU-accelerated configuration
  - Uses `Dockerfile` (NVIDIA CUDA 12.6.0)
  - Allocates NVIDIA GPU resources
  - Only for Linux with NVIDIA GPU

## Manual Override

If you want to manually specify the configuration:

### Force CPU-only mode:
```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d
```

### Force GPU mode (Linux with NVIDIA only):
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

## Requirements

### For macOS (both Intel and Apple Silicon):
- Docker Desktop for Mac
- No additional requirements

### For Linux with GPU:
1. NVIDIA GPU with CUDA support
2. NVIDIA Driver (recommended: 525+)
3. NVIDIA Container Toolkit:
```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### For Linux without GPU:
- Docker Engine or Docker Desktop
- No additional requirements

## Performance Considerations

### CPU-Only Mode (macOS, Linux without GPU)
- ✅ Data collection: Full speed
- ✅ Data validation: Full speed
- ✅ API operations: Full speed
- ⚠️  Model training: Slower (use smaller models)
- ⚠️  Predictions: Slower

### GPU Mode (Linux with NVIDIA)
- ✅ Data collection: Full speed
- ✅ Data validation: Full speed
- ✅ API operations: Full speed
- ✅ Model training: Fast (GPU-accelerated)
- ✅ Predictions: Fast (GPU-accelerated)

## Troubleshooting

### macOS: "CUDA not available" warnings
- **Expected behavior** on macOS
- System automatically uses CPU-only mode
- You can safely ignore these warnings

### Linux: GPU not detected
1. Check if GPU is available: `nvidia-smi`
2. Check Docker runtime: `docker info | grep -i runtime`
3. Install nvidia-container-toolkit (see Requirements)
4. Restart Docker: `sudo systemctl restart docker`

### Build fails on Apple Silicon
- Ensure Docker Desktop is updated to latest version
- Try clean build: Choose option 3 in start.sh menu
- Check Docker has enough memory allocated (Settings > Resources)

## Architecture

```
┌─────────────────────────────────────────────┐
│           Platform Detection                 │
│  (macOS M1/M2/M3, macOS Intel, Linux)       │
└─────────────┬───────────────────────────────┘
              │
              ├─── macOS ──────► docker-compose.cpu.yml
              │                  (Python 3.10 slim)
              │
              └─── Linux ────┬── GPU Available ──► docker-compose.gpu.yml
                             │                     (CUDA 12.6.0)
                             │
                             └── No GPU ────────► docker-compose.cpu.yml
                                                   (Python 3.10 slim)
```

## Testing Your Setup

After starting BEACON, check the platform detection output:

```bash
./scripts/start.sh
```

Look for:
- ✓ Platform detection results
- ✓ CPU/GPU configuration message
- ✓ Docker image build process

## Questions?

- **Q**: Can I use GPU on macOS?
  - **A**: No, NVIDIA CUDA is not available on macOS. The system automatically uses CPU mode.

- **Q**: Will it work on Windows?
  - **A**: Windows with WSL2 should work. Use the Linux instructions within WSL2.

- **Q**: Do I need a GPU?
  - **A**: No, BEACON works fine in CPU mode for most use cases. GPU just makes training faster.

- **Q**: Can I switch between CPU and GPU mode?
  - **A**: Yes, rebuild with appropriate compose files or use manual override commands.
