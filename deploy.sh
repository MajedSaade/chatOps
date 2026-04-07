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

# 1. Create the virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Install/Update dependencies
echo "📥 Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 3. Create or update the .env file using the variable passed from GitHub
echo "🔐 Generating .env file..."
cat > "$PROJECT_DIR/.env" << EOF
ENVIRONMENT=production
DISCORD_BOT_TOKEN=$DISCORD_TOKEN
EOF

# 4. Always write the known-good systemd unit for consistent deploys
echo "⚙️ Writing systemd service file..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Discord ChatOps Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/chatOps
ExecStart=/home/ubuntu/venv/bin/python -m app.app
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable discord-bot

# 5. Restart the bot to apply the new code
echo "🔄 Restarting the Discord Bot..."
sudo systemctl daemon-reload
sudo systemctl restart discord-bot
sudo systemctl --no-pager --full status discord-bot | head -n 20

echo "✅ Deployment Successful!"