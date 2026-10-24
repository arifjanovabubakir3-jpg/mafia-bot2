#!/bin/bash
# Ishlatish: papkani serverga ~/mafia-bot ga yuklang, so'ng:  bash install.sh
set -e
cd ~/mafia-bot
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
mkdir -p data
sudo cp mafia-bot.service /etc/systemd/system/mafia-bot.service
sudo systemctl daemon-reload
sudo systemctl enable mafia-bot
sudo systemctl restart mafia-bot
echo "✅ Tayyor. Loglar: sudo journalctl -u mafia-bot -f"
