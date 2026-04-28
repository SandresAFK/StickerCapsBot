# StickerCapsBot

MVP Telegram-бот на `aiogram 3`:
- коллекция фишек из стикеров
- круглый рендер фишек, номинал `⚡`, порядковые номера
- реальные аватарка и ник игрока на картинке
- бой с ботом (50/50 по каждой выбранной фишке)
- энергия для прокачки/добавления фишек
- кнопка тестового сброса коллекции

## Запуск (Windows PowerShell)

```powershell
cd C:\CODING_2026\StickerCapsBot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Заполни `.env`:
- `BOT_TOKEN`
- `DEFAULT_STICKER_SET_NAME` (набор со **статическими** стикерами)

Запуск:

```powershell
.\.venv\Scripts\python.exe -m app
```
