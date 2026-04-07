#!/bin/bash
# deploy.sh - Runs on the EC2 instance

set -euo pipefail

PROJECT_DIR="/home/ubuntu/chatOps"
VENV_DIR="/home/ubuntu/venv"
SERVICE_FILE="/etc/systemd/system/discord-bot.service"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3}"
OLLAMA_CHAT_URL="${OLLAMA_CHAT_URL:-http://127.0.0.1:11434/api/chat}"
OLLAMA_TIMEOUT_SECONDS="${OLLAMA_TIMEOUT_SECONDS:-60}"

echo "🚀 Starting Deployment for ChatOps..."

if [ -z "${DISCORD_TOKEN:-}" ]; then
    echo "❌ DISCORD_TOKEN is missing. Aborting deployment."
    exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ Project directory not found: $PROJECT_DIR"
    exit 1
fi

# 1. The Fix: Check for the pip executable, not just the directory
if [ ! -f "$VENV_DIR/bin/pip" ]; then
    echo "📦 Creating/Rebuilding virtual environment..."
    # Wipe the folder in case it's a broken/empty shell from a previous failure
    rm -rf "$VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

# 2. Install/Update dependencies
echo "📥 Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 3. Install and start Ollama for local LLM support
echo "🧠 Ensuring Ollama is installed and running..."
if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
sudo systemctl enable --now ollama

echo "📦 Pulling Ollama model: $OLLAMA_MODEL"
ollama pull "$OLLAMA_MODEL"

# 4. Create or update the .env file securely
echo "🔐 Generating secure .env file..."
cat > "$PROJECT_DIR/.env" << EOF
ENVIRONMENT=production
DISCORD_BOT_TOKEN=$DISCORD_TOKEN
OLLAMA_MODEL=$OLLAMA_MODEL
OLLAMA_CHAT_URL=$OLLAMA_CHAT_URL
OLLAMA_TIMEOUT_SECONDS=$OLLAMA_TIMEOUT_SECONDS
EOF
chmod 600 "$PROJECT_DIR/.env"

# 5. Write the systemd service file (Using your exact specifications)
echo "⚙️ Writing systemd service file..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Discord ChatOps Bot
After=network.target ollama.service
Wants=ollama.service

[Service]
User=ubuntu
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$VENV_DIR/bin/python -m app.app
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 6. Reload, Enable, and Restart the bot
echo "🔄 Restarting the Discord Bot..."
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl restart discord-bot

echo "⏳ Checking service status..."
sleep 2
sudo systemctl --no-pager status discord-bot | grep "Active:"

echo "✅ Deployment Successful!"