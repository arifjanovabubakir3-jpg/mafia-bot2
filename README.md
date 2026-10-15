# 🤵🏻 Mafia Bot (Telegram, aiogram 3)

16 rolli Mafia o'yini boti: tun/kun/ovoz berish, do'kon, hamyon, Stars orqali olmos, admin panel.

## Lokal ishga tushirish
```bash
pip install -r requirements.txt
cp .env.example .env     # BOT_TOKEN va OWNER_ID ni to'ldiring
python bot.py
```

## GitHub'ga joylash
```bash
git init
git add .
git commit -m "Mafia bot"
git branch -M main
git remote add origin https://github.com/<login>/<repo>.git
git push -u origin main
```
`.env` fayli `.gitignore` da — tokeningiz GitHub'ga chiqmaydi.

## Render'ga joylash
1. Render → **New → Blueprint** (yoki Web Service) → GitHub repo'ni tanlang (`render.yaml` avtomatik o'qiladi).
2. **Environment** bo'limida kiriting:
   - `BOT_TOKEN` — @BotFather bergan token
   - `OWNER_ID` — sizning Telegram ID'ingiz (@userinfobot yoki botda `/id`). Bir nechta bo'lsa: `111,222`
3. Deploy. Bot `RENDER_EXTERNAL_URL` orqali webhook rejimida o'zi ishga tushadi.

## Muhim eslatmalar
- **Ma'lumotlar bazasi (SQLite)**: Render'ning bepul rejasida fayl tizimi vaqtinchalik — har deployda
  statistika, pul, olmos va to'lovlar **o'chib ketadi**. Doimiy saqlash uchun pullik rejada
  Persistent Disk ulang va `DB_PATH=/var/data/mafia.db` qiling.
- **Bepul reja uxlaydi**: 15 daqiqa so'rov bo'lmasa servis uxlaydi, davom etayotgan o'yinlar
  (xotirada saqlanadi) uziladi. Jiddiy foydalanish uchun pullik reja yoki tashqi ping (UptimeRobot → `/`).
- Botni guruhda **admin** qiling (xabarlarni o'chirish huquqi bilan).
- Ixtiyoriy sozlamalar: `REG_TIME`, `NIGHT_TIME`, `DAY_TIME`, `VOTE_TIME`, `MIN_PLAYERS`, `MAX_PLAYERS`, `DB_PATH`.
