# Mafia bot — Oracle Cloud (Ubuntu VM)

1) Papkani serverga yuklang (Windows'dan):
   scp -i kalit.key -r mafia-oracle ubuntu@SERVER_IP:~/mafia-bot
2) Serverga kiring: ssh -i kalit.key ubuntu@SERVER_IP
3) Tokenni yozing: nano ~/mafia-bot/.env  (BOT_TOKEN=...)
4) O'rnating: cd ~/mafia-bot && bash install.sh

Foydali buyruqlar:
  sudo systemctl restart mafia-bot     # qayta ishga tushirish
  sudo systemctl status mafia-bot      # holati
  sudo journalctl -u mafia-bot -f      # loglar

Yangilash: yangi bot.py ni ~/mafia-bot ga yuklang (data/ papkaga tegmang), so'ng
  sudo systemctl restart mafia-bot

Ma'lumotlar: ~/mafia-bot/data/mafia.db — VM diskida, restart/yangilashda o'chmaydi.
Zaxira nusxa: cp ~/mafia-bot/data/mafia.db ~/mafia-backup-$(date +%F).db

Eslatma: foydalanuvchi nomi ubuntu bo'lmasa (masalan opc), mafia-bot.service va .env
ichidagi /home/ubuntu yo'lini o'zgartiring. Webhook kerak emas, bot polling bilan ishlaydi,
portlarni ochish shart emas.
