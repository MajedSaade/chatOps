---
description: Run the Discord bot locally
---
// turbo-all

## Prerequisites
- `.env` filled in with real Discord tokens
- Python venv activated
- **Message Content Intent** enabled in Discord Developer Portal → Bot → Privileged Gateway Intents
- **Interactions Endpoint URL** in Discord Developer Portal must be **blank** (remove it if set)

## Steps

1. Activate the virtual environment
```bash
source /home/majed/AntiGround/DiscordApp/venv/bin/activate
```

2. Start the bot
```bash
cd /home/majed/AntiGround/DiscordApp && python bot.py
```

3. Test slash commands: `/cluster-health`, `/logs`, `/aws-cost`
4. Test messages: DM the bot or @mention it with "hi" or "how are you"
