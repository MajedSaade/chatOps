#!/bin/bash
# deploy.sh - Runs on the EC2 instance

set -euo pipefail

PROJECT_DIR="/home/ubuntu/chatOps"
VENV_DIR="/home/ubuntu/venv"
SERVICE_FILE="/etc/systemd/system/discord-bot.service"

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

# 3. Create or update the .env file securely
echo "🔐 Generating secure .env file..."
cat > "$PROJECT_DIR/.env" << EOF
ENVIRONMENT=production
DISCORD_BOT_TOKEN=$DISCORD_TOKEN
EOF
chmod 600 "$PROJECT_DIR/.env"

# 4. Write the systemd service file (Using your exact specifications)
echo "⚙️ Writing systemd service file..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Discord ChatOps Bot
After=network.target

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

# 5. Reload, Enable, and Restart the bot
echo "🔄 Restarting the Discord Bot..."
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl restart discord-bot

echo "⏳ Checking service status..."
sleep 2
sudo systemctl --no-pager status discord-bot | grep "Active:"

echo "✅ Deployment Successful!"