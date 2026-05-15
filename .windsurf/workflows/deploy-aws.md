---
description: Deploy StickerCapsBot to AWS EC2 Free Tier (Singapore)
---

## 1. Создать AWS аккаунт
- Перейди на https://aws.amazon.com → Create account
- Нужна карта Visa/Mastercard (только для верификации, $1 временный холд)
- Выбери план: **Free**

## 2. Запустить EC2 инстанс
- Перейди в **EC2 → Launch Instance** (регион: **ap-southeast-1 Singapore**)
- Name: `stickercapsbot`
- AMI: **Ubuntu Server 22.04 LTS** (Free tier eligible)
- Instance type: **t2.micro** (Free tier)
- Key pair: Create new → `stickercapsbot-key` → Download `.pem` файл, сохрани
- Security group: Allow **SSH (22)** from Anywhere
- Storage: **20 GB gp3**
- Launch instance

## 3. Подключиться по SSH
```bash
chmod 400 stickercapsbot-key.pem
ssh -i stickercapsbot-key.pem ubuntu@<PUBLIC_IP>
```

## 4. Установить зависимости на сервере
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git
```

## 5. Клонировать репозиторий
```bash
git clone https://github.com/SandresAFK/StickerCapsBot.git
cd StickerCapsBot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 6. Создать .env файл
```bash
nano .env
```
Вставить:
```
BOT_TOKEN=your_token_here
DEFAULT_STICKER_SET_NAME=your_sticker_set
ADMIN_ID=your_telegram_id
```
Сохранить: Ctrl+O → Enter → Ctrl+X

## 7. Создать директорию данных
```bash
mkdir -p data
```

## 8. Создать systemd сервис (автозапуск)
```bash
sudo nano /etc/systemd/system/stickercapsbot.service
```
Вставить:
```ini
[Unit]
Description=StickerCapsBot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/StickerCapsBot
ExecStart=/home/ubuntu/StickerCapsBot/.venv/bin/python -m app
Restart=always
RestartSec=5
EnvironmentFile=/home/ubuntu/StickerCapsBot/.env

[Install]
WantedBy=multi-user.target
```
Сохранить: Ctrl+O → Enter → Ctrl+X

## 9. Запустить бот
```bash
sudo systemctl daemon-reload
sudo systemctl enable stickercapsbot
sudo systemctl start stickercapsbot
sudo systemctl status stickercapsbot
```

## 10. Проверить логи
```bash
journalctl -u stickercapsbot -f
```

## Обновление бота (после git push)
```bash
cd /home/ubuntu/StickerCapsBot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart stickercapsbot
```
