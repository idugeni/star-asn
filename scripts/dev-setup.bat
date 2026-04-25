@echo off
REM Star ASN Development Setup Script (Windows)
REM Usage: scripts\dev-setup.bat

setlocal enabledelayedexpansion

echo.
echo 🚀 Star ASN Development Setup
echo ==========================================

REM Check Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker not installed
    exit /b 1
)
for /f "tokens=3" %%i in ('docker --version') do set DOCKER_VERSION=%%i
echo ✓ Docker %DOCKER_VERSION%

REM Check Docker Compose
docker compose version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker Compose not found
    exit /b 1
)
for /f "tokens=4" %%i in ('docker compose version') do set COMPOSE_VERSION=%%i
echo ✓ Docker Compose %COMPOSE_VERSION%

REM Check .env file
if not exist .env (
    echo ⚠️  .env file not found
    echo    Creating .env template...
    (
        echo # API Configuration
        echo INTERNAL_API_URL=http://api:11800
        echo INTERNAL_API_TOKEN=your_token_here
        echo MASTER_SECURITY_KEY=your_key_here
        echo.
        echo # Telegram Bot
        echo TELEGRAM_BOT_TOKEN=your_bot_token_here
        echo.
        echo # Database
        echo DATABASE_URL=postgresql://user:password@db:5432/star_asn
        echo.
        echo # Supabase (if applicable^)
        echo SUPABASE_URL=your_supabase_url
        echo SUPABASE_KEY=your_supabase_key
    ) > .env
    echo    Created .env - please update with your values
) else (
    echo ✓ .env exists
)

REM Pull latest base images
echo.
echo 📦 Pulling latest base images (no cache^)...
docker compose -f docker-compose.dev.yml --profile dev build --pull --no-cache api

echo.
echo ✅ Setup complete!
echo.
echo 📖 Next steps:
echo    1. Update .env with your configuration
echo    2. Run: docker compose -f docker-compose.dev.yml --profile dev up --watch
echo    3. Or open in VS Code Dev Container: F1 -^> 'Reopen in Container'
echo.
echo 💡 For help: type QUICK_START_DEV.md
echo.

endlocal
