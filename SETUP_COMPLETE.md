# Star ASN Development Setup - Complete Package

Setup Anda sudah lengkap dengan teknologi terbaru! Berikut adalah ringkasan apa yang telah dikonfigurasi:

## ✅ Sudah Siap Digunakan

### 1. **Docker Compose Watch** (Hot-Reload)
- File: `docker-compose.dev.yml`
- Fitur: Deteksi perubahan file otomatis, sync ke container, restart service
- Cocok untuk development cepat tanpa rebuild ulang

### 2. **Dev Containers** (VS Code Remote Development)
- File: `.devcontainer/devcontainer.json`
- Fitur: Develop di environment production, semua tools pre-installed
- Extensions: Python, Pylance, Ruff, Docker, Git, Debugpy

### 3. **Improved .dockerignore**
- File: `.dockerignore`
- Fitur: Exclude cache files, test files, logs (lebih cepat build)
- Benefit: Ukuran build context lebih kecil, cache lebih efficient

### 4. **GitHub Actions CI/CD Validation**
- File: `.github/workflows/validate-devcontainer.yml`
- Fitur: Otomatis validate config, security scan, build test
- Trigger: Setiap push/PR ke main/develop

### 5. **Setup Scripts**
- File: `scripts/dev-setup.sh` (Linux/macOS)
- File: `scripts/dev-setup.bat` (Windows)
- Fitur: One-command setup, check Docker versions, pull latest images

---

## 🚀 Memulai (Pilih Satu)

### **Opsi A: Setup Otomatis + Command Line** (Rekomendasi)

**Windows:**
```bash
scripts\dev-setup.bat
docker compose -f docker-compose.dev.yml --profile dev up --watch
```

**Linux/macOS:**
```bash
bash scripts/dev-setup.sh
docker compose -f docker-compose.dev.yml --profile dev up --watch
```

✅ Semua services auto-start  
✅ Hot-reload saat file berubah  
✅ Logs terlihat di terminal  

---

### **Opsi B: VS Code Dev Container** (Full IDE)

1. Buka project di VS Code
2. Tekan **F1** → ketik "Reopen in Container"
3. VS Code auto-setup environment production-like
4. Develop dengan IntelliSense + Debugging + Terminal

---

## 📊 Versions Terinstall

| Komponen | Versi | Status |
|----------|-------|--------|
| Docker | 29.4.0 | ✅ Latest |
| Docker Compose | 5.1.2 | ✅ Latest |
| Python (Container) | 3.12 | ✅ Latest |
| Watch Mode | Support | ✅ Enabled |

---

## 📁 File Structure Baru

```
project/
├── .devcontainer/
│   └── devcontainer.json          # VS Code remote dev config
├── .github/workflows/
│   └── validate-devcontainer.yml  # CI/CD pipeline
├── scripts/
│   ├── dev-setup.sh               # Linux/macOS setup
│   └── dev-setup.bat              # Windows setup
├── docker-compose.yml             # Production (unchanged)
├── docker-compose.dev.yml         # Development (new)
├── .dockerignore                  # Optimized for build
├── QUICK_START_DEV.md             # Quick reference
└── DOCKER_COMPOSE_WATCH_GUIDE.md  # Detailed guide
```

---

## 💡 Fitur Berguna Saat Development

### Hot-Reload (Otomatis)
```bash
# Edit api/routes.py → sync instant → restart otomatis
docker compose -f docker-compose.dev.yml --profile dev up --watch
```

### Run Tests Tanpa Restart Services
```bash
docker compose -f docker-compose.dev.yml exec api pytest tests/ -v
```

### Type Check
```bash
docker compose -f docker-compose.dev.yml exec api mypy api/ star_attendance/
```

### Format Code (Ruff)
```bash
docker compose -f docker-compose.dev.yml exec api ruff format api/
```

### Debug Mode (VS Code)
- Set breakpoint
- Eksekusi: `docker compose -f docker-compose.dev.yml exec api python -m debugpy.adapter`
- Attach debugger VS Code

---

## ⚙️ Apa Yang Berbeda (Dev vs Prod)

| Aspek | Production | Development |
|-------|-----------|-------------|
| Config | `docker-compose.yml` | `docker-compose.dev.yml` |
| Cache | Enabled | Disabled |
| Watch | ❌ | ✅ Enabled |
| Healthcheck Interval | 30s | 15s |
| Log Levels | INFO | DEBUG |
| Restart Policy | Strict | More lenient |
| Network | star-asn-network | star-asn-network-dev |

---

## 🔒 Security & Quality

✅ **Docker Scout** - Scan vulnerability saat build (GitHub Actions)  
✅ **Ruff** - Linting & formatting otomatis  
✅ **MyPy** - Type checking untuk bug prevention  
✅ **Pytest** - Unit testing built-in  
✅ **Playwright** - Pre-installed untuk browser automation  

---

## 🎯 Next Steps

### Immediate (Sekarang)
1. Run: `scripts/dev-setup.bat` (Windows) atau `bash scripts/dev-setup.sh` (Linux/macOS)
2. Update `.env` dengan nilai real Anda
3. Start: `docker compose -f docker-compose.dev.yml --profile dev up --watch`

### Short-term (Hari Ini)
1. Buat perubahan di `api/` → lihat hot-reload bekerja
2. Jalankan tests: `docker compose -f docker-compose.dev.yml exec api pytest`
3. Coba format code: `docker compose -f docker-compose.dev.yml exec api ruff format api/`

### Medium-term (Minggu Depan)
1. Setup VS Code Dev Container
2. Configure GitHub Actions untuk CI/CD (sudah ada template)
3. Add pre-commit hooks untuk format otomatis

---

## 📖 Dokumentasi Lengkap

- **Quick Start:** Baca `QUICK_START_DEV.md` (5 menit)
- **Detailed Guide:** Baca `DOCKER_COMPOSE_WATCH_GUIDE.md` (20 menit)
- **Official Docs:**
  - https://docs.docker.com/compose/file-watch/
  - https://containers.dev/
  - https://docs.docker.com/build/cache/

---

## ❓ Troubleshooting

### Error: "Port 8000 already in use"
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Linux/macOS
lsof -i :8000 | grep LISTEN | awk '{print $2}' | xargs kill -9
```

### Error: "File sync not working"
- Pastikan Docker Compose >= 2.20 (`docker compose version`)
- Restart dengan: `docker compose -f docker-compose.dev.yml down && up --watch`

### Error: ".env not found"
```bash
# Auto-create dari setup script
scripts/dev-setup.bat  # Windows
bash scripts/dev-setup.sh  # Linux/macOS
```

---

## 🎉 Selesai!

Anda sekarang punya:
- ✅ Development environment production-like
- ✅ Hot-reload untuk developer experience optimal
- ✅ CI/CD pipeline untuk quality assurance
- ✅ VS Code integration untuk remote development
- ✅ Setup scripts untuk onboarding mudah

**Mulai sekarang:** `scripts/dev-setup.bat` (atau `.sh` di Linux) → `docker compose -f docker-compose.dev.yml --profile dev up --watch`

Enjoy coding! 🚀
