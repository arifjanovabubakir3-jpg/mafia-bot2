# Mafia bot — ishga tushirish

## VS Code (lokal)
1. Papkani VS Code'da oching (bot.py, .env, requirements.txt bir joyda bo'lsin).
2. `.env` faylini oching va yozing:
   - `BOT_TOKEN=` — @BotFather'dan olingan token
   - `OWNER_ID=` — sizning Telegram ID'ingiz (@userinfobot ga /start yozsangiz beradi)
   (Yoki bot.py tepasidagi `TOKEN_HERE` va `ADMIN_IDS_HERE` ga yozing.)
3. Terminalda:
   - Windows: `run.bat` (ikki marta bosing)
   - Linux/Mac: `bash run.sh`
   yoki qo'lda: `pip install -r requirements.txt` va `python bot.py`
4. Botga /start, guruhga qo'shib admin qiling, `/game` yozing. Admin panel: botga `/admin`.

Python 3.10+ kerak. Baza `mafia.db` avtomatik yaratiladi.

## Render
- GitHub'ga bot.py, requirements.txt, render.yaml yuklang (.env yuklamang!).
- Render → Environment: `BOT_TOKEN`, `OWNER_ID`.
- Bazani saqlash uchun Disk ulab `DB_PATH=/data/mafia.db` qo'ying.

## Admin buyruqlar
`/admin` panel · `/give` istalgan narsa berish · `/giveall` · `/manual on|off` · guruhda `/st`, `/vaqtsiz`
