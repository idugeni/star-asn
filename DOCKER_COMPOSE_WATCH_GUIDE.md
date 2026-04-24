# Docker Compose Watch & Dev Containers Setup

## 1. Docker Compose Watch (Hot-Reload Development)

**Start development mode with live reload:**
```bash
docker compose up --watch
```

**What happens:**
- Changes to `api/` → synced to container `/app/api`, service restarts (500ms)
- Changes to `star_attendance/` → synced to container, service restarts
- Changes to `pyproject.toml` → full container rebuild (dependency changes)

**Workflow:**
1. Edit `api/routes.py` → automatically synced + api service restarts
2. No need to rebuild image or restart manually
3. Check logs: `docker compose logs -f api`

---

## 2. Dev Containers (VS Code Remote Development)

**Setup (One-time):**
1. Install VS Code extensions: Remote - Containers, Docker
2. Open project in VS Code
3. Press `F1` → "Dev Containers: Reopen in Container"
4. VS Code will build/start container and mount your workspace

**Benefits:**
- Python environment = production environment
- `/opt/venv` already configured
- Ruff, mypy, pytest pre-installed
- All dependencies matching production
- Port 11800 auto-forwarded to localhost

**Inside Dev Container:**
```bash
# Run tests
pytest tests/

# Type check
mypy api/ star_attendance/

# Lint + format
ruff check api/
ruff format api/
```

**Edit code locally → see results immediately in container.**

---

## 3. Combined Workflow (Recommended)

**Terminal 1 - Start services with watch:**
```bash
docker compose up --watch
```

**Terminal 2 - Dev Container:**
```
VS Code → F1 → "Dev Containers: Reopen in Container"
```

**Result:**
- Develop in production environment
- Hot-reload on file changes
- Full debugging + testing + linting available
- Consistency across team

---

## 4. Configuration Details

### `.devcontainer/devcontainer.json`
- **Service:** Connects to `api` service from docker-compose.yml
- **Extensions:** Python, Pylance, Ruff, Docker, Git
- **Post-create:** Installs dev dependencies
- **Post-start:** Installs Playwright chromium

### `docker-compose.yml` Updates
- **develop.watch paths:**
  - `api/` → `/app/api` (code sync)
  - `star_attendance/` → `/app/star_attendance` (code sync)
  - `pyproject.toml` → full rebuild

---

## 5. Troubleshooting

**Watch not triggering?**
- Ensure `docker compose version ≥ 2.20`
- Check file changes are being detected: `docker compose up --watch --verbose`

**Dev Container connection failed?**
- Ensure docker daemon is running
- Check `.devcontainer/devcontainer.json` syntax: `cat .devcontainer/devcontainer.json | jq`

**Port already in use?**
- `lsof -i :11800` (macOS/Linux)
- `netstat -ano | findstr :11800` (Windows)

---

## 6. Next Steps

1. Test watch mode: `docker compose up --watch`
2. Modify `api/main.py` → watch for auto-sync
3. Open in Dev Container for full IDE experience
