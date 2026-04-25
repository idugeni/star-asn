#!/bin/bash

# Star ASN Development Setup Script
# Usage: ./scripts/dev-setup.sh

set -e

echo "🚀 Star ASN Development Setup"
echo "=========================================="

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not installed"
    exit 1
fi
echo "✓ Docker $(docker --version | awk '{print $3}')"

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose not found"
    exit 1
fi
COMPOSE_VERSION=$(docker compose version | awk '{print $4}')
echo "✓ Docker Compose $COMPOSE_VERSION"

# Verify version >= 2.20 for watch mode
MAJOR=$(echo $COMPOSE_VERSION | cut -d. -f1)
MINOR=$(echo $COMPOSE_VERSION | cut -d. -f2)
if [ "$MAJOR" -lt 2 ] || ([ "$MAJOR" -eq 2 ] && [ "$MINOR" -lt 20 ]); then
    echo "⚠️  Docker Compose $COMPOSE_VERSION detected"
    echo "   Watch mode requires >= 2.20"
    echo "   Install latest: https://docs.docker.com/compose/install/"
fi

# Check .env file
if [ ! -f .env ]; then
    echo "⚠️  .env file not found"
    echo "   Creating .env template..."
    cat > .env << 'EOF'
# API Configuration
INTERNAL_API_URL=http://api:11800
INTERNAL_API_TOKEN=your_token_here
MASTER_SECURITY_KEY=your_key_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Database
DATABASE_URL=postgresql://user:password@db:5432/star_asn

# Supabase (if applicable)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
EOF
    echo "   Created .env - please update with your values"
fi
echo "✓ .env exists"

# Pull latest base images
echo ""
echo "📦 Pulling latest base images (no cache)..."
docker compose -f docker-compose.dev.yml --profile dev build --pull --no-cache api 2>&1 | tail -5

echo ""
echo "✅ Setup complete!"
echo ""
echo "📖 Next steps:"
echo "   1. Update .env with your configuration"
echo "   2. Run: docker compose -f docker-compose.dev.yml --profile dev up --watch"
echo "   3. Or open in VS Code Dev Container: F1 → 'Reopen in Container'"
echo ""
echo "💡 For help: cat QUICK_START_DEV.md"
