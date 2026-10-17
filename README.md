# Mafia Bot (aiogram 3)

## GitHub'ga yuklanadigan fayllar
bot.py, requirements.txt, .python-version, .gitignore, .env.example, README.md

## Render sozlamalari (Web Service)
| Maydon | Qiymat |
|---|---|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python bot.py` |
| Health Check Path | `/` |

### Environment o'zgaruvchilari
| Kalit | Qiymat |
|---|---|
| BOT_TOKEN | @BotFather bergan token (majburiy) |
| OWNER_ID | Telegram ID raqamingiz (botga /id yozsangiz ko'rasiz). Bir nechta bo'lsa vergul bilan |
| DB_PATH | (ixtiyoriy) Persistent Disk bo'lsa `/data/mafia.db` |

`PORT` va `RENDER_EXTERNAL_URL` ni Render o'zi beradi — qo'shmang.

## Muhim eslatmalar
- Bir token bilan bir vaqtda faqat bitta joyda ishga tushiring. Kompyuterda ham, Renderda ham
  ishlasa, webhook/polling bir-birini buzadi.
- Render bepul tarifida disk vaqtinchalik: har deploy/restartda `mafia.db` (pul, olmos, reyting)
  o'chadi. Doimiy saqlash uchun pullik tarifda Persistent Disk ulab, `DB_PATH=/data/mafia.db` qiling.
- Faol o'yinlar xotirada turadi: bot qayta ishga tushsa, davom etayotgan o'yinlar to'xtaydi.
- Bepul tarifda servis uxlab qolmasligi uchun bot o'zini har 9 daqiqada chaqirib turadi
  (`KEEPALIVE=0` bilan o'chiriladi). Ishonchliroq yo'l: UptimeRobot'da `https://SERVIS.onrender.com/` ni
  har 5 daqiqada tekshirtiring.
- Telegram Stars to'lovi uchun aiogram 3.13+ kerak (requirements.txt shuni ta'minlaydi).
