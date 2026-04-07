#!/bin/bash
# deploy.sh - Runs on the EC2 instance

set -euo pipefail

PROJECT_DIR="/home/ubuntu/chatOps"
VENV_DIR="/home/ubuntu/venv"
SERVICE_FILE="/etc/systemd/system/discord-bot.service"

echo "🚀 Starting Deployment for ChatOps..."

# Validate Token exists in the SSH environment
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

# 3. Create or update the .env file securely
echo "🔐 Generating secure .env file..."
cat > "$PROJECT_DIR/.env" << EOF
ENVIRONMENT=production
DISCORD_BOT_TOKEN=$DISCORD_TOKEN
EOF
# Ensure only the ubuntu user can read this file
chmod 600 "$PROJECT_DIR/.env"

# 4. Write the systemd service file
echo "⚙️ Writing systemd service file..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Discord ChatOps Bot
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=$PROJECT_DIR
# Systemd will inject the token from this file into the bot's environment
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

# 6. Check the status to ensure it didn't crash immediately
echo "⏳ Checking service status..."
sleep 2 # Give the bot a moment to start or crash
sudo systemctl --no-pager status discord-bot | grep "Active:"

echo "✅ Deployment Successful!"