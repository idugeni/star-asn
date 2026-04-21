# Star ASN - Docker Development Quick Start Guide

## ⚡ Quick Start (5 minutes)

### 1. Start Development Environment with Hot-Reload

```bash
# One command - starts all services with live file sync
docker compose -f docker-compose.dev.yml --profile dev up --watch
```

**What happens automatically:**
- ✅ Builds image (cache disabled for latest code)
- ✅ Starts bootstrap → api → worker → bot in sequence
- ✅ File changes auto-synced: `api/` and `star_attendance/` → container
- ✅ Services auto-restart when files change
- ✅ Logs streamed to terminal

**Edit example:**
1. Open `api/main.py` in your editor
2. Make a change
3. Watch terminal → file synced automatically
4. API service restarts instantly (~2 seconds)

---

## 🎯 Option A: Command Line Only (Fastest)

**Terminal 1 - Start services:**
```bash
docker compose -f docker-compose.dev.yml --profile dev up --watch
```

**Terminal 2 - Run tests/checks while services run:**
```bash
# Run all tests
docker compose -f docker-compose.dev.yml exec api pytest tests/ -v

# Type check
docker compose -f docker-compose.dev.yml exec api mypy api/ star_attendance/

# Lint with ruff
docker compose -f docker-compose.dev.yml exec api ruff check api/

# Format code
docker compose -f docker-compose.dev.yml exec api ruff format api/
```

---

## 🎯 Option B: VS Code Dev Containers (Full IDE Experience)

**Setup (first time only):**
1. Install VS Code extensions: "Remote - Containers" + "Docker"
2. Open this project in VS Code
3. Press **F1** → type "Reopen in Container"
4. VS Code rebuilds container & mounts workspace

**Inside Dev Container:**
- Python environment = production environment
- All dependencies pre-installed
- Debugging available
- Terminal runs inside container
- Port 8000 auto-forwarded

**Run commands in VS Code terminal:**
```bash
# Tests with live output
pytest tests/ -v

# Continuous type check
mypy api/ --watch

# Format on save (automatic in Editor settings)
ruff format api/
```

---

## 📊 Useful Commands

### View Logs
```bash
# All services
docker compose -f docker-compose.dev.yml logs -f

# Specific service
docker compose -f docker-compose.dev.yml logs -f api

# Last 50 lines
docker compose -f docker-compose.dev.yml logs --tail=50 api
```

### Stop Services
```bash
# Graceful stop (waits 30s)
docker compose -f docker-compose.dev.yml down

# Immediate stop
docker compose -f docker-compose.dev.yml kill
```

### Clean Cache & Rebuild
```bash
# Remove volumes, rebuild without cache
docker compose -f docker-compose.dev.yml down -v
docker compose -f docker-compose.dev.yml --profile dev build --no-cache
docker compose -f docker-compose.dev.yml --profile dev up --watch
```

### Run Command Inside Container
```bash
# One-off command
docker compose -f docker-compose.dev.yml exec api python -m pytest tests/

# Interactive shell
docker compose -f docker-compose.dev.yml exec api bash
```

---

## 🔍 Troubleshooting

### "Port 8000 already in use"
```bash
# Kill whatever is using port 8000
# macOS/Linux:
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9

# Windows:
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### "Watch not detecting file changes"
```bash
# Verify Docker Compose version >= 2.20
docker compose version

# Restart with verbose mode
docker compose -f docker-compose.dev.yml --profile dev up --watch --verbose
```

### "Service keeps restarting"
```bash
# Check logs
docker compose -f docker-compose.dev.yml logs api

# Verify .env file exists
ls -la .env

# Check API healthcheck
docker compose -f docker-compose.dev.yml exec api python -m star_attendance.service_runner check-api
```

### "Dev Container connection failed"
```bash
# Verify docker daemon is running
docker ps

# Check devcontainer.json syntax
cat .devcontainer/devcontainer.json

# Rebuild container
# In VS Code: F1 → "Dev Containers: Rebuild Container"
```

---

## 📋 What Each File Does

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Production config |
| `docker-compose.dev.yml` | Development with hot-reload, debug logging |
| `.devcontainer/devcontainer.json` | VS Code remote dev environment |
| `.dockerignore` | Excludes cache/tests from build context |
| `.github/workflows/validate-devcontainer.yml` | CI/CD validation |

---

## 🚀 Development Workflow Example

**Scenario: Fix a bug in API**

1. **Start development:**
   ```bash
   docker compose -f docker-compose.dev.yml --profile dev up --watch
   ```

2. **Edit code** (in your IDE):
   ```python
   # api/routes.py - make a change
   ```

3. **See result instantly:**
   - File synced to container
   - API service auto-restarts
   - Check logs in terminal

4. **Run tests:**
   ```bash
   docker compose -f docker-compose.dev.yml exec api pytest tests/ -v
   ```

5. **When done, stop:**
   ```bash
   docker compose -f docker-compose.dev.yml down
   ```

---

## 📦 Versions

- **Docker:** 29.4.0+ (your system: 29.4.0 ✓)
- **Docker Compose:** 5.1.2+ (your system: 5.1.2 ✓)
- **Python:** 3.12 (in container)
- **Dev Dependencies:** pytest, ruff, mypy, debugpy (auto-installed)

---

## 💡 Pro Tips

1. **Keep terminal visible** → See logs in real-time as you code
2. **Use VS Code Dev Container** → Get IntelliSense + debugging
3. **Never restart manually** → Watch mode handles it
4. **Check .env before starting** → API needs env variables
5. **Commit early, test often** → GitHub Actions validates on push

---

## ❓ Still Have Questions?

```bash
# Inspect docker-compose.dev.yml structure
docker compose -f docker-compose.dev.yml config

# Check if all services are running
docker compose -f docker-compose.dev.yml ps

# Get detailed service info
docker compose -f docker-compose.dev.yml inspect api
```

Start with `docker compose -f docker-compose.dev.yml --profile dev up --watch` — everything else is optional! 🎉
