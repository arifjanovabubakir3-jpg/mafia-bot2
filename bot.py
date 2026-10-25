# -*- coding: utf-8 -*-
"""
🤵🏻 MAFIA BOT — Telegram (aiogram 3.x)
- 16 ta rol, tun/kun/ovoz berish, DM orqali tungi harakatlar
- Shaxsiy chatda ham, guruhda ham menyu
- Render uchun tayyor (webhook yoki polling, avtomatik)

"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import tempfile
import time
import traceback
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import (
    JOIN_TRANSITION,
    ChatMemberUpdatedFilter,
    Command,
    CommandObject,
    CommandStart,
)
from aiogram.types import (
    FSInputFile,
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    ChatMemberUpdated,
    ErrorEvent,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    User,
    WebAppInfo,
    MenuButtonWebApp,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import ClientSession, ClientTimeout, web

# ───────── 🎨 Rangli tugmalar (Bot API: style = primary / success / danger) ─────────
STYLE_BTN = os.getenv("STYLE_BTN", "1").strip().lower() not in ("0", "false", "no")
_ST_DANGER = ("❌", "🚫", "⛔", "🗑", "Bekor", "O'chir", "Chiqish", "Ban", "Taqiq")
_ST_SUCCESS = ("✅", "➕", "Qo'shil", "Sotib", "Boshlash", "Tasdiq", "🎮", "👍", "Yoqish", "Olish", "Bonus")
_ST_PRIMARY = ("🛒", "🛍", "👤", "👛", "🏆", "🎭", "📖", "🌐", "👑", "✨", "💎", "🎒", "📊", "⚙", "🔄", "Do'kon", "Profil")


def _btn_style(text: str):
    for k in _ST_DANGER:
        if k in text:
            return "danger"
    for k in _ST_SUCCESS:
        if k in text:
            return "success"
    for k in _ST_PRIMARY:
        if k in text:
            return "primary"
    return None


class InlineKeyboardBuilder(_IKB):
    """Oddiy builder, lekin tugma matniga qarab rang (style) beradi."""

    def button(self, *, text, **kw):
        if STYLE_BTN and "style" not in kw and not any(w in text for w in ("Orqaga", "◀", "⬅")):
            st = _btn_style(text)
            if st:
                kw["style"] = st
        return super().button(text=text, **kw)


# ───────────────────────── SOZLAMALAR ─────────────────────────
def _load_env(path=".env"):
    """Lokal ishlatish uchun: .env fayldan o'qiydi (Render'da kerak emas)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_env()

# ▼▼▼ LOKAL (VS Code) UCHUN: token va admin ID'ni shu yerga yozsangiz ham bo'ladi (yoki .env faylga) ▼▼▼
TOKEN_HERE = ""        # masalan: "123456789:AAH...."  (@BotFather bergan token)
ADMIN_IDS_HERE = []    # masalan: [123456789, 987654321]  (@userinfobot dan olingan ID'lar)
# ▲▲▲ Render'da bularni bo'sh qoldiring — Environment orqali beriladi ▲▲▲

# Token va owner ID faqat muhit o'zgaruvchilaridan olinadi (GitHub'ga sir yozilmaydi).
# Lokal: .env fayl, Render: Dashboard > Environment.
BOT_TOKEN = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TOKEN") or TOKEN_HERE or "") \
    .strip().strip('"').strip("'").strip()
# Bir nechta owner bo'lsa vergul bilan: 111,222
OWNER_IDS = {8773630118} | {int(x) for x in ADMIN_IDS_HERE} | {int(x) for x in re.split(r"[,\s]+", os.getenv("OWNER_ID", "")) if x.lstrip("-").isdigit()}
OWNER_IDS.discard(123456789)  # namuna ID hisobga olinmaydi
PORT = int(os.getenv("PORT", "10000"))
BASE_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
if not BASE_URL and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
    BASE_URL = "https://" + os.getenv("RENDER_EXTERNAL_HOSTNAME").strip()
if BASE_URL and not BASE_URL.startswith("http"):
    BASE_URL = "https://" + BASE_URL
# USE_POLLING=1 bo'lsa Render'da ham polling rejimi ishlatiladi (webhook o'rniga)
if os.getenv("USE_POLLING", "").strip().lower() in ("1", "true", "yes"):
    BASE_URL = ""
# Render bepul tarifida bot uxlab qolmasligi uchun o'zini chaqirib turadi (KEEPALIVE=0 bilan o'chiriladi)
KEEPALIVE = os.getenv("KEEPALIVE", "1").strip().lower() not in ("0", "false", "no")
DB_PATH = os.getenv("DB_PATH", "mafia.db")

REG_TIME = int(os.getenv("REG_TIME", "120"))      # ro'yxatga olish (soniya)
NIGHT_TIME = int(os.getenv("NIGHT_TIME", "50"))   # tun
DAY_TIME = int(os.getenv("DAY_TIME", "60"))       # muhokama
VOTE_TIME = int(os.getenv("VOTE_TIME", "40"))     # ovoz berish
MIN_PLAYERS = int(os.getenv("MIN_PLAYERS", "4"))
MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", "60"))
CONFIRM_TIME = int(os.getenv("CONFIRM_TIME", "30"))   # osishni tasdiqlash (👍/👎) vaqti
LAST_WORD_TIME = int(os.getenv("LAST_WORD_TIME", "45"))  # oxirgi so'z yozish vaqti

if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", BOT_TOKEN):
    raise SystemExit(
        "❌ BOT_TOKEN topilmadi yoki noto'g'ri.\n"
        "   Render: Dashboard → servis → Environment → BOT_TOKEN = @BotFather bergan token.\n"
        "   Lokal: bot.py yonida .env fayl yarating: BOT_TOKEN=123456:ABC...")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mafia")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
BOT_USERNAME = ""

# ───────────────────────── ROLLAR (16 ta) ─────────────────────────
# kalit: (nomi, jamoa, tavsif)
ROLES = {
    "civ": ("👨🏼 Tinch axoli", "town",
            "Siz oddiy fuqarosiz. Kunduzi muhokama qilib, ovoz berib mafiyani toping."),
    "kom": ("🕵🏻‍♂️ Komissar", "town",
            "Har kecha bitta o'yinchini tekshirasiz (mafiyami yoki yo'qmi) yoki otib o'ldirasiz."),
    "ser": ("👮🏻‍♂️ Serjant", "town",
            "Komissarning yordamchisi. Komissar o'lsa, uning o'rnini egallaysiz."),
    "doc": ("👨🏻‍⚕️ Doktor", "town",
            "Har kecha bitta o'yinchini davolaysiz. O'zingizni faqat bir marta davolay olasiz."),
    "luck": ("🤞 Omadli", "town",
             "Sizga hujum bo'lsa, 50% ehtimol bilan omon qolasiz."),
    "kam": ("💣 Kamikaze", "town",
            "Agar sizni osishsa, sizga ovoz berganlardan birini o'zingiz bilan olib ketasiz."),
    "bomj": ("🧙‍♂️ Daydi", "town",
             "Kechasi bitta o'yinchi eshigiga borasiz va u yerga yana kimlar kelganini ko'rasiz."),
    "kez": ("💃 Mashuqa", "town",
            "Har kecha bitta o'yinchini band qilasiz — u o'sha tunda hech qanday harakat qila olmaydi."),
    "guard": ("🛡 Soqchi", "town",
              "Bitta o'yinchini qo'riqlaysiz. Unga hujum bo'lsa, uning o'rniga siz o'lasiz."),
    "hunter": ("🏹 Mergan", "town",
               "Agar sizni tunda o'ldirishsa, qotilingizni o'zingiz bilan olib ketasiz."),
    "mafia": ("🤵🏻 Mafia", "mafia",
              "Mafiya a'zosisiz. Har kecha jamoa bilan birga bitta odamni o'ldirasiz."),
    "don": ("🎩 Don", "mafia",
            "Mafiya boshlig'i. Ovozlar teng bo'lsa, sizning ovozingiz hal qiladi. Komissar sizni tinch aholi deb ko'radi."),
    "adv": ("👨🏼‍💼 Advokat", "mafia",
            "Har kecha bitta mafiya a'zosini himoya qilasiz — komissar tekshirsa, u tinch aholi bo'lib ko'rinadi."),
    "spy": ("🤵🏻‍♀️ Donning xotini", "mafia",
            "Har kecha bitta o'yinchining aniq rolini bilib olasiz va uni mafiya jamoasiga oshkor qilasiz."),
    "man": ("🔪 Manyak", "solo",
            "Yolg'iz o'ynaysiz. Har kecha bitta odamni o'ldirasiz. Oxirgi tirik qolsangiz — g'alaba."),
    "suit": ("🤦🏼 Suitsid", "solo",
             "Sizning maqsadingiz — kunduzi osilish. Sizni osishsa, g'alaba qozonasiz!"),
    # ---- yangi rollar ----
    "pois": ("🧪 Zaharchi", "mafia",
             "Har kecha bitta o'yinchini zaharlaysiz — u keyingi tunda o'ladi, agar doktor davolamasa."),
    "hypno": ("🌀 Gipnozchi", "mafia",
              "Har kecha bitta o'yinchini gipnoz qilasiz — u ertasi kuni ovoz bera olmaydi."),
    "thief": ("🥷 O'g'ri", "mafia",
              "Har kecha bitta o'yinchining hamyonidan 30💵 gacha o'g'irlaysiz."),
    "snip": ("🎯 Snayper", "town",
             "O'yin davomida faqat 1 marta tunda bitta o'yinchini otib o'ldirasiz."),
    "priest": ("⛪️ Ruhoniy", "town",
               "O'yin davomida 1 marta oldin o'lgan bitta o'yinchini tiriltirasiz."),
    "jail": ("⛓ Qamoqchi", "town",
             "Har kecha bitta o'yinchini qamaysiz: u harakat qila olmaydi, lekin unga hujum ham o'tmaydi."),
    "judge": ("⚖️ Sudya", "town",
              "O'yin davomida 1 marta veto qo'yasiz — keyingi kunduzgi osish bekor bo'ladi."),
    "mayor": ("🏛 Mer", "town",
              "Kunduzgi ovoz berishda sizning ovozingiz 2 ta hisoblanadi."),
    "track": ("🐾 Izquvar", "town",
              "Har kecha bitta o'yinchini kuzatasiz — u kimning uyiga borganini bilasiz."),
    "bull": ("💪 Polvon", "town",
             "Birinchi o'limcha hujumdan 1 marta omon qolasiz."),
    "nurse": ("👩🏻‍⚕️ Hamshira", "town",
              "Doktor halok bo'lsa, uning o'rniga Doktor bo'lasiz."),
    # ---- "tez orada" rollari (endi ishlaydi) ----
    "killer": ("🗡 Qotil", "mafia",
               "Mafiya jamoasi a'zosi. Mafiyaning umumiy hujumidan tashqari, har 2 tunda bir marta o'zingiz alohida bitta o'yinchini o'ldirasiz."),
    "swindler": ("🃏 Aferist", "mafia",
                 "Har kecha bitta tinch aholini tanlaysiz — Komissar uni o'sha tun tekshirsa, mafiya deb ko'radi."),
    "miner": ("☠️ Minior", "town",
              "Bitta o'yinchining eshigiga mina qo'yasiz. Unga hujum qilgan odam mina portlab halok bo'ladi, nishon esa omon qoladi. Mina portlamaguncha turadi."),
    "chem": ("🧑‍🔬 Kimyogar", "town",
             "Har kecha bitta o'yinchiga eliksir berasiz: zahar va zombi infeksiyasi yo'qoladi, joniga +50❤️ qo'shiladi."),
    "fool": ("👨🏻‍🦲 Tentak", "town",
             "Siz tinch aholisiz, lekin Komissar sizni tekshirsa, mafiya deb ko'radi. Ehtiyot bo'ling!"),
    "cham": ("🦎 Buqalamun", "town",
             "Har kecha bitta o'yinchini tanlaysiz. Agar u o'lsa (tunda yoki kunduzi), uning rolini o'zingiz olasiz."),
    "seller": ("🎁 Sotuvchi", "town",
               "Har kecha bitta o'yinchining oldiga borasiz: unga do'kon ochasiz (🛡 Himoya va boshqa narsalar). Sotilgan har narxning 20% i sizga."),
    "fan": ("🔮 Muxlis", "town",
            "O'yin boshida Komissar kimligini bilib olasiz (agar o'yinda Komissar bo'lsa)."),
    "rais": ("💰 Rais", "town",
             "Har kecha bitta o'yinchiga 100💵 berasiz. O'yin mukofotingiz 2 barobar bo'ladi."),
    "mage": ("🧙‍♀️ Sehrgar", "town",
             "O'yin davomida 1 marta bitta o'yinchi bilan rollaringizni almashtirasiz — siz uning rolini olasiz, u esa Sehrgar bo'ladi."),
    "gent": ("🎖 Janob", "town",
             "Har kecha bitta o'yinchiga ta'zim qilasiz: u ertangi kunduzgi ovoz berishda osilmaydi."),
    "sheep": ("🐑 Qo'y", "town",
              "Tungi harakatingiz yo'q. Agar mafiya sizni o'ldirsa, mafiya jamoasi keyingi tunda qilichini ko'tara olmaydi."),
    "zombi": ("🧟 Zombi", "solo",
              "Yakka o'ynaysiz. Har kecha bir o'yinchini tishlaysiz — u zombiga aylanadi va tungi harakatini yo'qotadi. "
              "Hamma tirik o'yinchi zombi bo'lsa, g'alaba. Doktor/Kimyogar davolasa, qaytadi. Siz o'lsangiz, hamma tuzaladi."),
}

# kechasi harakat qiladigan rollar}

# kechasi harakat qiladigan rollar va ruxsat etilgan harakat turlari
ROLE_KINDS = {
    "mafia": {"k"}, "don": {"k"}, "adv": {"a"}, "spy": {"j"},
    "kom": {"c", "s"}, "doc": {"h"}, "kez": {"b"}, "guard": {"g"},
    "bomj": {"v"}, "man": {"m"},
    "pois": {"p"}, "hypno": {"w"}, "thief": {"t"}, "snip": {"z"},
    "priest": {"y"}, "jail": {"i"}, "judge": {"u"}, "track": {"f"},
    "killer": {"q"}, "swindler": {"e"}, "miner": {"o"}, "chem": {"C"}, "cham": {"l"},
    "seller": {"d"}, "rais": {"R"}, "mage": {"W"}, "gent": {"r"}, "zombi": {"Z"},
}
ONCE_ROLES = {"snip", "priest", "judge", "mage"}   # butun o'yinda 1 marta
MAFIA_KINDS = ("k", "p", "w", "t", "q", "e")        # mafiya jamoasiga bildiriladigan harakatlar
PROMPTS = {
    "k": "🔪 Kimni o'ldiramiz?",
    "a": "👨🏼‍💼 Kimni himoya qilasiz? (u tekshiruvda tinch aholi bo'lib ko'rinadi)",
    "j": "🤵🏻‍♀️ Kimning rolini bilmoqchisiz? (mafiya jamoasiga oshkor qilinadi)",
    "c": "🔍 Kimni tekshirasiz?",
    "s": "🔫 Kimni otasiz?",
    "h": "💉 Kimni davolaysiz?",
    "b": "💃 Kimni band qilasiz?",
    "g": "🛡 Kimni qo'riqlaysiz?",
    "v": "🧙‍♂️ Kimning uyiga borasiz?",
    "m": "🔪 Kimni o'ldirasiz?",
    "p": "🧪 Kimni zaharlaysiz?",
    "w": "🌀 Kimni gipnoz qilasiz? (ertaga ovoz bera olmaydi)",
    "t": "🥷 Kimning cho'ntagini kovlaysiz?",
    "z": "🎯 Kimni otasiz? (butun o'yinda 1 marta!)",
    "y": "⛪️ Kimni tiriltirasiz? (butun o'yinda 1 marta!)",
    "i": "⛓ Kimni qamaysiz?",
    "u": "⚖️ Keyingi kunduzgi osishga veto qo'yasizmi? (butun o'yinda 1 marta)",
    "f": "🐾 Kimni kuzatasiz?",
    "o": "☠️ Kimning eshigiga mina qo'yasiz?",
    "q": "🗡 Kimni o'zingiz alohida o'ldirasiz? (har 2 tunda 1 marta)",
    "e": "🃏 Kimni Komissarga mafiya qilib ko'rsatamiz?",
    "C": "🧑‍🔬 Kimga eliksir berasiz?",
    "l": "🦎 Kimning rolini olmoqchisiz? (u o'lsa, uning roli sizga o'tadi)",
    "d": "🛍 Kimning oldiga do'kon ochasiz?",
    "R": "💰 Kimga 100💵 berasiz?",
    "W": "🧙‍♀️ Kim bilan rolingizni almashtirasiz? (butun o'yinda 1 marta)",
    "r": "🎖 Kimga ta'zim qilasiz? (u ertaga osilmaydi)",
    "Z": "🧟 Kimni tishlaysiz?",
}


# ── rollar ro'yxati: tugmalar, bosilsa qisqa ma'lumot (popup) chiqadi ──
ROLE_POPUP = {
    "civ": "Siz tinch aholi tarafidasiz. Kunduzi muhokama qilib, ovoz berish orqali mafiyani toping.",
    "kom": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchini tekshirasiz yoki otib o'ldirasiz.",
    "ser": "Siz tinch aholi tarafidasiz. Komissarning yordamchisisiz — u o'lsa, uning o'rnini egallaysiz.",
    "doc": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchini davolaysiz. O'zingizni faqat bir marta davolay olasiz.",
    "luck": "Siz tinch aholi tarafidasiz. Sizga hujum bo'lsa, 50% ehtimol bilan omon qolasiz.",
    "kam": "Siz tinch aholi tarafidasiz. Sizni osishsa, sizga ovoz berganlardan birini o'zingiz bilan olib ketasiz.",
    "bomj": "Siz tinch aholi tarafidasiz. Tunda bitta o'yinchining uyiga borib, u yerga yana kimlar kelganini ko'rasiz.",
    "kez": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchini band qilasiz — u tunda hech narsa qila olmaydi.",
    "guard": "Siz tinch aholi tarafidasiz. Bitta o'yinchini qo'riqlaysiz: unga hujum bo'lsa, uning o'rniga siz o'lasiz.",
    "hunter": "Siz tinch aholi tarafidasiz. Sizni tunda o'ldirishsa, qotilingizni ham o'zingiz bilan olib ketasiz.",
    "mafia": "Siz mafialar tarafidasiz. Har kecha jamoangiz bilan birga bitta odamni o'ldirasiz.",
    "don": "Siz mafialar tarafidasiz. Ovozlar teng bo'lsa, sizniki hal qiladi. Komissar sizni tinch aholi deb ko'radi.",
    "adv": "Siz mafialar tarafidasiz. Har kecha bitta mafiya a'zosini himoya qilasiz — komissar uni tinch aholi deb ko'radi.",
    "spy": "Siz mafialar tarafidasiz. Siz tunda xohlagan bitta o'yinchining rolini bilishingiz va uni mafialar uchun oshkor qilishingiz mumkin.",
    "man": "Siz yakka o'ynaysiz. Har kecha bitta odamni o'ldirasiz. Oxirgi tirik qolsangiz — g'alaba.",
    "suit": "Siz yakka o'ynaysiz. Maqsadingiz — kunduzi osilish. Sizni osishsa, g'alaba qozonasiz!",
    "pois": "Siz mafialar tarafidasiz. Har kecha bitta o'yinchini zaharlaysiz — u keyingi tunda o'ladi, doktor davolasa qutuladi.",
    "hypno": "Siz mafialar tarafidasiz. Bitta o'yinchini gipnoz qilasiz — u ertasi kuni ovoz bera olmaydi.",
    "thief": "Siz mafialar tarafidasiz. Har kecha bitta o'yinchidan 30💵 gacha o'g'irlaysiz. Komissar sizni mafiya deb ko'radi.",
    "snip": "Siz tinch aholi tarafidasiz. O'yin davomida faqat 1 marta tunda bitta o'yinchini otib o'ldirasiz.",
    "priest": "Siz tinch aholi tarafidasiz. O'yin davomida 1 marta o'lgan bitta o'yinchini tiriltirasiz.",
    "jail": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchini qamaysiz: u harakat qila olmaydi, unga hujum ham o'tmaydi.",
    "judge": "Siz tinch aholi tarafidasiz. O'yinda 1 marta veto qo'yasiz — keyingi kunduzgi osish bekor bo'ladi.",
    "mayor": "Siz tinch aholi tarafidasiz. Ovoz berishda sizning ovozingiz 2 ta hisoblanadi.",
    "track": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchini kuzatasiz — u kimning uyiga borganini bilasiz.",
    "bull": "Siz tinch aholi tarafidasiz. O'limcha hujumdan 1 marta omon qolasiz.",
    "nurse": "Siz tinch aholi tarafidasiz. Doktor halok bo'lsa, uning o'rniga Doktor bo'lasiz.",
    "killer": "Siz mafialar tarafidasiz. Jamoa hujumidan tashqari, har 2 tunda bir marta o'zingiz alohida o'ldirasiz.",
    "swindler": "Siz mafialar tarafidasiz. Tinch aholidan birini Komissarga mafiya qilib ko'rsatasiz.",
    "miner": "Siz tinch aholi tarafidasiz. Eshikka mina qo'yasiz: unga hujum qilgan o'ladi, nishon omon qoladi.",
    "chem": "Siz tinch aholi tarafidasiz. Eliksir: zahar va zombi infeksiyasini yo'qotadi, +50❤️ beradi.",
    "fool": "Siz tinch aholi tarafidasiz, lekin Komissar sizni mafiya deb ko'radi.",
    "cham": "Siz tinch aholi tarafidasiz. Tanlagan o'yinchingiz o'lsa, uning rolini olasiz.",
    "seller": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchiga do'kon ochasiz: Himoya va boshqa narsalarni sotasiz (20% foyda sizga).",
    "fan": "Siz tinch aholi tarafidasiz. O'yin boshida Komissar kimligini bilasiz.",
    "rais": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchiga 100💵 berasiz. O'yin mukofoti 2 barobar.",
    "mage": "Siz tinch aholi tarafidasiz. 1 marta bitta o'yinchi bilan rollarni almashtirasiz.",
    "gent": "Siz tinch aholi tarafidasiz. Har kecha bitta o'yinchi ertangi kunduzgi osishdan himoyalanadi.",
    "sheep": "Siz tinch aholi tarafidasiz. Mafiya sizni o'ldirsa, ular keyingi tunda hujum qila olmaydi.",
    "zombi": "Siz yakka o'ynaysiz. Tishlagan o'yinchingiz zombiga aylanadi. Hamma zombi bo'lsa — g'alaba.",
}
# hali o'yinda ishlamaydigan rollar (faqat ro'yxatda ko'rinadi)
SOON_ROLES = {}
SOON_TEXT = "Bu rol tez orada o'yinga qo'shiladi."
ROLE_GRID = ["civ", "don", "mafia", "man", "kom", "doc", "ser", "bomj", "kez", "adv", "suit", "killer",
             "kam", "swindler", "miner", "spy", "zombi", "chem", "fool", "cham", "seller", "fan",
             "luck", "rais", "mage", "hunter", "gent", "sheep", "guard",
             "pois", "hypno", "thief", "snip", "priest", "jail", "judge", "mayor", "track", "bull", "nurse"]
ROLES_HEAD = "🎭 <b>Rollar ro'yxati:</b>\nRol ustiga bosing — qisqacha ma'lumot chiqadi."
# 🎭 Aktiv rol sifatida tanlash mumkin bo'lgan rollar
ACTIVE_ROLES = ["kom", "doc", "ser", "luck", "kam", "bomj", "kez", "guard", "hunter",
                "mafia", "don", "adv", "spy", "man", "suit"]


def role_display(key: str) -> str:
    return ROLES[key][0] if key in ROLES else SOON_ROLES[key]


def roles_kb():
    kb = InlineKeyboardBuilder()
    for k in ROLE_GRID:
        kb.button(text=role_display(k), callback_data=f"rl:{k}")
    kb.adjust(2)
    return kb.as_markup()


def role_popup(key: str) -> str:
    body = ROLE_POPUP.get(key, SOON_TEXT)
    return f"Siz - {role_display(key)}!\n\n{body}"[:200]   # Telegram oynasi: eng ko'pi 200 belgi


@router.callback_query(F.data.startswith("rl:"))
async def role_info_cb(cq: CallbackQuery):
    key = cq.data.split(":", 1)[1]
    if key not in ROLES and key not in SOON_ROLES:
        return await cq.answer()
    await cq.answer(role_popup(key), show_alert=True)


def rname(role: str) -> str:
    return ROLES[role][0]


def team(role: str) -> str:
    return ROLES[role][1]


# ───────────────────── ZAXIRA (BACKUP) VA TIKLASH ─────────────────────
# Render bepul tarifida disk vaqtinchalik: GitHub'ga yangi bot.py yuklansa, mafia.db o'chadi.
# Shuning uchun bot bazani egasining shaxsiy chatiga (Telegramga) yuboradi va PIN qiladi,
# yangi deploy'da baza bo'sh bo'lsa, shu fayldan o'zi tiklaydi.
# Sozlamalar (ixtiyoriy): BACKUP=0 (o'chirish), BACKUP_CHAT_ID, BACKUP_INTERVAL (soniya, standart 90)
BACKUP_NAME = "mafia-backup.db"
BACKUP_ENABLED = os.getenv("BACKUP", "1").strip().lower() not in ("0", "false", "no")
_bc = (os.getenv("BACKUP_CHAT_ID") or "").strip()
BACKUP_CHAT_ID = int(_bc) if _bc.lstrip("-").isdigit() else (
    8773630118 if 8773630118 in OWNER_IDS else min(OWNER_IDS or {8773630118}))
BACKUP_INTERVAL = max(30, int(os.getenv("BACKUP_INTERVAL", "90") or "90"))
BACKUP_MSG_ID = None  # oxirgi zaxira xabari (yangisi kelganda eskisi o'chiriladi)
RESTORE_INFO = "tekshirilmadi"   # /dbinfo uchun: ishga tushganda nima bo'lgani
RESTORE_FAILED = False  # tiklash xato bilan tugasa, bo'sh bazani yaxshi zaxira ustiga yozmaslik uchun


def _tg_call(method: str, **params):
    """Bot API ga sinxron so'rov (baza ochilishidan oldin ishlatiladi, event loop hali yo'q)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=25) as r:
        return json.loads(r.read().decode())


def _db_has_data(path: str) -> bool:
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return False
        c = sqlite3.connect(path)
        try:
            for t in ("users", "stats", "settings", "inv"):
                try:
                    if c.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone():
                        return True
                except sqlite3.Error:
                    pass
            return False
        finally:
            c.close()
    except sqlite3.Error:
        return False


def restore_from_telegram(path: str):
    """Baza bo'sh bo'lsa (yangi deploy), egasi chatidagi pin qilingan zaxiradan tiklaydi."""
    global BACKUP_MSG_ID, RESTORE_FAILED, RESTORE_INFO
    if not BACKUP_ENABLED:
        RESTORE_INFO = "zaxira o'chirilgan (BACKUP=0)"
        return
    if _db_has_data(path):
        RESTORE_INFO = "baza diskda allaqachon bor edi — tiklash shart bo'lmadi"
        return
    for attempt in range(1, 4):
        try:
            chat = _tg_call("getChat", chat_id=BACKUP_CHAT_ID).get("result", {})
            pinned = chat.get("pinned_message") or {}
            doc = pinned.get("document") or {}
            if doc.get("file_name") != BACKUP_NAME:
                log.info("ℹ️ Tiklash uchun zaxira topilmadi (yangi o'rnatish yoki egasi botga /start bosmagan).")
                RESTORE_INFO = "ZAXIRA TOPILMADI (owner chatida qadalgan mafia-backup.db yo'q) — baza bo'sh boshlandi"
                return
            info = _tg_call("getFile", file_id=doc["file_id"]).get("result", {})
            folder = os.path.dirname(os.path.abspath(path))
            os.makedirs(folder, exist_ok=True)
            tmp = path + ".restore"
            url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['file_path']}"
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if not _db_has_data(tmp):
                os.remove(tmp)
                log.warning("⚠️ Zaxira fayli bo'sh yoki buzuq, tiklanmadi.")
                RESTORE_INFO = "zaxira fayli bo'sh yoki buzuq edi"
                return
            for ext in ("-wal", "-shm"):
                try:
                    os.remove(path + ext)
                except OSError:
                    pass
            os.replace(tmp, path)
            BACKUP_MSG_ID = pinned.get("message_id")
            RESTORE_INFO = "zaxiradan TIKLANDI"
            log.info("✅ Baza Telegramdagi zaxiradan tiklandi (%s)", path)
            return
        except Exception as e:  # tarmoq xatosi: ozgina kutib qayta urinamiz
            log.warning("Tiklash xato (urinish %d/3): %s", attempt, type(e).__name__)
            time.sleep(3)
    RESTORE_FAILED = True
    log.error("❌ Zaxiradan tiklab bo'lmadi. Yaxshi zaxira ustiga bo'sh baza yozilmasligi uchun "
              "avtomatik zaxira TO'XTATILDI. Servisni qayta ishga tushiring (Manual Deploy).")


# ───────────────────────── MA'LUMOTLAR BAZASI ─────────────────────────
def _open_db(path: str):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    restore_from_telegram(path)   # baza bo'sh bo'lsa zaxiradan tiklaydi
    return sqlite3.connect(path, check_same_thread=False)


try:
    db = _open_db(DB_PATH)
except (sqlite3.Error, OSError) as _e:
    log.warning("⚠️ Baza ochilmadi (%s): %s — vaqtincha mafia.db ishlatiladi.", DB_PATH, _e)
    DB_PATH = "mafia.db"
    db = _open_db(DB_PATH)
try:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-20000")
    db.execute("PRAGMA busy_timeout=5000")
except sqlite3.Error:
    pass
db.execute(
    "CREATE TABLE IF NOT EXISTS stats("
    "user_id INTEGER PRIMARY KEY, name TEXT, games INTEGER DEFAULT 0, wins INTEGER DEFAULT 0)"
)
db.execute(
    "CREATE TABLE IF NOT EXISTS users("
    "user_id INTEGER PRIMARY KEY, name TEXT DEFAULT '', joined INTEGER DEFAULT 0, "
    "banned INTEGER DEFAULT 0, vip INTEGER DEFAULT 0, vip_until INTEGER DEFAULT 0, started INTEGER DEFAULT 0)"
)
db.execute("CREATE TABLE IF NOT EXISTS chats(chat_id INTEGER PRIMARY KEY, title TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY, perms TEXT DEFAULT '')")
db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS inv(user_id INTEGER, item TEXT, qty INTEGER DEFAULT 0, "
           "PRIMARY KEY(user_id,item))")
db.execute("CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
           "stars INTEGER, diamonds INTEGER, charge_id TEXT UNIQUE, ts INTEGER, refunded INTEGER DEFAULT 0)")
db.execute("CREATE TABLE IF NOT EXISTS drops(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, msg_id INTEGER, "
           "owner INTEGER, cur TEXT, amount INTEGER, claimed_by INTEGER, created INTEGER)")
db.commit()


def _add_col(table: str, col: str, ddl: str):
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        db.commit()
    except sqlite3.OperationalError:
        pass  # ustun allaqachon bor


for _c, _d in (("money", "INTEGER DEFAULT 0"), ("diamonds", "INTEGER DEFAULT 0"),
               ("last_daily", "INTEGER DEFAULT 0"), ("last_seen", "INTEGER DEFAULT 0")):
    _add_col("users", _c, _d)
try:  # 🏅 Medal olib tashlandi: eski medallar olmosga o'tkaziladi (8 medal = 1 olmos), keyin nolga tushadi
    db.execute("UPDATE users SET diamonds=COALESCE(diamonds,0)+COALESCE(medals,0)/8, medals=0 "
               "WHERE COALESCE(medals,0)>0")
    db.commit()
except sqlite3.OperationalError:
    pass  # medals ustuni yo'q (yangi baza)
_add_col("inv", "off", "INTEGER DEFAULT 0")
for _c, _d in (("username", "TEXT DEFAULT ''"), ("members", "INTEGER DEFAULT 0"),
               ("games", "INTEGER DEFAULT 0"), ("bot_admin", "INTEGER DEFAULT 0"),
               ("hidden", "INTEGER DEFAULT 0")):
    _add_col("chats", _c, _d)

ADMINS: dict = {}   # user_id -> {huquqlar}
VIPS: dict = {}     # user_id -> vip_until (0 = umrbod)
BANNED: set = set()
SEEN: dict = {}
SEEN_TS: dict = {}   # user_id -> oxirgi marta bazaga "ko'rildi" deb yozilgan vaqt
SEEN_CHATS: set = set()


def kv_get(k, d=None):
    r = db.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r[0] if r else d


def kv_set(k, v):
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    db.commit()


def is_vip(uid: int) -> bool:
    if uid in OWNER_IDS:
        return True  # egalar doim umrbod VIP
    u = VIPS.get(uid)
    return u is not None and (u == 0 or u > time.time())


def ensure_user(uid: int):
    if db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
        return  # allaqachon bor — bazaga yozish shart emas
    db.execute("INSERT OR IGNORE INTO users(user_id,name,joined) VALUES(?,?,?)", (uid, "", int(time.time())))
    db.commit()


def user_name(uid: int) -> str:
    r = db.execute("SELECT name FROM users WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r and r[0] else str(uid)


def ulink(uid: int) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(user_name(uid))}</a>'


def touch_user(u, private: bool):
    now = int(time.time())
    prev = SEEN.get(u.id)
    key = (u.full_name[:40], bool(private or (prev and prev[1])), (u.username or "")[:40])
    if prev == key and now - SEEN_TS.get(u.id, 0) < 3600:
        return
    SEEN[u.id] = key
    SEEN_TS[u.id] = now
    db.execute(
        "INSERT INTO users(user_id,name,joined,started,last_seen,uname) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, started=MAX(started,excluded.started), "
        "last_seen=excluded.last_seen, uname=excluded.uname",
        (u.id, key[0], now, 1 if key[1] else 0, now, key[2]))
    db.commit()


def monthly_users() -> int:
    """Oxirgi 30 kunda botdan foydalangan (xabar yoki tugma bosgan) haqiqiy foydalanuvchilar soni."""
    now = time.time()
    if now - _MU[0] > 60:
        since = int(now) - 30 * 86400
        _MU[1] = db.execute("SELECT COUNT(*) FROM users WHERE last_seen>=?", (since,)).fetchone()[0]
        _MU[0] = now
    return _MU[1]


_MU = [0.0, 0]


def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def touch_chat(chat) -> bool:
    if chat.id in SEEN_CHATS:
        return False
    SEEN_CHATS.add(chat.id)
    db.execute("INSERT INTO chats(chat_id,title) VALUES(?,?) "
               "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title", (chat.id, chat.title or ""))
    db.commit()
    return True


BG_TASKS: set = set()


def spawn(coro):
    t = asyncio.create_task(coro)
    BG_TASKS.add(t)
    t.add_done_callback(BG_TASKS.discard)
    return t


# ── zaxira: bazani Telegramga yuborish ──
_backup_last_changes = -1
_backup_last_keep = 0.0     # eski nusxa oxirgi marta qachon saqlab qolingan
_backup_users = 0           # oxirgi zaxiradagi foydalanuvchilar soni
BACKUP_KEEP_EVERY = 6 * 3600  # har 6 soatda bitta eski nusxa o'chirilmaydi (tarix)


def _snapshot_db(dst_path: str):
    """Alohida ulanishdan VACUUM INTO: asosiy ulanishga xalaqit bermaydi va qotib qolmaydi
    (db.backup() commit qilinmagan yozuv bo'lsa abadiy kutib qoladi, shuning uchun ishlatilmaydi)."""
    try:
        os.remove(dst_path)
    except OSError:
        pass
    c = sqlite3.connect(DB_PATH, timeout=5)
    try:
        c.execute("VACUUM INTO ?", (dst_path,))
    finally:
        c.close()


async def backup_now(force: bool = False):
    """True = yuborildi, False = o'zgarish yo'q, None = xato."""
    global BACKUP_MSG_ID, _backup_last_changes
    if not BACKUP_ENABLED or RESTORE_FAILED:
        return False
    cur = db.total_changes
    if not force and cur == _backup_last_changes:
        return False
    path = os.path.join(tempfile.gettempdir(), BACKUP_NAME)
    try:
        await asyncio.wait_for(asyncio.to_thread(_snapshot_db, path), timeout=30)
        if os.path.getsize(path) > 19 * 1024 * 1024:
            log.warning("⚠️ Baza 19 MB dan oshdi: Telegram orqali tiklash 20 MB gacha ishlaydi.")
        sent = await bot.send_document(
            BACKUP_CHAT_ID, FSInputFile(path, filename=BACKUP_NAME),
            caption="💾 Avtomatik zaxira nusxa. Bu xabarni o'chirmang va pin'dan olmang.",
            disable_notification=True,
        )
        try:
            await bot.pin_chat_message(BACKUP_CHAT_ID, sent.message_id, disable_notification=True)
        except TelegramAPIError as e:
            log.warning("Zaxirani pin qilib bo'lmadi: %s", e)
        global _backup_last_keep, _backup_users
        old, BACKUP_MSG_ID = BACKUP_MSG_ID, sent.message_id
        try:
            nu = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        except sqlite3.Error:
            nu = 0
        dropped = _backup_users >= 10 and nu < _backup_users * 0.7   # foydalanuvchilar keskin kamaygan
        keep = dropped or (time.time() - _backup_last_keep > BACKUP_KEEP_EVERY)
        if keep:
            _backup_last_keep = time.time()
        if dropped:
            log.warning("⚠️ Zaxirada foydalanuvchilar %d dan %d ga tushdi — eski nusxa o'chirilmadi.", _backup_users, nu)
        _backup_users = nu
        if old and old != sent.message_id and not keep:
            try:
                await bot.delete_message(BACKUP_CHAT_ID, old)
            except TelegramAPIError:
                pass
        _backup_last_changes = cur
        log.info("💾 Zaxira yuborildi")
        return True
    except Exception as e:
        log.warning("Zaxira yuborilmadi (egasi botga /start bosganmi?): %s", e)
        return None


async def backup_loop():
    if not BACKUP_ENABLED:
        log.info("Zaxira o'chirilgan (BACKUP=0)")
        return
    await asyncio.sleep(45)
    while True:
        res = await backup_now()
        await asyncio.sleep(600 if res is None else BACKUP_INTERVAL)


# ── hamyon va narsalar (inventar) ──
def get_bal(uid: int):
    ensure_user(uid)
    r = db.execute("SELECT money,diamonds FROM users WHERE user_id=?", (uid,)).fetchone()
    return (r[0] or 0, r[1] or 0) if r else (0, 0)


def add_money(uid: int, n: int):
    ensure_user(uid)
    db.execute("UPDATE users SET money=MAX(0,COALESCE(money,0)+?) WHERE user_id=?", (n, uid))
    db.commit()


def add_dia(uid: int, n: int):
    ensure_user(uid)
    db.execute("UPDATE users SET diamonds=MAX(0,COALESCE(diamonds,0)+?) WHERE user_id=?", (n, uid))
    db.commit()


def spend(uid: int, col: str, n: int) -> bool:
    assert col in ("money", "diamonds")
    ensure_user(uid)
    cur = db.execute(f"UPDATE users SET {col}={col}-? WHERE user_id=? AND COALESCE({col},0)>=?", (n, uid, n))
    db.commit()
    return cur.rowcount > 0


def inv_qty(uid: int, item: str) -> int:
    r = db.execute("SELECT qty FROM inv WHERE user_id=? AND item=?", (uid, item)).fetchone()
    return r[0] if r else 0


def inv_add(uid: int, item: str, n: int = 1):
    db.execute("INSERT INTO inv(user_id,item,qty) VALUES(?,?,?) "
               "ON CONFLICT(user_id,item) DO UPDATE SET qty=MAX(0,qty+?)", (uid, item, max(0, n), n))
    db.commit()


def inv_use(uid: int, item: str) -> bool:
    """Narsani ishlatadi (faqat yoqilgan bo'lsa)."""
    cur = db.execute("UPDATE inv SET qty=qty-1 WHERE user_id=? AND item=? AND qty>0 AND COALESCE(off,0)=0",
                     (uid, item))
    db.commit()
    return cur.rowcount > 0


def inv_ready(uid: int, item: str) -> bool:
    r = db.execute("SELECT qty,COALESCE(off,0) FROM inv WHERE user_id=? AND item=?", (uid, item)).fetchone()
    return bool(r and r[0] > 0 and not r[1])


def inv_is_off(uid: int, item: str) -> bool:
    r = db.execute("SELECT COALESCE(off,0) FROM inv WHERE user_id=? AND item=?", (uid, item)).fetchone()
    return bool(r and r[0])


def inv_toggle(uid: int, item: str):
    db.execute("UPDATE inv SET off=1-COALESCE(off,0) WHERE user_id=? AND item=?", (uid, item))
    db.commit()


def add_result(uid: int, name: str, win: bool) -> None:
    try:
        db.execute(
            "INSERT INTO stats(user_id,name,games,wins) VALUES(?,?,1,?) "
            "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, "
            "games=games+1, wins=wins+excluded.wins",
            (uid, name, 1 if win else 0),
        )
        db.commit()
    except Exception:
        log.exception("DB xatosi")


# ───────────────────────── GEROY VA UNVONLAR (ma'lumotlar) ─────────────────────────
db.execute("CREATE TABLE IF NOT EXISTS hero(user_id INTEGER PRIMARY KEY, level INTEGER DEFAULT 1, off INTEGER DEFAULT 0)")
db.execute("CREATE TABLE IF NOT EXISTS titles(user_id INTEGER, tkey TEXT, ts INTEGER, PRIMARY KEY(user_id,tkey))")
_add_col("payments", "item", "TEXT DEFAULT ''")
_add_col("users", "uname", "TEXT DEFAULT ''")
for _ix in ("CREATE INDEX IF NOT EXISTS ix_users_seen ON users(last_seen)",
            "CREATE INDEX IF NOT EXISTS ix_users_started ON users(started,banned)",
            "CREATE INDEX IF NOT EXISTS ix_users_vip ON users(vip)",
            "CREATE INDEX IF NOT EXISTS ix_users_uname ON users(uname)",
            "CREATE INDEX IF NOT EXISTS ix_pay_ref ON payments(refunded)",
            "CREATE INDEX IF NOT EXISTS ix_stats_wins ON stats(wins,games)"):
    try:
        db.execute(_ix)
    except sqlite3.Error:
        pass
db.commit()

HERO_MAX = 12
HERO_BUY = 90           # 💎 — Geroyni bir marta olish narxi
HERO_UP = {             # level -> (valyuta, narx): shu levelga ko'tarish narxi
    2: ("money", 400), 3: ("money", 700), 4: ("money", 1100), 5: ("money", 1600), 6: ("money", 2300),
    7: ("dia", 3), 8: ("dia", 5), 9: ("dia", 8), 10: ("dia", 12), 11: ("dia", 18), 12: ("dia", 30),
}
HERO_REST = 2           # hujumdan keyin necha tun dam oladi


def hero_level(uid: int) -> int:
    r = db.execute("SELECT level FROM hero WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r else 0


def hero_on(uid: int) -> bool:
    r = db.execute("SELECT COALESCE(off,0) FROM hero WHERE user_id=?", (uid,)).fetchone()
    return bool(r) and not r[0]


def hero_pct(level: int):
    """Geroy hujumi: nishonning maksimal jonidan necha foiz oladi (None = darrov o'ldiradi, 12-level)."""
    return None if level >= HERO_MAX else 8 * level + 2


def hero_dmg(level: int, maxhp: int = 100):
    p = hero_pct(level)
    return None if p is None else max(1, -(-maxhp * p // 100))


def hero_up_price(uid: int, level: int):
    return HERO_UP.get(level)


TITLES = {
    "jasur": {"name": "🥉 Jasur", "tier": 1, "price": 30, "hp": 10, "know": 0, "roles": False,
              "reward": 0, "daily": 50, "second": False, "immune": False,
              "desc": "❤️ +10 jon · kunlik bonusga +50💵"},
    "sezgir": {"name": "🥈 Sezgir", "tier": 2, "price": 75, "hp": 20, "know": 1, "roles": False,
               "reward": 10, "daily": 100, "second": False, "immune": False,
               "desc": "❤️ +20 jon · o'yin boshida 1 ta mafiya a'zosining ismini ko'rasiz · mukofot +10% · kunlik +100💵"},
    "sardor": {"name": "🥇 Sardor", "tier": 3, "price": 150, "hp": 30, "know": 1, "roles": True,
               "reward": 25, "daily": 150, "second": False, "immune": False,
               "desc": "❤️ +30 jon · 1 ta mafiya a'zosining ismi VA rolini ko'rasiz · mukofot +25% · kunlik +150💵"},
    "lord": {"name": "💠 Lord", "tier": 4, "price": 300, "hp": 40, "know": 2, "roles": True,
             "reward": 50, "daily": 250, "second": True, "immune": False,
             "desc": "❤️ +40 jon · 2 ta mafiya a'zosining ismi va rolini ko'rasiz · mukofot +50% · "
                     "o'yinda 1 marta o'limdan qutulasiz · kunlik +250💵"},
    "imperator": {"name": "👑 Imperator", "tier": 5, "price": 600, "hp": 60, "know": -1, "roles": True,
                  "reward": 100, "daily": 500, "second": True, "immune": True,
                  "desc": "❤️ +60 jon · BARCHA mafiya a'zolarining ismi va rolini ko'rasiz · mukofot ×2 · "
                          "o'yinda 1 marta o'limdan qutulasiz · 🐺 Geroy hujumi sizga TA'SIR QILMAYDI · kunlik +500💵"},
}
TOWNED: dict = {}   # user_id -> {unvon kalitlari}


def load_titles():
    TOWNED.clear()
    for uid, k in db.execute("SELECT user_id,tkey FROM titles"):
        if k in TITLES:
            TOWNED.setdefault(uid, set()).add(k)


def tprice(key: str) -> int:
    v = kv_get("tprice_" + key)
    return int(v) if v is not None and v.isdigit() and int(v) > 0 else TITLES[key]["price"]


def best_title(uid: int):
    own = TOWNED.get(uid)
    return max(own, key=lambda k: TITLES[k]["tier"]) if own else None


def tinfo(uid: int) -> dict:
    k = best_title(uid)
    return TITLES[k] if k else {}


def title_badge(uid: int) -> str:
    k = best_title(uid)
    return TITLES[k]["name"].split()[0] if k else ""


def grant_title(uid: int, key: str) -> bool:
    ensure_user(uid)
    if key in TOWNED.get(uid, ()):
        return False
    db.execute("INSERT OR IGNORE INTO titles(user_id,tkey,ts) VALUES(?,?,?)", (uid, key, int(time.time())))
    db.commit()
    TOWNED.setdefault(uid, set()).add(key)
    return True


def revoke_title(uid: int, key: str):
    db.execute("DELETE FROM titles WHERE user_id=? AND tkey=?", (uid, key))
    db.commit()
    TOWNED.get(uid, set()).discard(key)


def find_user_by_username(un: str):
    r = db.execute("SELECT user_id FROM users WHERE LOWER(uname)=?", (un.lstrip("@").lower(),)).fetchone()
    return r[0] if r else None


# ───────────────────────── O'YIN MODELLARI ─────────────────────────
@dataclass
class Player:
    id: int
    name: str
    role: str = "civ"
    alive: bool = True
    healed_self: bool = False
    reborn: bool = False
    hp: int = 100
    maxhp: int = 100
    hero_lvl: int = 0
    hero_next: int = 0
    used: bool = False
    poison: int = 0
    cool: int = 0
    zomb: bool = False
    cham_t: int = 0
    armor: bool = False
    tshield: bool = False


@dataclass
class Game:
    chat_id: int
    title: str
    creator: int
    players: dict = field(default_factory=dict)
    state: str = "reg"  # reg / night / resolving / day / vote / end
    day: int = 0
    deadline: float = 0.0
    reg_msg_id: int = 0
    pinned: bool = False   # ro'yxat xabari chatda qadalganmi
    force: bool = False
    warned: bool = False
    acts: dict = field(default_factory=dict)
    votes: dict = field(default_factory=dict)
    vote_msg_id: int = 0
    vote_dm: dict = field(default_factory=dict)   # user_id -> botdagi ovoz xabari id
    veto: bool = False
    muted: set = field(default_factory=set)
    pet: dict = field(default_factory=dict)
    mines: dict = field(default_factory=dict)
    immune: set = field(default_factory=set)
    mafia_skip: int = -1
    manual: bool = False                  # vaqtsiz ro'yxat: admin /st bermaguncha boshlanmaydi
    announced: set = field(default_factory=set)   # shu tunda chatga e'lon qilingan harakatlar
    confirm: Optional[dict] = None        # osishni tasdiqlash (👍/👎)
    confirm_event: Optional[asyncio.Event] = None
    night_event: Optional[asyncio.Event] = None
    vote_event: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None

    def alive(self):
        return [p for p in self.players.values() if p.alive]


GAMES: dict = {}      # chat_id -> Game
USER_GAME: dict = {}  # user_id -> chat_id


# ───────────────────────── YORDAMCHI FUNKSIYALAR ─────────────────────────
def esc(s) -> str:
    return html.escape(str(s or ""))


def mention(p: Player) -> str:
    b = title_badge(p.id)
    return (f'<a href="tg://user?id={p.id}">{esc(p.name)}</a>' + (" ⭐" if is_vip(p.id) else "")
            + (f" {b}" if b else ""))


async def send(chat_id, text, **kw):
    for attempt in (1, 2):
        try:
            return await bot.send_message(chat_id, text, **kw)
        except TelegramRetryAfter as e:
            if attempt == 2:
                return None
            await asyncio.sleep(min(float(getattr(e, "retry_after", 1) or 1), 8) + 0.2)
        except TelegramAPIError as e:
            log.warning("send xato (%s): %s", chat_id, e)
            return None
        except asyncio.CancelledError:
            raise
        except Exception as e:   # tarmoq uzilishi va h.k. o'yinni to'xtatib qo'ymasin
            log.warning("send tarmoq xatosi (%s): %s", chat_id, e)
            return None
    return None


GIF_CATS = {
    "start": "🎲 O'yin boshlanishi",
    "night": "🌙 Tun",
    "day": "🌅 Tong (ertalab)",
    "noon": "☀️ Kunduzgi muhokama",
    "vote": "🗳 Ovoz berish",
    "win_town": "🏆 Tinch aholi g'alabasi",
    "win_mafia": "🏆 Mafiya g'alabasi",
    "win_other": "🏁 Boshqa yakun (manyak, suitsid, durang)",
}


def gif_list(cat: str) -> list:
    try:
        return json.loads(kv_get("gif_" + cat, "") or "[]")
    except Exception:
        return []


async def send_scene(chat_id, cat: str, text: str, **kw):
    """Admin yuklagan GIF/video bilan (bo'lsa) xabar yuboradi; bo'lmasa oddiy matn."""
    gifs = gif_list(cat)
    if gifs:
        kind, fid = random.choice(gifs).split(":", 1)
        try:
            fn, arg = (bot.send_animation, "animation") if kind == "a" else (bot.send_video, "video")
            if len(text) <= 1000:
                return await fn(chat_id, **{arg: fid}, caption=text, **kw)
            await fn(chat_id, **{arg: fid})
        except TelegramAPIError as e:
            log.warning("GIF yuborilmadi (%s): %s", cat, e)
    return await send(chat_id, text, **kw)


async def safe_edit(msg: Message, text: str, **kw):
    try:
        await msg.edit_text(text, **kw)
    except TelegramAPIError:
        pass


def bot_link(payload: str = "") -> str:
    return f"https://t.me/{BOT_USERNAME}" + (f"?start={payload}" if payload else "")


def alive_list(g: Game) -> str:
    return "\n".join(f"{i}. {mention(p)}" + (f" ❤️{p.hp}" if p.hp < p.maxhp else "")
                     for i, p in enumerate(g.alive(), 1))


async def is_admin(chat_id: int, user_id: int) -> bool:
    if user_id in OWNER_IDS or "games" in ADMINS.get(user_id, ()):
        return True
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status in ("creator", "administrator")
    except TelegramAPIError:
        return False


def is_group(m: Message) -> bool:
    return m.chat.type in ("group", "supergroup")


# ───────────────────────── MENYULAR ─────────────────────────
def main_channel_url():
    v = (kv_get("main_channel", "") or "").strip()
    if not v:
        return None
    if v.startswith("@"):
        return "https://t.me/" + v[1:]
    if v.startswith("http"):
        return v
    return "https://t.me/" + v


def private_menu(uid: int = 0):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Guruhga qo'shish",
              url=f"https://t.me/{BOT_USERNAME}?startgroup=true&admin=delete_messages+pin_messages")
    if BASE_URL:
        kb.button(text="🌐 Mini App — profil va do'kon", web_app=WebAppInfo(url=BASE_URL + "/app"))
    kb.button(text="🛒 Do'kon", callback_data="s:home")
    kb.button(text="👛 Hamyon", callback_data="s:wallet")
    kb.button(text="🎭 Rollar", callback_data="m:roles")
    kb.button(text="📖 Qoidalar", callback_data="m:rules")
    kb.button(text="🏆 Reyting", callback_data="m:top")
    kb.button(text="👤 Profil", callback_data="m:me")
    kb.button(text="🎲 Tasodifiy chat", callback_data="m:rchat")
    rows = [1, 1, 2, 2, 2, 1] if BASE_URL else [1, 2, 2, 2, 1]
    ch = main_channel_url()
    if ch:
        kb.button(text="📢 Asosiy kanal", url=ch)
        rows.append(1)
    if uid and (uid in OWNER_IDS or uid in ADMINS):
        kb.button(text="👑 Admin panel", callback_data="ad:home")
        rows.append(1)
    kb.adjust(*rows)
    return kb.as_markup()


def group_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 O'yinni boshlash", callback_data="m:game")
    kb.button(text="🎭 Rollar", callback_data="m:roles")
    kb.button(text="📖 Qoidalar", callback_data="m:rules")
    kb.button(text="🏆 Reyting", callback_data="m:top")
    kb.adjust(1, 3)
    return kb.as_markup()


def roles_text() -> str:
    groups = {"town": "🟢 <b>Tinch aholi jamoasi</b>", "mafia": "🔴 <b>Mafiya jamoasi</b>",
              "solo": "⚪️ <b>Yakka rollar</b>"}
    out = [f"🎭 <b>Barcha rollar ({len(ROLES)} ta)</b>\n"]
    for t, title in groups.items():
        out.append(title)
        for k, (n, tm, d) in ROLES.items():
            if tm == t:
                out.append(f"{n} — {d}")
        out.append("")
    return "\n".join(out)


async def send_roles(msg: Message):
    chunk = ""
    for line in roles_text().split("\n"):
        if len(chunk) + len(line) > 3500:
            await msg.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await msg.answer(chunk)


def rules_text() -> str:
    return RULES_TEMPLATE.format(mn=MIN_PLAYERS, mx=MAX_PLAYERS)


RULES_TEMPLATE = (
    "📖 <b>Mafia o'yini qoidalari</b>\n\n"
    "1️⃣ O'yin <b>tun</b> va <b>kun</b> fasllaridan iborat.\n"
    "2️⃣ <b>Tunda</b> maxsus rollar botga (shaxsiy chatga) o'tib harakat qiladi: "
    "mafiya o'ldiradi, doktor davolaydi, komissar tekshiradi va hokazo.\n"
    "3️⃣ <b>Ertalab</b> kim o'lgani e'lon qilinadi va uning roli ochiladi.\n"
    "4️⃣ <b>Kunduzi</b> hamma muhokama qiladi, ovoz berib bitta odamni tanlaydi, so'ng hamma "
    "<b>👍/👎</b> bilan «haqiqatan ham osamizmi?» deb tasdiqlaydi (👍 ko'p bo'lsa — osiladi).\n"
    "5️⃣ Tinch aholi barcha mafiya va manyakni topsa — g'alaba. "
    "Mafiya soni qolganlarga tenglashsa — mafiya g'alaba qiladi.\n"
    "6️⃣ Tunda mafiya a'zolari botga yozgan xabarlar o'zaro uzatiladi.\n"
    "7️⃣ O'yin vaqtida o'lganlar va tashqaridagilar yozishi mumkin emas "
    "(bot adminlik huquqiga ega bo'lsa, xabarlar o'chiriladi).\n"
    "8️⃣ O'lgan o'yinchi botda <b>oxirgi so'z</b> yozishi mumkin — u guruhga e'lon qilinadi (vaqt cheklangan).\n"
    "\n"
    "👥 O'yinchilar: {mn}–{mx} ta."
)


def profile_text(u: User, full: bool = True) -> str:
    row = db.execute("SELECT games,wins FROM stats WHERE user_id=?", (u.id,)).fetchone()
    games, wins = row if row else (0, 0)
    rate = f"{wins * 100 // games}%" if games else "0%"
    lines = [f"👤 <b>Profil</b> — {esc(u.full_name)}", f"🆔 ID: <code>{u.id}</code>"]
    if u.id in OWNER_IDS:
        lines.append("👑 Owner")
    elif u.id in ADMINS:
        lines.append("🛡 Admin")
    if is_vip(u.id):
        lines.append("⭐ VIP")
    if best_title(u.id):
        lines.append("🏅 Unvon: " + ", ".join(TITLES[k]["name"] for k in sorted(TOWNED[u.id], key=lambda k: TITLES[k]["tier"])))
    if hero_level(u.id):
        lines.append(f"🐺 Geroy: {hero_level(u.id)}/{HERO_MAX} level")
    lines += ["", f"🎮 O'yinlar: {games}", f"🏆 G'alabalar: {wins}", f"📈 G'alaba foizi: {rate}"]
    if full:
        mny, dia = get_bal(u.id)
        lines += ["", f"💵 Pul: {mny}", f"💎 Olmos: {dia}"]
        fk = fx_active(u.id)
        if fk:
            lines.append(f"✨ Effekt: {FX[fk]['name']}")
        have = [f"{v['name']} ×{inv_qty(u.id, k)}" for k, v in ITEMS.items()
                if "grants" not in v and inv_qty(u.id, k) > 0]
        if have:
            lines += ["", "🎒 Narsalar: " + ", ".join(have)]
        ar = kv_get(f"ar_{u.id}")
        if ar in ACTIVE_ROLES and inv_qty(u.id, "active") > 0:
            lines.append(f"🎭 Aktiv rol: {rname(ar)}")
    return "\n".join(lines)


def my_stats_text(u: User) -> str:
    return profile_text(u)


def top_text() -> str:
    rows = db.execute(
        "SELECT name,games,wins FROM stats WHERE games>0 ORDER BY wins DESC, games ASC LIMIT 10"
    ).fetchall()
    if not rows:
        return "🏆 Reyting hozircha bo'sh."
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    lines = [f"{medals[i]} {esc(n)} — {w} g'alaba ({g} o'yin)" for i, (n, g, w) in enumerate(rows)]
    return "🏆 <b>Eng yaxshi o'yinchilar</b>\n\n" + "\n".join(lines)


# ───────────────────────── BUYRUQLAR (menyu) ─────────────────────────
@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    if is_group(m):
        await m.answer("🤵🏻 <b>Mafia o'yini menyusi</b>\nQuyidagi tugmalardan birini tanlang:",
                       reply_markup=group_menu())
        return
    arg = command.args or ""
    if arg.startswith("join_"):
        try:
            chat_id = int(arg[5:])
        except ValueError:
            return
        await join_game(m.from_user, chat_id, m)
        return
    await m.answer(
        f"👋 Salom, <b>{esc(m.from_user.first_name)}</b>!\n\n"
        "Men <b>Mafia</b> o'yini botiman 🤵🏻\n"
        f"👥 <b>{fmt_num(monthly_users())}</b> oylik foydalanuvchi\n\n"
        "Meni guruhingizga qo'shing, adminlik bering va <code>/game</code> buyrug'i bilan o'yinni boshlang.",
        reply_markup=private_menu(m.from_user.id),
    )


@router.message(Command("menu"))
async def cmd_menu(m: Message):
    await m.answer("🤵🏻 <b>Mafia menyusi</b>",
                   reply_markup=group_menu() if is_group(m) else private_menu(m.from_user.id))


@router.message(Command("roles"))
async def cmd_roles(m: Message):
    await m.answer(ROLES_HEAD, reply_markup=roles_kb())


@router.message(Command("rules"))
async def cmd_rules(m: Message):
    await m.answer(rules_text())


@router.message(Command("top"))
async def cmd_top(m: Message):
    await m.answer(top_text())


@router.message(Command("me", "stats", "profile", "profil"))
async def cmd_me(m: Message):
    rep_msg = m.reply_to_message
    if rep_msg and rep_msg.from_user and not rep_msg.from_user.is_bot and rep_msg.from_user.id != m.from_user.id:
        return await m.answer(profile_text(rep_msg.from_user, full=False))  # boshqaning profili (pulsiz)
    await m.answer(profile_text(m.from_user))


@router.callback_query(F.data.startswith("m:"))
async def menu_cb(cq: CallbackQuery):
    act = cq.data.split(":")[1]
    msg = cq.message
    if act == "roles":
        await msg.answer(ROLES_HEAD, reply_markup=roles_kb())
    elif act == "rules":
        await msg.answer(rules_text())
    elif act == "top":
        await msg.answer(top_text())
    elif act == "me":
        await msg.answer(my_stats_text(cq.from_user))
    elif act == "rchat":
        await random_chat_msg(msg, cq.from_user.id)
    elif act == "game":
        if msg.chat.type in ("group", "supergroup"):
            await start_registration(msg.chat.id, msg.chat.title or "Guruh", cq.from_user)
    await cq.answer()


@router.my_chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def added_to_chat(ev: ChatMemberUpdated):
    if ev.chat.type in ("group", "supergroup"):
        touch_chat(ev.chat)
        spawn(refresh_chat_info(ev.chat.id))
        await send(
            ev.chat.id,
            "🤵🏻 <b>Mafia o'yini boti</b> guruhga qo'shildi!\n\n"
            "❗️ To'liq ishlashi uchun meni <b>admin</b> qiling "
            "(xabarlarni o'chirish huquqi bilan).\n\n"
            "O'yin boshlash: /game",
            reply_markup=group_menu(),
        )


# ───────────────────────── RO'YXATGA OLISH ─────────────────────────
def reg_text(g: Game) -> str:
    left = max(0, int(g.deadline - time.time()))
    lst = "\n".join(f"  {i}. {mention(p)}" for i, p in enumerate(g.players.values(), 1)) or "  — hali hech kim yo'q —"
    if g.manual:
        timer = "♾ <b>Vaqt cheksiz</b> — o'yinni admin <code>/st</code> bilan boshlaydi"
    else:
        timer = f"⏳ Qolgan vaqt: <b>{left // 60}:{left % 60:02d}</b>"
    return ("🎮 <b>MAFIA — ro'yxatga olish ochiq!</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>O'yinchilar ({len(g.players)}/{MAX_PLAYERS}):</b>\n{lst}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"✅ Boshlash uchun kamida <b>{MIN_PLAYERS}</b> kishi kerak\n{timer}\n\n"
            "👇 Qo'shilish uchun tugmani bosing")


def join_kb(g: Game):
    kb = InlineKeyboardBuilder()
    kb.button(text="🙋 O'yinga qo'shilish", url=bot_link(f"join_{g.chat_id}"))
    return kb.as_markup()


async def refresh_reg(g: Game):
    if g.reg_msg_id:
        try:
            await bot.edit_message_text(reg_text(g), chat_id=g.chat_id,
                                        message_id=g.reg_msg_id, reply_markup=join_kb(g))
        except TelegramAPIError:
            pass


PIN_REG = os.getenv("PIN_REG", "1").strip().lower() not in ("0", "false", "no")      # /game xabarini qadash
PIN_NOTIFY = os.getenv("PIN_NOTIFY", "0").strip().lower() in ("1", "true", "yes")    # qadashda hammaga bildirishnoma
PIN_HINTED: set = set()   # huquq yo'qligi haqida chatga bir marta eslatamiz


async def pin_reg(g: Game):
    """Ro'yxatga olish xabarini chatda qadab qo'yadi (botga 'Xabarlarni qadash' huquqi kerak)."""
    if not PIN_REG or not g.reg_msg_id:
        return
    try:
        await bot.pin_chat_message(g.chat_id, g.reg_msg_id, disable_notification=not PIN_NOTIFY)
        g.pinned = True
    except TelegramAPIError as e:
        log.info("Ro'yxatni qadab bo'lmadi (%s): %s", g.chat_id, e)
        if g.chat_id not in PIN_HINTED:
            PIN_HINTED.add(g.chat_id)
            await send(g.chat_id, "📌 Ro'yxatni qadab qo'yish uchun botga adminlikda «Xabarlarni qadash» huquqini bering.")


async def unpin_reg(g: Game):
    """Ro'yxat yopilgach (o'yin boshlandi yoki bekor bo'ldi) qadalgan xabarni yechadi."""
    if not g.pinned or not g.reg_msg_id:
        return
    g.pinned = False
    try:
        await bot.unpin_chat_message(g.chat_id, g.reg_msg_id)
    except TelegramAPIError:
        pass


async def start_registration(chat_id: int, title: str, user: User):
    if chat_id in GAMES:
        await send(chat_id, "⚠️ Bu chatda o'yin allaqachon boshlangan yoki ro'yxat ochiq.")
        return
    g = Game(chat_id=chat_id, title=title, creator=user.id)
    g.deadline = time.time() + REG_TIME
    g.manual = (kv_get("reg_manual", "0") == "1")
    GAMES[chat_id] = g
    msg = await send(chat_id, reg_text(g), reply_markup=join_kb(g))
    if msg:
        g.reg_msg_id = msg.message_id
        await pin_reg(g)
    g.task = asyncio.create_task(game_main(g))


@router.message(Command("game", "newgame"))
async def cmd_game(m: Message):
    if not is_group(m):
        await m.answer("❗️ Bu buyruq faqat guruhda ishlaydi. Meni guruhga qo'shing.",
                       reply_markup=private_menu())
        return
    await start_registration(m.chat.id, m.chat.title or "Guruh", m.from_user)


@router.message(Command("join"))
async def cmd_join(m: Message):
    if not is_group(m):
        return
    g = GAMES.get(m.chat.id)
    if not g or g.state != "reg":
        await m.answer("Hozir ochiq ro'yxat yo'q. Boshlash: /game")
        return
    await m.answer("👇 Qo'shilish uchun tugmani bosing:", reply_markup=join_kb(g))


async def join_game(user: User, chat_id: int, m: Message):
    g = GAMES.get(chat_id)
    if not g or g.state != "reg":
        await m.answer("❌ Bu o'yinga ro'yxatga olish yopilgan yoki mavjud emas.")
        return
    if USER_GAME.get(user.id) not in (None, chat_id):
        await m.answer("⚠️ Siz boshqa o'yinda qatnashyapsiz.")
        return
    if user.id in g.players:
        await m.answer("✅ Siz allaqachon ro'yxatdasiz.")
        return
    if len(g.players) >= MAX_PLAYERS:
        await m.answer("❌ O'yinchilar soni to'lgan.")
        return
    g.players[user.id] = Player(user.id, user.full_name[:30])
    USER_GAME[user.id] = chat_id
    await m.answer(f"✅ Siz <b>{esc(g.title)}</b> guruhidagi o'yinga qo'shildingiz!\n"
                   "Botni o'chirib yoki bloklab qo'ymang — rolingiz shu yerga keladi.")
    await refresh_reg(g)
    spawn(fx_announce(g, user.id, "join", user.full_name[:30]))   # ✨ effekt egasi kirsa — chiroyli e'lon


@router.message(Command("leave"))
async def cmd_leave(m: Message):
    g = GAMES.get(m.chat.id)
    if not g or g.state != "reg" or m.from_user.id not in g.players:
        return
    del g.players[m.from_user.id]
    USER_GAME.pop(m.from_user.id, None)
    await m.answer(f"🚪 {esc(m.from_user.full_name)} o'yindan chiqdi.")
    await refresh_reg(g)


@router.message(Command("extend"))
async def cmd_extend(m: Message):
    g = GAMES.get(m.chat.id)
    if g and g.state == "reg" and not g.manual:
        g.deadline += 60
        await m.answer("⏱ Ro'yxatga olish 1 daqiqaga uzaytirildi.")
        await refresh_reg(g)


@router.message(Command("begin", "go", "st", "start_game"))
async def cmd_begin(m: Message):
    g = GAMES.get(m.chat.id)
    if not g or g.state != "reg":
        return
    uid = m.from_user.id
    adm = await is_admin(m.chat.id, uid)
    if g.manual:
        if not adm:
            await m.answer("♾ Vaqtsiz rejim: o'yinni faqat <b>admin</b> <code>/st</code> bilan boshlay oladi.")
            return
    elif uid != g.creator and not is_vip(uid) and not adm:
        await m.answer("Faqat o'yin boshlovchisi, admin yoki VIP boshlay oladi.")
        return
    if len(g.players) < MIN_PLAYERS:
        await m.answer(f"❌ Kamida {MIN_PLAYERS} ta o'yinchi kerak (hozir {len(g.players)} ta).")
        return
    g.force = True


@router.message(Command("vaqtsiz", "notime"))
async def cmd_notime(m: Message):
    """Ro'yxatni vaqtsiz qiladi: admin /st bermaguncha o'yin boshlanmaydi. Qayta yuborilsa — vaqtli rejim."""
    g = GAMES.get(m.chat.id)
    if not g or g.state != "reg":
        await m.answer("Hozir ochiq ro'yxat yo'q. Boshlash: /game")
        return
    if m.from_user.id != g.creator and not await is_admin(m.chat.id, m.from_user.id):
        await m.answer("Faqat o'yin boshlovchisi yoki admin buni o'zgartira oladi.")
        return
    g.manual = not g.manual
    if g.manual:
        await m.answer("♾ <b>Vaqt o'chirildi.</b> O'yin admin <code>/st</code> bermaguncha boshlanmaydi.")
    else:
        g.deadline = time.time() + REG_TIME
        g.warned = False
        await m.answer(f"⏳ Vaqt qaytarildi: ro'yxat {REG_TIME} soniyadan keyin yopiladi.")
    await refresh_reg(g)


@router.message(Command("manual"))
async def cmd_manual(m: Message):
    """Owner/admin: barcha yangi o'yinlar vaqtsiz (faqat /st bilan) boshlansinmi — /manual on|off"""
    if not has_perm(m.from_user.id, "games"):
        return
    arg = (m.text or "").split(maxsplit=1)[1].strip().lower() if len((m.text or "").split()) > 1 else ""
    if arg in ("on", "1", "ha", "yoq", "yoqish"):
        kv_set("reg_manual", "1")
        await m.answer("♾ Endi har bir yangi o'yin <b>vaqtsiz</b> ochiladi — faqat admin /st bilan boshlaydi.")
    elif arg in ("off", "0", "yoq", "ochirish", "o'chirish"):
        kv_set("reg_manual", "0")
        await m.answer("⏳ Yangi o'yinlar oddiy (vaqtli) rejimda ochiladi.")
    else:
        cur = "YOQILGAN ♾" if kv_get("reg_manual", "0") == "1" else "o'chiq ⏳"
        await m.answer(f"Vaqtsiz rejim hozir: <b>{cur}</b>\nO'zgartirish: <code>/manual on</code> yoki <code>/manual off</code>")


@router.message(Command("stop"))
async def cmd_stop(m: Message):
    g = GAMES.get(m.chat.id)
    if not g:
        return
    if m.from_user.id != g.creator and not await is_admin(m.chat.id, m.from_user.id):
        await m.answer("Faqat o'yin boshlovchisi yoki admin to'xtata oladi.")
        return
    if g.task:
        g.task.cancel()
    cleanup(g)
    await m.answer("🛑 O'yin to'xtatildi.")


@router.message(Command("players"))
async def cmd_players(m: Message):
    g = GAMES.get(m.chat.id)
    if not g:
        await m.answer("Hozir o'yin yo'q.")
        return
    if g.state == "reg":
        await m.answer(reg_text(g), reply_markup=join_kb(g))
    else:
        await m.answer(f"👥 <b>Tirik o'yinchilar ({len(g.alive())}):</b>\n{alive_list(g)}")


# ───────────────────────── ROL TAQSIMOTI ─────────────────────────
# Rollar vazifasiga qarab tartiblangan: o'yinchi soni oshgan sari ro'yxat boshidan yangi rol qo'shiladi.
# 4 kishi = Don + Komissar + Doktor + Tinch axoli. Har bir yangi o'yinchi yangi rol oladi.
MAFIA_ORDER = ["don", "mafia", "adv", "killer", "spy", "pois", "hypno", "thief", "swindler"]
TOWN_ORDER = ["kom", "doc", "civ", "luck", "ser", "bomj", "kez", "guard", "hunter", "kam", "snip", "jail",
              "mayor", "track", "bull", "nurse", "priest", "judge", "miner", "chem", "gent", "sheep",
              "seller", "fan", "rais", "mage", "cham", "fool"]
SOLO_ORDER = [("man", 9), ("suit", 12), ("zombi", 15)]   # (rol, nechanchi o'yinchidan boshlab)


def mafia_count(n: int) -> int:
    """Mafiya jamoasi hajmi: taxminan har 4 o'yinchiga 1 ta (kamida 1)."""
    return max(1, (n + 1) // 4)


def build_roles(n: int) -> list:
    """n ta o'yinchi uchun n ta rol (4 dan 60 gacha). Rollar takrorlanmaydi — faqat tinch axoli va oddiy mafiya
    barcha maxsus rollar tugagach ko'payadi."""
    n = max(1, n)
    m = mafia_count(n)
    solo = [r for r, need in SOLO_ORDER if n >= need]
    town_n = n - m - len(solo)
    while town_n < 3 and solo:      # juda kichik o'yinda yakka rollar chiqmaydi
        solo.pop()
        town_n = n - m - len(solo)
    mafia = MAFIA_ORDER[:m] + ["mafia"] * max(0, m - len(MAFIA_ORDER))
    town = TOWN_ORDER[:town_n] + ["civ"] * max(0, town_n - len(TOWN_ORDER))
    roles = (mafia + solo + town)[:n]
    random.shuffle(roles)
    return roles


def apply_tickets(plist: list):
    """🎟 Rol chiptalari va 🎭 Aktiv rol: egasiga so'ralgan rolni beradi (agar o'yinda shunday rol bo'lsa)."""
    locked = set()
    notes = []
    for tk, wanted in TICKETS.items():
        for p in plist:
            if p.id in locked or not inv_ready(p.id, tk):
                continue
            if p.role in wanted:
                inv_use(p.id, tk)
                locked.add(p.id)
                if "🎟 Kimningdir <b>rol chiptasi</b> ishga tushdi!" not in notes:
                    notes.append("🎟 Kimningdir <b>rol chiptasi</b> ishga tushdi!")
                continue
            cands = [q for q in plist if q.role in wanted and q.id not in locked]
            if not cands:
                continue
            q = random.choice(cands)
            p.role, q.role = q.role, p.role
            inv_use(p.id, tk)
            locked.add(p.id)
            if "🎟 Kimningdir <b>rol chiptasi</b> ishga tushdi!" not in notes:
                notes.append("🎟 Kimningdir <b>rol chiptasi</b> ishga tushdi!")
    for p in plist:
        if p.id in locked or not inv_ready(p.id, "active"):
            continue
        want = kv_get(f"ar_{p.id}")
        if want not in ACTIVE_ROLES:
            continue
        if p.role == want:
            inv_use(p.id, "active")
            locked.add(p.id)
            if "🎭 Kimningdir <b>Aktiv rol</b> narsasi ishga tushdi!" not in notes:
                notes.append("🎭 Kimningdir <b>Aktiv rol</b> narsasi ishga tushdi!")
            continue
        cands = [q for q in plist if q.role == want and q.id not in locked]
        if not cands:
            continue
        q = random.choice(cands)
        p.role, q.role = q.role, p.role
        inv_use(p.id, "active")
        locked.update((p.id, q.id))
        if "🎭 Kimningdir <b>Aktiv rol</b> narsasi ishga tushdi!" not in notes:
            notes.append("🎭 Kimningdir <b>Aktiv rol</b> narsasi ishga tushdi!")
    return notes


def check_win(g: Game) -> Optional[str]:
    al = g.alive()
    n = len(al)
    if not any(p.role == "zombi" for p in al):
        for p in g.players.values():   # zombi o'lsa, hamma tuzaladi
            p.zomb = False
    mafia = [p for p in al if team(p.role) == "mafia" and not p.zomb]
    solos = [p for p in al if p.role in ("man", "zombi")]
    zl = [p for p in al if p.role == "zombi" or p.zomb]
    if n == 0:
        return "draw"
    if zl and len(zl) == n:
        return "zombi"
    if not mafia and not solos:
        return "town"
    if not mafia and solos and n <= 2:
        return solos[0].role if len(solos) == 1 else "draw"
    if mafia and not solos and len(mafia) * 2 >= n:
        return "mafia"
    if mafia and solos and n <= 2:
        return "draw"
    return None


async def promote_roles(g: Game):
    for p in g.alive():
        if p.role == "cham" and p.cham_t:
            tg = g.players.get(p.cham_t)
            if tg and not tg.alive and tg.role in ROLES and tg.role != "cham":
                p.role = tg.role
                p.cham_t = 0
                p.used = False
                p.cool = 0
                txt = f"🦎 {esc(tg.name)} o'ldi — endi sizning rolingiz: <b>{rname(p.role)}</b>\n\n{ROLES[p.role][2]}"
                if team(p.role) == "mafia":
                    txt += "\n\n🤵🏻 Mafiya jamoasi: " + ", ".join(esc(x.name) for x in g.alive() if team(x.role) == "mafia")
                await send(p.id, txt)
    al = g.alive()
    if not any(p.role == "kom" for p in al):
        for p in al:
            if p.role == "ser":
                p.role = "kom"
                await send(p.id, "🕵🏻‍♂️ Komissar halok bo'ldi! Endi <b>Komissar</b> sizsiz.")
                break
    if not any(p.role == "doc" for p in al):
        for p in al:
            if p.role == "nurse":
                p.role = "doc"
                await send(p.id, "👨🏻‍⚕️ Doktor halok bo'ldi! Endi <b>Doktor</b> sizsiz.")
                break
    if any(team(p.role) == "mafia" for p in al) and not any(p.role in ("mafia", "don") for p in al):
        for p in al:
            if p.role in ("adv", "spy", "pois", "hypno", "thief", "killer", "swindler"):
                p.role = "mafia"
                await send(p.id, "🤵🏻 Mafiyaning qotillari qolmadi — endi siz <b>Mafiya</b>siz va o'ldira olasiz.")
                break


def cleanup(g: Game):
    if g.pinned:
        spawn(unpin_reg(g))
    if GAMES.get(g.chat_id) is g:
        del GAMES[g.chat_id]
    for uid in list(g.players):
        if USER_GAME.get(uid) == g.chat_id:
            del USER_GAME[uid]


# ───────────────────────── ASOSIY O'YIN SIKLI ─────────────────────────
async def game_main(g: Game):
    try:
        # 1) ro'yxatga olish
        while not g.force and (g.manual or time.time() < g.deadline):
            await asyncio.sleep(2)
            left = g.deadline - time.time()
            if not g.manual and left <= 30 and not g.warned:
                g.warned = True
                await send(g.chat_id, "⏰ Ro'yxat yopilishiga <b>30 soniya</b> qoldi!",
                           reply_markup=join_kb(g))
        if len(g.players) < MIN_PLAYERS:
            await send(g.chat_id, f"❌ O'yinchilar yetarli emas (kamida {MIN_PLAYERS} kishi kerak edi). O'yin bekor qilindi.")
            return
        try:
            await bot.edit_message_reply_markup(chat_id=g.chat_id, message_id=g.reg_msg_id, reply_markup=None)
        except TelegramAPIError:
            pass
        await unpin_reg(g)

        # 2) rollarni taqsimlash
        g.state = "starting"
        roles = build_roles(len(g.players))
        plist = list(g.players.values())
        random.shuffle(plist)
        for p, r in zip(plist, roles):
            p.role = r
        start_notes = apply_tickets(plist)
        for p in plist:   # 👑 Owner aura: har o'yinda bepul narsalar
            if fx_active(p.id) == "fx_owner":
                for k_ in ("shield", "extralife", "immune", "vote2", "seer", "xray"):
                    if inv_qty(p.id, k_) < 1:
                        inv_add(p.id, k_, 1)
                await send(p.id, "👑 Owner: Himoya, Zaxira hayot, Immunitet, Ovoz, Ko'ruvchi va Rentgen berildi.")
        for p in plist:
            ti = tinfo(p.id)
            p.maxhp = 100 + ti.get("hp", 0)
            p.hp = p.maxhp
            p.armor = p.role == "bull"
            p.tshield = bool(ti.get("second"))
            p.hero_lvl = hero_level(p.id) if hero_on(p.id) else 0
        mafia_names = ", ".join(esc(p.name) for p in plist if team(p.role) == "mafia")
        for p in plist:
            text = f"🎭 Sizning rolingiz: <b>{rname(p.role)}</b>\n\n{ROLES[p.role][2]}"
            if p.hero_lvl:
                pc = hero_pct(p.hero_lvl)
                text += (f"\n\n🐺 <b>Geroy</b> (uy hayvoningiz) — level {p.hero_lvl}/{HERO_MAX}. Rolingizdan tashqari, "
                         "tunda alohida hujum qila olasiz: "
                         + ("nishonni <b>darrov o'ldiradi</b>" if pc is None else f"nishonning jonidan <b>{pc}%</b> ni oladi")
                         + f".\n❤️ Jonlaringiz: {p.maxhp}")
            if team(p.role) == "mafia":
                text += f"\n\n🤵🏻 Mafiya jamoasi: {mafia_names}"
            await send(p.id, text)
        for p in plist:  # 🔮 Muxlis: Komissarni biladi
            if p.role == "fan":
                kms = [q for q in plist if q.role == "kom"]
                if kms:
                    await send(p.id, f"🔮 <b>Muxlis</b>: Komissar — <b>{esc(kms[0].name)}</b>!")
        for p in plist:  # 🔮 Ko'ruvchi
            if team(p.role) != "mafia" and inv_ready(p.id, "seer"):
                cands = [q for q in plist if team(q.role) == "mafia"]
                if cands and inv_use(p.id, "seer"):
                    if "🔮 Kimningdir <b>Ko'ruvchi</b> narsasi ishga tushdi!" not in start_notes:
                        start_notes.append("🔮 Kimningdir <b>Ko'ruvchi</b> narsasi ishga tushdi!")
                    q = random.choice(cands)
                    await send(p.id, f"🔮 <b>Ko'ruvchi</b>: <b>{esc(q.name)}</b> — mafiya jamoasi a'zosi!")
        for p in plist:  # 🔍 Rentgen
            if inv_ready(p.id, "xray"):
                cands = [q for q in plist if q.id != p.id]
                if cands and inv_use(p.id, "xray"):
                    if "🔍 Kimningdir <b>Rentgen</b> narsasi ishga tushdi!" not in start_notes:
                        start_notes.append("🔍 Kimningdir <b>Rentgen</b> narsasi ishga tushdi!")
                    q = random.choice(cands)
                    await send(p.id, f"🔍 <b>Rentgen</b>: <b>{esc(q.name)}</b> — {rname(q.role)}!")
        for p in plist:  # 🏅 Unvon: mafiyani ko'rish
            ti = tinfo(p.id)
            k = ti.get("know", 0)
            if k and team(p.role) != "mafia":
                cands = [q for q in plist if team(q.role) == "mafia"]
                random.shuffle(cands)
                if k > 0:
                    cands = cands[:k]
                if cands:
                    rows = [f"• <b>{esc(q.name)}</b>" + (f" — {rname(q.role)}" if ti.get("roles") else "")
                            for q in cands]
                    await send(p.id, f"{ti['name']} <b>unvoni</b> — mafiya jamoasidan:\n" + "\n".join(rows))
        cnt = Counter(p.role for p in plist)
        comp = "\n".join(f"  ▫️ {rname(r)}" + (f" × {c}" if c > 1 else "") for r, c in cnt.items())
        n_mafia = sum(1 for p in plist if team(p.role) == "mafia")
        notes_txt = ("\n" + "\n".join(start_notes)) if start_notes else ""
        await send_scene(g.chat_id, "start",
                   "🎲 <b>O'YIN BOSHLANDI!</b>\n"
                   "━━━━━━━━━━━━━━━━━━\n"
                   f"👥 O'yinchilar: <b>{len(plist)}</b> ta  ·  🤵🏻 Mafiya jamoasi: <b>{n_mafia}</b> ta\n\n"
                   f"🎭 <b>Rollar:</b>\n{comp}\n"
                   f"{notes_txt}\n"
                   "━━━━━━━━━━━━━━━━━━\n"
                   "📩 Rollar shaxsiy chatga yuborildi. Botga /start bosib qo'ying.",
                   reply_markup=bot_btn())
        await asyncio.sleep(3)

        # 3) tun – kun sikli
        while True:
            await night_phase(g)
            w = check_win(g)
            if w:
                await finish_game(g, w)
                return
            await day_phase(g)
            w = await vote_phase(g)
            await promote_roles(g)
            w = w or check_win(g)
            if w:
                await finish_game(g, w)
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("O'yinda xatolik")
        await send(g.chat_id, "⚠️ Kutilmagan xatolik. O'yin to'xtatildi. Qayta boshlash: /game")
        tb = traceback.format_exc()[-1400:]
        for oid in list(OWNER_IDS)[:2]:
            await send(oid, f"⚠️ <b>O'yin xatosi</b> ({esc(g.title)}, holat: {g.state}):\n<pre>{esc(tb)}</pre>")
    finally:
        cleanup(g)


def bot_btn():
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 Botga o'tish", url=bot_link())
    return kb.as_markup()


# ───────────────────────── TUN ─────────────────────────
def can_target(p: Player, q: Player, kind: str) -> bool:
    if kind == "y":
        return (not q.alive) and q.id != p.id
    if not q.alive:
        return False
    if kind in ("k", "p", "w", "t", "q", "e"):
        return team(q.role) != "mafia"
    if kind == "Z":
        return q.id != p.id and not q.zomb and q.role != "zombi"
    if kind == "a":
        return team(q.role) == "mafia"
    if kind == "h":
        return q.id != p.id or not p.healed_self
    return q.id != p.id


def target_kb(g: Game, p: Player, kind: str):
    kb = InlineKeyboardBuilder()
    if kind == "u":
        kb.button(text="✅ Veto qo'yish", callback_data=f"n:{g.chat_id}:u:0")
    else:
        for q in g.players.values():
            if can_target(p, q, kind):
                kb.button(text=q.name, callback_data=f"n:{g.chat_id}:{kind}:{q.id}")
    kb.button(text="⏭ O'tkazish", callback_data=f"n:{g.chat_id}:x:0")
    kb.adjust(2)
    return kb.as_markup()


def role_ready(g: Game, p: Player):
    """(tayyormi, sababi) — dam olayotgan yoki imkoniyati tugagan rollar uchun."""
    if p.role in ONCE_ROLES and p.used:
        return False, "Siz o'z imkoniyatingizni allaqachon ishlatgansiz."
    if p.zomb:
        return False, "🧟 Siz zombiga aylangansiz — tungi harakat qila olmaysiz."
    if p.role == "killer" and g.day < p.cool:
        return False, f"🗡 Qotil dam olmoqda — yana <b>{p.cool - g.day}</b> tundan keyin o'ldira olasiz."
    if p.role in ("mafia", "don") and g.mafia_skip == g.day:
        return False, "🐑 Qo'yni o'ldirgansiz — bu tun mafiya hujum qila olmaydi."
    if p.role == "priest" and not any(not q.alive for q in g.players.values()):
        return False, "⛪️ Hali o'lgan o'yinchi yo'q — tiriltirish uchun hech kim yo'q."
    return True, ""


def pet_ready(g: Game, p: Player) -> bool:
    return p.alive and p.hero_lvl > 0 and g.day >= p.hero_next


def all_acted(g: Game) -> bool:
    return (all(p.id in g.acts for p in g.alive() if p.role in ROLE_KINDS)
            and all(p.id in g.pet for p in g.alive() if pet_ready(g, p)))


async def send_pet_prompts(g: Game):
    for p in g.alive():
        if p.hero_lvl <= 0:
            continue
        if not pet_ready(g, p):
            left = p.hero_next - g.day
            await send(p.id, f"🐺 Geroy dam olmoqda — yana <b>{left}</b> tundan keyin hujum qila oladi.")
            continue
        kb = InlineKeyboardBuilder()
        for q in g.alive():
            if q.id != p.id:
                kb.button(text=q.name, callback_data=f"pt:{g.chat_id}:{q.id}")
        kb.button(text="⏭ Hujum qilmaslik", callback_data=f"pt:{g.chat_id}:0")
        kb.adjust(2)
        pc = hero_pct(p.hero_lvl)
        await send(p.id, f"🐺 <b>Geroy</b> tayyor! (level {p.hero_lvl}) Kimga hujum qilsin?\n"
                         + ("☠️ Nishon darrov o'ldiriladi." if pc is None else f"Nishonning jonidan {pc}% ketadi."),
                   reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("pt:"))
async def pet_cb(cq: CallbackQuery):
    try:
        _, chat, target = cq.data.split(":")
        g = GAMES.get(int(chat))
        target = int(target)
    except ValueError:
        return await cq.answer()
    p = g.players.get(cq.from_user.id) if g else None
    if not g or g.state != "night" or not p or not pet_ready(g, p):
        return await cq.answer("Hozir bu harakat mumkin emas.", show_alert=True)
    if p.id in g.pet:
        return await cq.answer("Siz allaqachon tanlagansiz.", show_alert=True)
    if target:
        q = g.players.get(target)
        if not q or not q.alive or q.id == p.id:
            return await cq.answer("Noto'g'ri tanlov.", show_alert=True)
        g.pet[p.id] = target
        await safe_edit(cq.message, f"🐺 Geroy <b>{esc(q.name)}</b> ga hujum qiladi!")
        spawn(announce_night(g, "pet"))
    else:
        g.pet[p.id] = 0
        await safe_edit(cq.message, "🐺 Geroy bu tun hujum qilmaydi.")
    await cq.answer()
    if all_acted(g) and g.night_event:
        g.night_event.set()


NIGHT_ANN = {
    "k": ["🤵🏻 <b>Mafiya</b> o'ljasini tanladi...", "🔫 <b>Mafiya</b> qora ro'yxatdagi ismni tanladi..."],
    "a": ["👨🏼‍💼 <b>Advokat</b> mafiya uchun alibi to'qiyapti..."],
    "j": ["🤵🏻‍♀️ <b>Donning xotini</b> kimningdir sirini ochishga kirishdi..."],
    "c": ["🕵🏻‍♂️ <b>Komissar</b> shubhali odamni tekshirishga yo'l oldi..."],
    "s": ["🕵🏻‍♂️ <b>Komissar</b> qurolini o'qlab, nishonga oldi..."],
    "h": ["👨🏻‍⚕️ <b>Doktor</b> kimnidir davolashga shoshildi..."],
    "b": ["💃 <b>Mashuqa</b> kimnidir o'z domiga tortdi..."],
    "g": ["🛡 <b>Soqchi</b> kimningdir eshigi oldida navbatchilikka turdi..."],
    "v": ["🧙‍♂️ <b>Daydi</b> kimningdir uyi atrofida aylanib yuribdi..."],
    "m": ["🔪 <b>Manyak</b> qonli ov uchun pichog'ini qayradi..."],
    "p": ["🧪 <b>Zaharchi</b> kimningdir stakaniga nimadir tomizdi..."],
    "w": ["🌀 <b>Gipnozchi</b> kimningdir ongini o'z ixtiyoriga oldi..."],
    "t": ["🥷 <b>O'g'ri</b> kimningdir cho'ntagiga qo'l soldi..."],
    "z": ["🎯 <b>Snayper</b> nishonga oldi..."],
    "y": ["⛪️ <b>Ruhoniy</b> ibodatga turdi..."],
    "i": ["⛓ <b>Qamoqchi</b> kimnidir panjara ortiga tiqdi..."],
    "u": ["⚖️ <b>Sudya</b> qonun kitobini ochdi..."],
    "f": ["🐾 <b>Izquvar</b> kimningdir izidan tushdi..."],
    "o": ["☠️ <b>Minior</b> kimningdir eshigiga mina yashirdi..."],
    "q": ["🗡 <b>Qotil</b> o'z ishiga kirishdi..."],
    "e": ["🃏 <b>Aferist</b> soxta dalil tayyorladi..."],
    "C": ["🧑‍🔬 <b>Kimyogar</b> eliksir aralashtirmoqda..."],
    "l": ["🦎 <b>Buqalamun</b> rangini o'zgartirmoqda..."],
    "d": ["🛍 <b>Sotuvchi</b> kimningdir eshigini qoqdi..."],
    "R": ["💰 <b>Rais</b> kimgadir pul uzatdi..."],
    "W": ["🧙‍♀️ <b>Sehrgar</b> sehrli tayoqchasini ko'tardi..."],
    "r": ["🎖 <b>Janob</b> kimgadir ta'zim qildi..."],
    "Z": ["🧟 <b>Zombi</b> ochlikdan o'rnidan turdi..."],
    "pet": ["🐺 Kimningdir <b>Geroy</b>i ovga chiqdi..."],
}


async def announce_night(g: Game, kind: str):
    """Tunda rol harakat qilsa — guruhga (nishonni oshkor qilmasdan) e'lon qiladi."""
    if g.state != "night" or kind in g.announced or kind not in NIGHT_ANN:
        return
    if kind == "k":   # mafiya jamoasi hammasi tanlab bo'lgandagina
        team_k = [x for x in g.alive() if x.role in ("mafia", "don")]
        if any(x.id not in g.acts for x in team_k) or not any(a[0] == "k" for a in g.acts.values()):
            return
    g.announced.add(kind)
    await send(g.chat_id, random.choice(NIGHT_ANN[kind]))


async def send_night_prompts(g: Game):
    for p in g.alive():
        if p.role not in ROLE_KINDS:
            continue
        ok, why = role_ready(g, p)
        if not ok:
            g.acts[p.id] = ("x", 0)
            await send(p.id, f"🌙 <b>Tun {g.day}</b>\n{why}")
            continue
        if p.role == "kom":
            kb = InlineKeyboardBuilder()
            kb.button(text="🔍 Tekshirish", callback_data=f"nm:{g.chat_id}:c")
            kb.button(text="🔫 Otish", callback_data=f"nm:{g.chat_id}:s")
            kb.button(text="⏭ O'tkazish", callback_data=f"n:{g.chat_id}:x:0")
            kb.adjust(2, 1)
            await send(p.id, f"🌙 <b>Tun {g.day}</b>\nNima qilasiz?", reply_markup=kb.as_markup())
        else:
            kind = next(iter(ROLE_KINDS[p.role]))
            await send(p.id, f"🌙 <b>Tun {g.day}</b>\n{PROMPTS[kind]}", reply_markup=target_kb(g, p, kind))


async def night_phase(g: Game):
    g.day += 1
    g.state = "night"
    g.acts = {}
    g.muted = set()
    g.pet = {}
    g.immune = set()
    g.announced = set()
    g.night_event = asyncio.Event()
    await send_scene(g.chat_id, "night",
               f"🌙 <b>{g.day}-TUN</b>\n"
               "━━━━━━━━━━━━━━━━━━\n"
               "Shahar uyquga ketdi... 😴\nMaxsus rollar botga o'tib harakat qilsin!\n\n"
               f"👥 <b>Tirik o'yinchilar ({len(g.alive())}):</b>\n{alive_list(g)}\n\n"
               f"⏳ Tun <b>{NIGHT_TIME}</b> soniya davom etadi",
               reply_markup=bot_btn())
    await send_night_prompts(g)
    await send_pet_prompts(g)
    if all_acted(g):
        await asyncio.sleep(5)
    else:
        try:
            await asyncio.wait_for(g.night_event.wait(), NIGHT_TIME)
        except asyncio.TimeoutError:
            pass
    g.state = "resolving"
    await resolve_night(g)


@router.callback_query(F.data.startswith("nm:"))
async def night_mode_cb(cq: CallbackQuery):
    try:
        _, chat, kind = cq.data.split(":")
        g = GAMES.get(int(chat))
    except ValueError:
        return await cq.answer()
    p = g.players.get(cq.from_user.id) if g else None
    if not g or g.state != "night" or not p or not p.alive or p.role != "kom" or p.id in g.acts:
        return await cq.answer("Hozir bu harakat mumkin emas.", show_alert=True)
    await safe_edit(cq.message, f"🌙 <b>Tun {g.day}</b>\n{PROMPTS[kind]}", reply_markup=target_kb(g, p, kind))
    await cq.answer()


SELLER_ITEMS = ("shield", "immune", "vote2", "fakedoc")
SELLER_CUT = 20     # sotuvchi foizi
RAIS_GIFT = 100


def seller_kb(g: Game, seller_id: int):
    kb = InlineKeyboardBuilder()
    for k in SELLER_ITEMS:
        it = ITEMS[k]
        kb.button(text=f"{it['name']} — {it['price']}💵", callback_data=f"sl:{g.chat_id}:{seller_id}:{k}")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data.startswith("sl:"))
async def seller_buy(cq: CallbackQuery):
    try:
        _, chat, sid, key = cq.data.split(":")
        g = GAMES.get(int(chat))
        sid = int(sid)
    except ValueError:
        return await cq.answer()
    if key not in SELLER_ITEMS or not g or g.state == "end":
        return await cq.answer("Do'kon yopilgan.", show_alert=True)
    buyer = g.players.get(cq.from_user.id)
    if not buyer or not buyer.alive:
        return await cq.answer("Do'kon yopilgan.", show_alert=True)
    price = ITEMS[key]["price"]
    if not spend(buyer.id, "money", price):
        return await cq.answer("Pulingiz yetmaydi.", show_alert=True)
    inv_add(buyer.id, key, 1)
    cut = price * SELLER_CUT // 100
    seller = g.players.get(sid)
    if seller and cut:
        add_money(sid, cut)
        await send(sid, f"🛍 {esc(buyer.name)} xarid qildi: +<b>{cut}💵</b>")
    await cq.answer(f"✅ {ITEMS[key]['name']} sotib olindi", show_alert=True)


@router.callback_query(F.data.startswith("n:"))
async def night_cb(cq: CallbackQuery):
    try:
        _, chat, kind, target = cq.data.split(":")
        g = GAMES.get(int(chat))
        target = int(target)
    except ValueError:
        return await cq.answer()
    p = g.players.get(cq.from_user.id) if g else None
    if not g or g.state != "night" or not p or not p.alive:
        return await cq.answer("Bu tun allaqachon tugagan.", show_alert=True)
    if p.id in g.acts:
        return await cq.answer("Siz allaqachon tanlagansiz.", show_alert=True)
    if kind != "x" and not role_ready(g, p)[0]:
        return await cq.answer("Hozir bu harakat mumkin emas.", show_alert=True)
    if kind == "x":
        g.acts[p.id] = ("x", 0)
        await safe_edit(cq.message, "⏭ Bu tun harakat qilmadingiz.")
    else:
        q = g.players.get(target) if kind != "u" else p
        if kind not in ROLE_KINDS.get(p.role, set()) or not q or (kind != "u" and not can_target(p, q, kind)):
            return await cq.answer("Noto'g'ri tanlov.", show_alert=True)
        g.acts[p.id] = (kind, target)
        if kind == "h" and target == p.id:
            p.healed_self = True
        await safe_edit(cq.message, "✅ Veto tayyor." if kind == "u" else f"✅ Tanlov: <b>{esc(q.name)}</b>")
        if kind in MAFIA_KINDS:  # mafiya jamoasiga bildirish
            for t in g.alive():
                if team(t.role) == "mafia" and t.id != p.id:
                    await send(t.id, f"🗳 {esc(p.name)} → <b>{esc(q.name)}</b>")
        spawn(announce_night(g, kind))
    await cq.answer()
    if all_acted(g) and g.night_event:
        g.night_event.set()


async def resolve_night(g: Game):
    pl = g.players
    acts = g.acts
    kez_blocked = {t for u, (k, t) in acts.items() if k == "b" and pl[u].alive}
    jailed = {t for u, (k, t) in acts.items() if k == "i" and pl[u].alive and u not in kez_blocked}
    blocked = kez_blocked | jailed
    valid = {u: (k, t) for u, (k, t) in acts.items()
             if k != "x" and u not in blocked and pl[u].alive and not pl[u].zomb}
    for b in kez_blocked:
        if pl[b].alive:
            await send(b, "💃 Bu tun sizni mashuqa band qildi — harakat qila olmadingiz!")
    for b in jailed:
        if pl[b].alive:
            await send(b, "⛓ Bu tun sizni qamoqqa olishdi — harakat qila olmadingiz, lekin sizga hujum ham o'tmadi!")

    attacks = []   # (nishon, hujumchi, zarar) — zarar None bo'lsa o'ldiradi
    kills = [(u, t) for u, (k, t) in valid.items() if k == "k"]
    if g.mafia_skip == g.day:
        kills = []
    if kills:
        cnt = Counter(t for _, t in kills)
        mx = max(cnt.values())
        tops = [t for t, c in cnt.items() if c == mx]
        don_vote = [t for u, t in kills if pl[u].role == "don" and t in tops]
        target = don_vote[0] if don_vote else random.choice(tops)
        voters = [u for u, t in kills if t == target]
        attacker = next((u for u in voters if pl[u].role == "don"), voters[0])
        attacks.append((target, attacker, None))
    for u, (k, t) in valid.items():
        if k in ("m", "s", "z", "q"):
            attacks.append((t, u, None))
            if k == "z":
                pl[u].used = True
            if k == "q":
                pl[u].cool = g.day + 2

    pet_pairs = {}   # (nishon, egasi) -> foiz (None = o'ldiradi)
    for u, t in g.pet.items():
        if t and u in pl and pl[u].alive and u not in blocked and t in pl and pl[t].alive and pl[u].hero_lvl:
            lvl = pl[u].hero_lvl
            attacks.append((t, u, hero_dmg(lvl, pl[t].maxhp)))
            pet_pairs[(t, u)] = hero_pct(lvl)
            pl[u].hero_next = g.day + 1 + HERO_REST

    heals = {t: u for u, (k, t) in valid.items() if k == "h"}
    guards = {t: u for u, (k, t) in valid.items() if k == "g"}
    adv_protected = {t for u, (k, t) in valid.items() if k == "a"}
    for u, (k, t) in valid.items():
        if k == "o":
            g.mines[t] = u   # mina portlamaguncha turadi
    elixir = {t: u for u, (k, t) in valid.items() if k == "C"}
    framed = {t for u, (k, t) in valid.items() if k == "e"}
    visits = defaultdict(list)
    for u, (k, t) in valid.items():
        visits[t].append(u)

    deaths = []
    extra = []
    hit = set()
    dmg_lines = []
    hints = {}     # o'lgan o'yinchi id -> "aytishlaricha, uning uyiga ... kelgan edi"

    def note(t: str):
        if t not in extra:
            extra.append(t)

    # ☠️ zahar (o'tgan tundagi)
    for q in list(pl.values()):
        if q.alive and q.poison and q.poison < g.day:
            q.poison = 0
            if q.id in elixir:
                await send(q.id, "🧑‍🔬 Kimyogar eliksiri sizni zahardan davoladi!")
            elif q.id in heals:
                await send(q.id, "💉 Doktor sizni zahardan davoladi!")
                await send(heals[q.id], f"✅ Siz <b>{esc(q.name)}</b> ni zahardan qutqardingiz!")
            else:
                q.alive = False
                deaths.append((q, "zahar"))
                hints[q.id] = "Aytishlaricha, kimdir uning ovqatiga zahar solgan edi..."

    for target, attacker, dmg in attacks:
        tp = pl.get(target)
        if not tp or not tp.alive:
            continue
        at = pl.get(attacker)
        if target in jailed:
            continue
        if target in g.mines and at and at.alive and g.mines[target] != attacker:
            tr = g.mines.pop(target)
            at.alive = False
            deaths.append((at, "mina"))
            extra.append(f"☠️ Mina portladi! {mention(at)} biror kishining eshigiga kirib, minaga tushdi!")
            await send(tr, f"☠️ Sizning minangiz <b>{esc(at.name)}</b> ni portlatdi!")
            continue  # mina hujumni to'xtatadi
        is_pet = (target, attacker) in pet_pairs
        if is_pet and tinfo(tp.id).get("immune"):
            await send(target, "👑 Geroy sizga hujum qildi, lekin <b>Imperator</b> unvoningiz tufayli ta'sir qilmadi!")
            await send(attacker, f"🐺 Geroy hujumi <b>{esc(tp.name)}</b> ga ta'sir qilmadi — u Imperator!")
            continue
        if target in heals:
            await send(target, "👨🏻‍⚕️ Bu tun sizga hujum bo'ldi, lekin doktor sizni qutqardi!")
            await send(heals[target], f"✅ Siz <b>{esc(tp.name)}</b> ni o'limdan qutqardingiz!")
            note("💉 <b>Doktor</b> kimningdir hayotini saqlab qoldi!")
            continue
        gu = guards.get(target)
        if gu and pl[gu].alive:
            pl[gu].alive = False
            deaths.append((pl[gu], "soqchi"))
            hints[gu] = "U boshqani himoya qilib, o'zini qurbon qildi..."
            note("🛡 <b>Soqchi</b> kimnidir o'z tanasi bilan to'sib qoldi!")
            await send(target, "🛡 Sizga hujum bo'ldi, lekin soqchi o'zini qurbon qildi!")
            continue
        if is_pet and inv_use(target, "herodef"):
            await send(target, "🔰 Geroy sizga hujum qildi, lekin <b>Geroydan himoya</b> sizni qutqardi!")
            await send(attacker, f"🐺 Geroy hujumi <b>{esc(tp.name)}</b> ga ta'sir qilmadi — u himoyalangan!")
            note("🔰 Kimningdir <b>Geroydan himoya</b>si ishga tushdi!")
            continue
        lethal = dmg is None or tp.hp <= dmg
        if not lethal:
            tp.hp -= dmg
            hit.add(target)
            pc = pet_pairs.get((target, attacker)) or max(1, dmg * 100 // max(1, tp.maxhp))
            dmg_lines.append(f"🐺 Kimdir {mention(tp)} ga Geroy bilan hujum qildi: joni -{pc}%")
            await send(target, f"🐺 <b>Geroy sizga hujum qildi!</b> Joningizning <b>{pc}%</b> i ketdi "
                               f"(qoldi {tp.hp}/{tp.maxhp}❤️)")
            continue
        if inv_use(target, "shield"):
            await send(target, "🛡 Sizga hujum bo'ldi, lekin <b>Himoya</b> narsangiz sizni qutqardi!")
            note("🛡 Kimningdir <b>Himoya</b>si ishga tushdi — hujum qaytarildi!")
            continue
        if tp.role == "luck" and random.random() < 0.5:
            await send(target, "🤞 Sizga hujum bo'ldi, lekin omadingiz keldi — tirik qoldingiz!")
            note("🤞 Kimningdir omadi keldi — o'q nishonga tegmadi!")
            continue
        if tp.armor:
            tp.armor = False
            await send(target, "💪 Sizga hujum bo'ldi, lekin <b>Polvon</b> zirhi sizni qutqardi (1 marta)!")
            note("💪 Kimningdir <b>zirhi</b> hujumni qaytardi!")
            continue
        if tp.tshield:
            tp.tshield = False
            await send(target, f"{tinfo(target).get('name', '🏅')} <b>unvoningiz</b> o'limdan qutqardi (o'yinda 1 marta)!")
            note("🏅 Kimningdir <b>unvoni</b> uni o'limdan qutqardi!")
            continue
        if inv_use(target, "extralife"):
            await send(target, "❤️ Sizga hujum bo'ldi, lekin <b>Zaxira hayot</b> sizni o'limdan qutqardi!")
            note("❤️ Kimningdir <b>Zaxira hayoti</b> ishga tushdi!")
            continue
        tp.alive = False
        deaths.append((tp, "hujum"))
        if is_pet:
            hints[tp.id] = "Aytishlaricha, uning uyiga <b>🐺 Geroy</b> hujum qilgan edi..."
        elif at:
            hints[tp.id] = f"Aytishlaricha, uning uyiga <b>{rname(at.role)}</b> kelgan edi..."
        else:
            hints[tp.id] = "Uning o'limi sirligicha qoldi..."
        if tp.role == "hunter":
            a = pl.get(attacker)
            if a and a.alive:
                a.alive = False
                deaths.append((a, "ovchi"))
                hints[a.id] = "Mergan o'lim oldidan uni ham o'zi bilan olib ketdi..."
                extra.append(f"🏹 Mergan {mention(tp)} o'lar ekan, qotilini ham o'zi bilan olib ketdi!")
        if tp.role == "sheep" and at and team(at.role) == "mafia" and attacker in {u for u, t in kills}:
            g.mafia_skip = g.day + 1
            extra.append(f"🐑 {mention(tp)} — Qo'y edi! Mafiya uni o'ldirgani uchun keyingi tunda hujum qila olmaydi.")

    # axborot va boshqa harakatlar
    revived = []
    dead_ids = {d.id for d, _ in deaths}
    for u, (k, t) in valid.items():
        tp = pl.get(t)
        if not tp:
            continue
        if k == "c":
            is_mafia = (team(tp.role) == "mafia" and tp.role != "don" and t not in adv_protected) \
                or tp.role == "fool" or t in framed
            if is_mafia and inv_use(t, "fakedoc"):
                is_mafia = False
                note("📁 Kimningdir <b>soxta hujjati</b> ishga tushdi!")
            res = "🔴 <b>Mafiya</b>" if is_mafia else "🟢 <b>Tinch aholi</b> (mafiya emas)"
            await send(u, f"🔍 Tekshiruv natijasi: <b>{esc(tp.name)}</b> — {res}")
        elif k == "j":
            await send(u, f"🕶 <b>{esc(tp.name)}</b> — {rname(tp.role)}")
            for q in pl.values():
                if q.alive and q.id != u and team(q.role) == "mafia":
                    await send(q.id, f"{rname(pl[u].role)} aniqladi: <b>{esc(tp.name)}</b> — {rname(tp.role)}")
        elif k == "v":
            vis = [esc(pl[x].name) for x in visits[t] if x != u]
            txt = ", ".join(vis) if vis else "hech kim kelmadi"
            await send(u, f"🧙‍♂️ <b>{esc(tp.name)}</b> uyiga bu tun: {txt}")
        elif k == "f":
            act = valid.get(t)
            if act and act[1] in pl and act[0] not in ("u",):
                await send(u, f"🐾 <b>{esc(tp.name)}</b> bu tun <b>{esc(pl[act[1]].name)}</b> ning uyiga bordi.")
            else:
                await send(u, f"🐾 <b>{esc(tp.name)}</b> bu tun uyidan chiqmadi.")
        elif k == "p":
            if tp.alive and t not in jailed:
                tp.poison = g.day
        elif k == "w":
            if tp.alive and t not in jailed:
                g.muted.add(t)
                await send(t, "🌀 Sizni gipnoz qilishdi — bugun ovoz bera olmaysiz!")
        elif k == "t":
            amt = min(30, get_bal(t)[0])
            if amt > 0:
                add_money(t, -amt)
                add_money(u, amt)
                await send(u, f"🥷 <b>{esc(tp.name)}</b> dan <b>{amt}💵</b> o'g'irladingiz!")
                await send(t, f"🥷 Kimdir sizning hamyoningizdan <b>{amt}💵</b> o'g'irladi!")
            else:
                await send(u, f"🥷 <b>{esc(tp.name)}</b> ning cho'ntagi bo'sh ekan.")
        elif k == "y":
            pl[u].used = True
            if not tp.alive and t not in dead_ids:
                tp.alive = True
                tp.hp = tp.maxhp
                tp.poison = 0
                revived.append(tp)
                await send(t, "⛪️ Ruhoniy sizni tiriltirdi! O'yinga qaytdingiz.")
        elif k == "u":
            g.veto = True
            pl[u].used = True
            await send(u, "⚖️ Veto qo'yildi: keyingi kunduzgi osish bekor bo'ladi.")
        elif k == "C":
            if tp.alive:
                was = tp.poison or tp.zomb
                tp.poison = 0
                tp.zomb = False
                tp.hp = min(tp.maxhp, tp.hp + 50)
                await send(t, "🧑‍🔬 Kimyogar sizga eliksir berdi: " + ("kasallik yo'qoldi, " if was else "") + f"❤️ {tp.hp}/{tp.maxhp}")
                await send(u, f"🧑‍🔬 Siz <b>{esc(tp.name)}</b> ga eliksir berdingiz.")
        elif k == "l":
            pl[u].cham_t = t
            await send(u, f"🦎 Siz <b>{esc(tp.name)}</b> ni kuzatyapsiz. U o'lsa, uning rolini olasiz.")
        elif k == "d":
            if tp.alive:
                await send(t, "🛍 <b>Sotuvchi</b> sizga do'kon ochdi. Hamyoningizdan to'lanadi:",
                           reply_markup=seller_kb(g, u))
                await send(u, f"🛍 <b>{esc(tp.name)}</b> ga do'kon ochildi. Sotilsa, 20% sizniki.")
        elif k == "R":
            if tp.alive:
                add_money(t, RAIS_GIFT)
                await send(t, f"💰 Rais sizga <b>{RAIS_GIFT}💵</b> berdi.")
                await send(u, f"💰 <b>{esc(tp.name)}</b> ga {RAIS_GIFT}💵 berildi.")
        elif k == "r":
            if tp.alive:
                g.immune.add(t)
                await send(t, "🎖 Janob sizga ta'zim qildi — bugun sizni osib bo'lmaydi!")
                await send(u, f"🎖 <b>{esc(tp.name)}</b> bugun osilishdan himoyalandi.")
        elif k == "Z":
            if tp.alive and t not in jailed and t not in heals and t not in elixir and not tp.zomb:
                tp.zomb = True
                await send(t, "🧟 Sizni zombi tishladi! Endi siz zombi tarafdasiz va tungi harakat qila olmaysiz. "
                              "Doktor yoki Kimyogar davolashi mumkin.")
                await send(u, f"🧟 <b>{esc(tp.name)}</b> zombiga aylandi!")
            elif tp.alive:
                await send(u, f"🧟 <b>{esc(tp.name)}</b> ni tishlay olmadingiz — u himoyalangan.")
        elif k == "W":
            me = pl[u]
            if tp.alive and me.alive and tp.role != "mage":
                me.role, tp.role = tp.role, me.role
                me.used, tp.used = False, True
                me.cool = tp.cool = 0
                await send(u, f"🧙‍♀️ Almashtirildi! Endi sizning rolingiz: <b>{rname(me.role)}</b>\n\n{ROLES[me.role][2]}")
                await send(t, f"🧙‍♀️ Sehrgar sizning rolingizni almashtirdi! Endi siz: <b>{rname(tp.role)}</b>")
                if team(me.role) == "mafia":
                    names = ", ".join(esc(x.name) for x in pl.values() if team(x.role) == "mafia" and x.alive)
                    await send(u, f"🤵🏻 Mafiya jamoasi: {names}")

    for t, d in heals.items():
        hp_ = pl.get(t)
        if hp_ and hp_.alive and hp_.zomb:
            hp_.zomb = False
            await send(t, "👨🏻‍⚕️ Doktor sizni zombi infeksiyasidan davoladi!")
            await send(d, f"✅ Siz <b>{esc(hp_.name)}</b> ni zombilikdan qutqardingiz!")

    # ❤️ jon tiklanishi (tunda hujum olmaganlar)
    for q in pl.values():
        if q.alive and q.id not in hit and q.hp < q.maxhp:
            q.hp = min(q.maxhp, q.hp + 10)

    # ertalab
    g.state = "day"
    lines = [f"🌅 <b>TONG OTDI!</b>  ·  {g.day}-kun", "━━━━━━━━━━━━━━━━━━"]
    if not deaths:
        lines += ["", random.choice(NO_DEATH_TEXTS)]
    for d, _ in deaths:
        lines.append("")
        lines.append(f"💀 Bu tun {mention(d)} hayotdan ko'z yumdi.")
        h = hints.get(d.id)
        if h:
            lines.append(f"🕯 <i>{h}</i>")
        lines.append(f"🎭 U — <b>{rname(d.role)}</b> edi.")
        await notify_dead(g, d, "☠️ Siz o'ldingiz. O'yin tugaguncha guruhda yozmang.")
    if extra:
        lines.append("")
        lines.extend(extra)
    if dmg_lines:
        lines.append("")
        lines.extend(dmg_lines)
    for r in revived:
        lines.append(f"\n⛪️ <b>Mo'jiza!</b> {mention(r)} tirildi!")
    lines += ["", "━━━━━━━━━━━━━━━━━━", f"👥 Tirik: <b>{len(g.alive())}</b> kishi"]
    await send_scene(g.chat_id, "day", "\n".join(lines))
    for d, _ in deaths:
        await fx_announce(g, d.id, "die", d.name)
    await promote_roles(g)


NO_DEATH_TEXTS = [
    "😮‍💨 <b>Bu tunda hech kim o'lmadi</b> — ishonish qiyin, lekin shunday!",
    "🕊 Shahar tinch uxladi: <b>bu tunda hech kimning joni olinmadi</b>...",
    "🤔 Mafiya adashdimi yoki doktor ulgurdimi? <b>Bu tunda hech kim o'lmadi!</b>",
    "🌤 Hamma tirik! Qotillar bu tun nishonga tegmadi — kimdir omadli ekan.",
    "🙌 <b>Tong tinch otdi.</b> Bu kecha hech kim o'lmadi — shahar nafas rostladi.",
]


# ───────────────────────── KUN VA OVOZ BERISH ─────────────────────────
async def day_phase(g: Game):
    if check_win(g):
        return
    g.state = "day"
    await send_scene(g.chat_id, "noon",
               f"☀️ <b>{g.day}-KUN</b>\n"
               "━━━━━━━━━━━━━━━━━━\n"
               f"Muhokama vaqti! Kim mafiya? 🕵️\n⏳ <b>{DAY_TIME}</b> soniya\n\n"
               f"👥 <b>Tirik o'yinchilar ({len(g.alive())}):</b>\n{alive_list(g)}")
    await asyncio.sleep(DAY_TIME)


# ── ovoz berish: har bir o'yinchi botda (shaxsiy chatda) ovoz beradi ──
def vote_kb(g: Game):
    kb = InlineKeyboardBuilder()
    for q in g.alive():
        kb.button(text=q.name, callback_data=f"v:{g.chat_id}:{q.id}")
    kb.button(text="🚫 Hech kim", callback_data=f"v:{g.chat_id}:0")
    kb.adjust(2)
    return kb.as_markup()


async def announce_vote(g: Game, text: str):
    for _ in range(3):
        try:
            await bot.send_message(g.chat_id, text)
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after, 10) + 0.5)
        except TelegramAPIError as e:
            log.warning("ovoz e'loni xato: %s", e)
            return


async def vote_phase(g: Game) -> Optional[str]:
    if check_win(g):
        return None
    g.state = "vote"
    g.votes = {}
    g.vote_dm = {}
    g.vote_event = asyncio.Event()
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 Botga o'tish", url=bot_link())
    msg = await send_scene(g.chat_id, "vote",
                     "🗳 <b>OVOZ BERISH BOSHLANDI!</b>\n"
                     "━━━━━━━━━━━━━━━━━━\n"
                     f"⏳ <b>{VOTE_TIME}</b> soniya\n"
                     "Har bir o'yinchiga botdan xabar yuborildi — kimni osishni botda tanlang.\n"
                     "Kim kimga ovoz bergani shu yerda e'lon qilinadi.",
                     reply_markup=kb.as_markup())
    g.vote_msg_id = msg.message_id if msg else 0
    failed = []
    for p in g.alive():
        if p.id in g.muted:
            await send(p.id, "🌀 Siz gipnoz ostidasiz — bugun ovoz bera olmaysiz.")
            continue
        dm = await send(p.id, f"🗳 <b>Ovoz berish!</b>\n«{esc(g.title)}» guruhi — kimni osamiz?",
                        reply_markup=vote_kb(g))
        if dm:
            g.vote_dm[p.id] = dm.message_id
        else:
            failed.append(p)
    if failed:
        await send(g.chat_id, "⚠️ Botga xabar yuborib bo'lmadi: " + ", ".join(mention(p) for p in failed) +
                   "\nBotga o'tib /start bosing.")
    try:
        await asyncio.wait_for(g.vote_event.wait(), VOTE_TIME)
    except asyncio.TimeoutError:
        pass
    g.state = "resolving"
    try:
        await bot.edit_message_reply_markup(chat_id=g.chat_id, message_id=g.vote_msg_id, reply_markup=None)
    except TelegramAPIError:
        pass
    for uid, mid in list(g.vote_dm.items()):
        if uid not in g.votes:
            try:
                await bot.edit_message_text("⌛ Ovoz berish vaqti tugadi.", chat_id=uid, message_id=mid)
            except TelegramAPIError:
                pass

    tally = Counter()
    used2 = False
    for voter, tgt in g.votes.items():
        w = 1
        if tgt and inv_use(voter, "vote2"):
            w = 2
            used2 = True
        if g.players[voter].role == "mayor":
            w *= 2
        tally[tgt] += w
    if used2:
        await send(g.chat_id, "🗳 Kimningdir <b>Qo'shimcha ovoz</b> narsasi ishga tushdi!")
    if g.veto:
        g.veto = False
        await send(g.chat_id, "⚖️ <b>Sudya veto qo'ydi!</b> Bugun hech kim osilmaydi.")
        return None
    skip = tally.pop(0, 0)
    if not tally:
        await send(g.chat_id, "🕊 <b>Hech kim osilmadi.</b> Shahar bugun hech kimni jazolamadi.")
        return None
    top = tally.most_common()
    best_id, best_c = top[0]
    if (len(top) > 1 and top[1][1] == best_c) or best_c <= skip:
        await send(g.chat_id, "🕊 <b>Ovozlar kelishmadi</b> — hech kim osilmadi.")
        return None

    victim = g.players[best_id]
    # 👍/👎 — haqiqatan ham osamizmi? (hamma tasdiqlaydi)
    if not await confirm_hang(g, victim):
        g.immune.clear()
        return None
    if best_id in g.immune:
        g.immune.clear()
        await send(g.chat_id, f"🎖 {mention(victim)} osilishi kerak edi, lekin <b>Janob</b> unga ta'zim qilib himoya qildi — bugun hech kim osilmadi!")
        return None
    g.immune.clear()
    if inv_use(victim.id, "immune"):
        await send(g.chat_id, f"⚖️ {mention(victim)} osilishi kerak edi, lekin <b>Immunitet</b> uni saqlab qoldi!")
        await send(victim.id, "⚖️ Immunitet narsangiz sizni osilishdan saqladi!")
        return None
    if inv_use(victim.id, "extralife"):
        await send(g.chat_id, f"⚖️ {mention(victim)} osilishi kerak edi, lekin <b>Zaxira hayot</b> uni saqlab qoldi!")
        await send(victim.id, "❤️ Zaxira hayot sizni osilishdan saqladi!")
        return None
    victim.alive = False
    await send(g.chat_id, "🪢 <b>HUKM ijro etildi!</b>\n━━━━━━━━━━━━━━━━━━\n"
                          f"{mention(victim)} shahar hukmi bilan osildi.\n🎭 U — <b>{rname(victim.role)}</b> edi.")
    await notify_dead(g, victim, "☠️ Siz osildingiz.")
    await fx_announce(g, victim.id, "die", victim.name)
    if victim.role == "suit":
        return "suit"
    if victim.role == "kam":
        voters = [g.players[v] for v, t in g.votes.items() if t == victim.id and g.players[v].alive]
        if voters:
            x = random.choice(voters)
            x.alive = False
            await send(g.chat_id,
                       f"💣 <b>Kamikaze portladi</b> va {mention(x)} ni o'zi bilan olib ketdi!\n"
                       f"🎭 U — <b>{rname(x.role)}</b> edi.")
            await notify_dead(g, x, "☠️ Kamikaze sizni o'zi bilan olib ketdi.")
            await fx_announce(g, x.id, "die", x.name)
    return None


@router.callback_query(F.data.startswith("v:"))
async def vote_cb(cq: CallbackQuery):
    try:
        _, chat, target = cq.data.split(":")
        g = GAMES.get(int(chat))
        target = int(target)
    except ValueError:
        return await cq.answer()
    if not g or g.state != "vote":
        return await cq.answer("Ovoz berish tugagan.", show_alert=True)
    p = g.players.get(cq.from_user.id)
    if not p or not p.alive:
        return await cq.answer("Siz ovoz bera olmaysiz.", show_alert=True)
    if p.id in g.votes:
        return await cq.answer("Siz allaqachon ovoz berdingiz.", show_alert=True)
    if p.id in g.muted:
        return await cq.answer("🌀 Siz gipnoz ostidasiz — bugun ovoz bera olmaysiz.", show_alert=True)
    if target and (target not in g.players or not g.players[target].alive):
        return await cq.answer("Noto'g'ri tanlov.", show_alert=True)
    g.votes[p.id] = target
    tp = g.players.get(target) if target else None
    await cq.answer("✅ Ovozingiz qabul qilindi")
    if cq.message:
        await safe_edit(cq.message,
                        f"✅ Siz <b>{esc(tp.name)}</b> ga ovoz berdingiz." if tp
                        else "✅ Siz hech kimni osmaslikka ovoz berdingiz.")
    if tp:
        spawn(announce_vote(g, f"🗳 <b>{esc(p.name)}</b> → <b>{esc(tp.name)}</b> ga ovoz berdi"))
    else:
        spawn(announce_vote(g, f"🗳 <b>{esc(p.name)}</b> → 🚫 hech kimga ovoz bermadi"))
    if len(g.votes) >= len([x for x in g.alive() if x.id not in g.muted]) and g.vote_event:
        g.vote_event.set()


# ── 👍/👎 osishni tasdiqlash ──
def confirm_kb(g: Game, yes: int, no: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"👍 Osilsin  ·  {yes}", callback_data=f"cf:{g.chat_id}:1")
    kb.button(text=f"👎 Tirik qolsin  ·  {no}", callback_data=f"cf:{g.chat_id}:0")
    kb.adjust(2)
    return kb.as_markup()


def confirm_counts(c: dict):
    yes = sum(1 for v in c["votes"].values() if v)
    return yes, len(c["votes"]) - yes


async def confirm_hang(g: Game, victim: Player) -> bool:
    """Ko'p ovoz olgan o'yinchini osishdan oldin hamma 👍/👎 bilan tasdiqlaydi. 👍 ko'p bo'lsa — osiladi."""
    eligible = {p.id for p in g.alive() if p.id != victim.id and p.id not in g.muted}
    if not eligible:
        return True
    g.confirm = {"target": victim.id, "votes": {}, "elig": eligible}
    g.confirm_event = asyncio.Event()
    g.state = "confirm"
    msg = await send(g.chat_id,
                     "⚖️ <b>HUKM VAQTI!</b>\n━━━━━━━━━━━━━━━━━━\n"
                     f"Ko'pchilik ovozi bilan {mention(victim)} aybdor deb topildi.\n\n"
                     "❓ <b>Haqiqatan ham uni osamizmi?</b>\n"
                     "👍 — ha, osilsin\n👎 — yo'q, tirik qolsin\n\n"
                     f"⏳ <b>{CONFIRM_TIME}</b> soniya · ovoz bera oladiganlar: {len(eligible)} kishi",
                     reply_markup=confirm_kb(g, 0, 0))
    try:
        await asyncio.wait_for(g.confirm_event.wait(), CONFIRM_TIME)
    except asyncio.TimeoutError:
        pass
    g.state = "resolving"
    yes, no = confirm_counts(g.confirm)
    g.confirm = None
    if msg:
        try:
            await msg.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
    if yes > no:
        await send(g.chat_id, f"👍 <b>{yes}</b> : 👎 <b>{no}</b>\nShahar rozi — {mention(victim)} osiladi!")
        return True
    await send(g.chat_id, f"👍 <b>{yes}</b> : 👎 <b>{no}</b>\n🕊 Shahar {mention(victim)} ni osishni xohlamadi — "
                          "<b>u tirik qoladi!</b>")
    return False


@router.callback_query(F.data.startswith("cf:"))
async def confirm_cb(cq: CallbackQuery):
    try:
        _, chat, val = cq.data.split(":")
        g = GAMES.get(int(chat))
    except ValueError:
        return await cq.answer()
    c = g.confirm if g else None
    if not g or g.state != "confirm" or not c:
        return await cq.answer("Bu ovoz berish tugagan.", show_alert=True)
    uid = cq.from_user.id
    if uid == c["target"]:
        return await cq.answer("Siz o'z hukmingizga ovoz bera olmaysiz.", show_alert=True)
    if uid not in c["elig"]:
        return await cq.answer("Faqat tirik o'yinchilar ovoz bera oladi.", show_alert=True)
    c["votes"][uid] = (val == "1")      # fikrini o'zgartirish mumkin
    yes, no = confirm_counts(c)
    await cq.answer("👍 Osilsin" if val == "1" else "👎 Tirik qolsin")
    if cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=confirm_kb(g, yes, no))
        except TelegramAPIError:
            pass
    if len(c["votes"]) >= len(c["elig"]) and g.confirm_event:
        g.confirm_event.set()


# ── 🕯 oxirgi so'z ──
LASTWORDS: dict = {}   # user_id -> {"g": Game, "exp": vaqt, "name": ism}
LAST_STYLES = [
    "🕯 <b>{n}</b> so'nggi nafasida shunday dedi:\n«<i>{t}</i>»",
    "😱 Kimdir <b>{n}</b> ning oxirgi qichqirig'ini eshitdi:\n«<i>{t}</i>»",
    "🥀 <b>{n}</b> ning oxirgi so'zlari:\n«<i>{t}</i>»",
]


async def ask_last_words(g: Game, p: Player):
    now = time.time()
    for k in [k for k, v in LASTWORDS.items() if v["exp"] < now - 600]:
        LASTWORDS.pop(k, None)
    LASTWORDS[p.id] = {"g": g, "exp": now + LAST_WORD_TIME, "name": p.name}
    await send(p.id, "🕯 <b>Oxirgi so'z</b>\n"
                     f"Guruhga oxirgi bir og'iz so'z qoldirmoqchimisiz? ✍️ <b>{LAST_WORD_TIME}</b> soniya ichida "
                     "shu yerga yozing (200 belgigacha).\n<i>Vaqt o'tib yozilsa — qabul qilinmaydi.</i>")


def has_lastword(m: Message) -> bool:
    return m.from_user is not None and m.from_user.id in LASTWORDS


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"), has_lastword)
async def lastword_input(m: Message):
    e = LASTWORDS.pop(m.from_user.id, None)
    if not e:
        return
    g = e["g"]
    if time.time() > e["exp"] or g.state == "end" or GAMES.get(g.chat_id) is not g:
        await m.answer("⌛ Kech qoldingiz — oxirgi so'z <b>qabul qilinmadi</b>.")
        return
    txt = esc((m.text or "").strip()[:200])
    if not txt:
        return
    await m.answer("🕯 Oxirgi so'zingiz guruhga yetkazildi.")
    link = f'<a href="tg://user?id={m.from_user.id}">{esc(e["name"])}</a>'
    out = fx_text(m.from_user.id, "last", link, txt) or random.choice(LAST_STYLES).format(n=link, t=txt)
    await send(g.chat_id, out)


# ───────────────────────── O'YIN YAKUNI ─────────────────────────
def team_won(p: Player, w: str) -> bool:
    if w == "town":
        return team(p.role) == "town" and not p.zomb
    if w == "mafia":
        return team(p.role) == "mafia" and not p.zomb
    if w == "man":
        return p.role == "man"
    if w == "suit":
        return p.role == "suit"
    if w == "zombi":
        return p.role == "zombi" or p.zomb
    return False


async def finish_game(g: Game, w: str):
    g.state = "end"
    titles = {"town": "👨🏼 Tinch aholi jamoasi", "mafia": "🤵🏻 Mafiya jamoasi",
              "man": "🔪 Manyak", "suit": "🤦🏼 Suitsid", "zombi": "🧟 Zombi", "draw": "🤝 Durang"}
    lines = ["🏁 <b>O'YIN TUGADI!</b>", "━━━━━━━━━━━━━━━━━━",
             f"🏆 G'olib: <b>{titles[w]}</b>", "", "👥 <b>O'yinchilar:</b>"]
    rewards = {}
    winners = []
    boosted = False
    for p in g.players.values():
        win = team_won(p, w)
        mark = "🏆" if win else ("🙂" if p.alive else "💀")
        lines.append(f"{mark} {mention(p)} — {rname(p.role)}")
        add_result(p.id, p.name, win)
        reward = REWARD_WIN if win else REWARD_PLAY
        mult = (6 if inv_use(p.id, "megaboost") else 4 if inv_use(p.id, "superboost")
                else (2 if inv_use(p.id, "boost") else 1))
        boosted = boosted or mult > 1
        reward *= mult
        if p.role == "rais":
            reward *= 2     # 💰 Rais: mukofot 2 barobar
        if fx_active(p.id) == "fx_owner":
            reward *= 3     # 👑 Owner aura
        reward = reward * (100 + tinfo(p.id).get("reward", 0)) // 100
        add_money(p.id, reward)
        if win:
            winners.append(p)
        rewards[p.id] = (reward, mult)
    kv_set("cnt_games", int(kv_get("cnt_games", "0") or 0) + 1)
    if boosted:
        lines.append("\n💰 Kimningdir <b>Boost</b> narsasi ishga tushdi!")
    lines.append("\n━━━━━━━━━━━━━━━━━━\nYana o'ynash uchun: /game")
    await send_scene(g.chat_id, {"town": "win_town", "mafia": "win_mafia"}.get(w, "win_other"),
                     "\n".join(lines))
    for p in winners:    # ✨ g'olib effekt egalari uchun alohida e'lon
        await fx_announce(g, p.id, "win", p.name)
    record_chat_game(g.chat_id)
    for uid, (amt, mult) in rewards.items():
        txt = f"💵 O'yin mukofoti: <b>+{amt}</b>" + (f" (💰 Boost ×{mult})" if mult > 1 else "")
        await send(uid, txt + "\nDo'kon: /shop")


# ───────────────────────── IQTISOD: PUL, OLMOS, DO'KON ─────────────────────────
REWARD_PLAY = 30        # o'yinda qatnashgani uchun
REWARD_WIN = 100        # g'alaba uchun
DAILY_BONUS = 100       # kunlik bonus
DIAMOND_RATE = 100      # 1 olmos = necha pul
REBIRTH_COST = 1        # qayta tug'ilish narxi (olmos)
VIP_DIAMONDS = 20       # 30 kunlik VIP narxi (olmos)

# Narsalar: kuchiga qarab narx. cur: "money" (💵) yoki "dia" (💎). tier: 1 (oddiy) ... 5 (afsonaviy)
TIERS = {1: "⚪️ Oddiy", 2: "🟢 Yaxshi", 3: "🔵 Kuchli", 4: "🟣 Epik", 5: "🟠 Afsonaviy"}
ITEMS = {
    # ---- 💵 pul bilan ----
    "vote2": {"name": "🗳 Qo'shimcha ovoz", "cur": "money", "price": 250, "tier": 1,
              "desc": "Kunduzgi ovoz berishda ovozingiz 2 ta hisoblanadi (1 marta)."},
    "boost": {"name": "💰 Boost ×2", "cur": "money", "price": 300, "tier": 1,
              "desc": "Keyingi o'yindagi pul mukofoti 2 barobar bo'ladi (1 marta)."},
    "shield": {"name": "🛡 Himoya", "cur": "money", "price": 500, "tier": 2,
               "desc": "Tungi hujumdan 1 marta saqlaydi."},
    "fakedoc": {"name": "📁 Soxta hujjat", "cur": "money", "price": 700, "tier": 2,
                "desc": "Mafiya jamoasida bo'lsangiz, komissar tekshiruvida 1 marta tinch aholi bo'lib ko'rinasiz."},
    "immune": {"name": "⚖️ Immunitet", "cur": "money", "price": 900, "tier": 3,
               "desc": "Kunduzgi osilishdan 1 marta saqlaydi."},
    # ---- 💎 olmos bilan (kuchliroq) ----
    "seer": {"name": "🔮 Ko'ruvchi", "cur": "dia", "price": 3, "tier": 3,
             "desc": "O'yin boshida mafiya jamoasidan bir a'zoni aniq bilib olasiz (tinch tomon uchun)."},
    "superboost": {"name": "💎 Super Boost ×4", "cur": "dia", "price": 3, "tier": 3,
                   "desc": "Keyingi o'yindagi pul mukofoti 4 barobar bo'ladi (1 marta)."},
    "t_doc": {"name": "🎟 Doktor chiptasi", "cur": "dia", "price": 4, "tier": 4,
              "desc": "Keyingi o'yinda sizga Doktor roli tushadi (o'yinda Doktor bo'lsa)."},
    "t_mafia": {"name": "🎟 Mafiya chiptasi", "cur": "dia", "price": 6, "tier": 4,
                "desc": "Keyingi o'yinda sizga mafiya jamoasidan rol tushadi."},
    "t_kom": {"name": "🎟 Komissar chiptasi", "cur": "dia", "price": 8, "tier": 5,
              "desc": "Keyingi o'yinda sizga Komissar roli tushadi (o'yinda Komissar bo'lsa)."},
    "extralife": {"name": "❤️ Zaxira hayot", "cur": "dia", "price": 10, "tier": 5,
                  "desc": "O'limdan (tungi hujum yoki osilish) 1 marta darhol saqlaydi."},
    "t_don": {"name": "🎟 Don chiptasi", "cur": "dia", "price": 12, "tier": 5,
              "desc": "Keyingi o'yinda sizga Don roli tushadi (mafiya 2+ bo'lgan o'yinlarda)."},
    "herodef": {"name": "🔰 Geroydan himoya", "cur": "dia", "price": 3, "tier": 3,
                "desc": "🐺 Geroy hujumidan 1 marta to'liq saqlaydi (jon ham ketmaydi, 12-levelda ham o'ldirmaydi)."},
    "active": {"name": "🎭 Aktiv rol", "cur": "dia", "price": 8, "tier": 4,
               "desc": "O'yinga qo'shilganingizda siz tanlagan rol bilan boshlaysiz (o'yinda shunday rol bo'lsa, 1 marta)."},
    "kit": {"name": "🧿 Himoya to'plami", "cur": "dia", "price": 20, "tier": 5,
            "desc": "🛡 Himoya + ⚖️ Immunitet + ❤️ Zaxira hayot — bittadan, alohida olgandan arzonroq.",
            "grants": {"shield": 1, "immune": 1, "extralife": 1}},
}
CUR_SYM = {"money": "💵", "dia": "💎"}
CUR_COL = {"money": "money", "dia": "diamonds"}   # valyuta -> bazadagi ustun
CUR_NAME = {"money": "💵 Pulingiz", "dia": "💎 Olmosingiz"}

# Do'konda sotilmaydigan narsalar (price=0): Owner aura beradi, eski inventarlar ishlashda davom etadi.
ITEMS.update({
    "xray": {"name": "🔍 Rentgen", "cur": "dia", "price": 0, "tier": 3,
             "desc": "O'yin boshida tasodifiy bitta o'yinchining ANIQ rolini bilib olasiz (1 marta)."},
    "megaboost": {"name": "🚀 Mega Boost ×6", "cur": "dia", "price": 0, "tier": 4,
                  "desc": "Keyingi o'yindagi pul mukofoti 6 barobar bo'ladi (1 marta)."},
})

# ✨ EFFEKTLAR (aura): o'yinga qo'shilganda, g'alaba qilganda, o'lganda va oxirgi so'zda chatga chiroyli e'lon.
# vip=True bo'lsa — faqat ⭐ VIP bo'lib turgan paytda ishlaydi. {n} — ism (havola), {t} — oxirgi so'z.
FX = {
    "fx_owner": {
        "name": "👑 Owner aura", "cur": "dia", "price": 0, "tier": 5, "vip": False,
        "desc": "Faqat owner uchun. Har o'yinda bepul Himoya, Zaxira hayot, Immunitet, Ko'ruvchi, Rentgen, "
                "Qo'shimcha ovoz va pul mukofoti ×3.",
        "join": "👑 <b>Owner</b> {n} o'yinga qo'shildi.",
        "win": "👑 <b>Owner</b> {n} g'alaba qozondi.",
        "die": "👑 <b>Owner</b> {n} o'yindan chiqdi.",
        "last": "👑 <b>{n}</b> (Owner): «<i>{t}</i>»"},
    "fx_gold": {
        "name": "👑 Oltin aura", "cur": "dia", "price": 25, "tier": 5, "vip": False,
        "desc": "Afsonaviy effekt: kirganingizda, yutganingizda, o'lganingizda va oxirgi so'zingizda chatda oltin e'lon.",
        "join": "✨🌟✨ ━━━━━━━━━━━━ ✨🌟✨\n👑 <b>AFSONAVIY MEHMON</b> 👑\n\n{n} o'yinga qadam qo'ydi!\n"
                "<i>Zal jim bo'ldi... hamma unga qaradi.</i> 🌠\n✨🌟✨ ━━━━━━━━━━━━ ✨🌟✨",
        "win": "🏆👑 ━━━━━━━━━━━━ 👑🏆\n🎉 <b>OLTIN G'ALABA!</b> 🎉\n\n{n} — shahar afsonasi!\n"
               "<i>Oltin aura porlab, hammani lol qoldirdi.</i> ✨\n🏆👑 ━━━━━━━━━━━━ 👑🏆",
        "die": "🕊👑 ━━━━━━━━━━━━ 👑🕊\nOltin aura so'ndi...\n{n} — afsonalar ketadi, nomi qoladi. 🕯\n"
               "🕊👑 ━━━━━━━━━━━━ 👑🕊",
        "last": "👑🕯 <b>Afsonaning so'nggi so'zi</b>\n{n}:\n«<i>{t}</i>»\n<i>Zal sukutga cho'mdi...</i> 🕊"},
    "fx_fire": {
        "name": "🔥 Olov aura", "cur": "dia", "price": 12, "tier": 4, "vip": True,
        "desc": "VIP effekt: olovli e'lonlar (kirish, g'alaba, o'lim, oxirgi so'z).",
        "join": "🔥🔥 ━━━━━━━━━━━━ 🔥🔥\n🐉 <b>OLOV KIRDI!</b> 🐉\n\n{n} alanga ichidan chiqib, o'yinga qo'shildi!\n"
                "<i>Atrof qizib ketdi...</i> 🌋\n🔥🔥 ━━━━━━━━━━━━ 🔥🔥",
        "win": "🔥🏆 ━━━━━━━━━━━━ 🏆🔥\n🌋 <b>OLOV G'ALABASI!</b> 🌋\n\n{n} hamma narsani kuydirib, g'olib bo'ldi!\n"
               "🔥🏆 ━━━━━━━━━━━━ 🏆🔥",
        "die": "🔥💀 {n} alangasi so'ndi... faqat qora kul qoldi. 🌫",
        "last": "🔥🕯 <b>Olovning oxirgi uchquni</b>\n{n}:\n«<i>{t}</i>»\n<i>Olov so'ndi...</i> 🌫"},
    "fx_ice": {
        "name": "❄️ Muz aura", "cur": "dia", "price": 12, "tier": 4, "vip": True,
        "desc": "VIP effekt: muzdek e'lonlar (kirish, g'alaba, o'lim, oxirgi so'z).",
        "join": "❄️💎 ━━━━━━━━━━━━ 💎❄️\n🧊 <b>MUZ SHAHZODASI</b> 🧊\n\n{n} sovuq shabada bilan o'yinga qo'shildi!\n"
                "<i>Hamma qotib qoldi...</i> 🌨\n❄️💎 ━━━━━━━━━━━━ 💎❄️",
        "win": "❄️🏆 ━━━━━━━━━━━━ 🏆❄️\n🧊 <b>MUZDEK SOVUQQONLIK!</b> 🧊\n\n{n} sovuqqonlik bilan g'alabani oldi!\n"
               "❄️🏆 ━━━━━━━━━━━━ 🏆❄️",
        "die": "❄️💔 {n} muzdek sovib qoldi... qor yog'moqda. 🌨",
        "last": "❄️🕯 <b>Muzdagi so'nggi nafas</b>\n{n}:\n«<i>{t}</i>»\n<i>Qor hamma narsani yopdi...</i> 🌨"},
    "fx_neon": {
        "name": "⚡️ Neon aura", "cur": "dia", "price": 15, "tier": 4, "vip": True,
        "desc": "VIP effekt: neon yog'dusi (kirish, g'alaba, o'lim, oxirgi so'z).",
        "join": "⚡️🌈 ━━━━━━━━━━━━ 🌈⚡️\n🎆 <b>NEON SHOU BOSHLANDI!</b> 🎆\n\n{n} chiroqlar yog'dusi ostida kirib keldi!\n"
                "<i>Raqs maydoni uniki!</i> 💃\n⚡️🌈 ━━━━━━━━━━━━ 🌈⚡️",
        "win": "⚡️🏆 ━━━━━━━━━━━━ 🏆⚡️\n🎇 <b>NEON G'ALABA!</b> 🎇\n\n{n} butun shaharni yoritib yubordi!\n"
               "⚡️🏆 ━━━━━━━━━━━━ 🏆⚡️",
        "die": "⚡️🌑 {n} chiroqlari o'chdi... zulmat cho'kdi. 🌑",
        "last": "⚡️🕯 <b>Neonning oxirgi yaltirashi</b>\n{n}:\n«<i>{t}</i>»\n<i>Chiroqlar o'chdi...</i> 🌑"},
}


def fx_price(key: str) -> int:
    v = kv_get("price_" + key)
    return int(v) if v is not None and v.lstrip("-").isdigit() else FX[key]["price"]


def fx_has(uid: int, k: str) -> bool:
    return inv_qty(uid, k) > 0 or (k == "fx_owner" and uid in OWNER_IDS)


def fx_owned(uid: int) -> list:
    return [k for k in FX if fx_has(uid, k)]


def fx_active(uid: int):
    """Hozir ishlayotgan effekt kaliti (yo'q bo'lsa None). VIP effektlar faqat VIP bo'lganda ishlaydi."""
    k = kv_get(f"fx_{uid}")
    if k is None and uid in OWNER_IDS:
        k = "fx_owner"          # owner'da avtomatik yoqilgan
    if not k or k not in FX or not fx_has(uid, k):
        return None
    if FX[k]["vip"] and not is_vip(uid):
        return None
    return k


def fx_text(uid: int, ev: str, name_html: str, text: str = ""):
    k = fx_active(uid)
    if not k:
        return None
    return FX[k][ev].format(n=name_html, t=text)


async def fx_announce(g: Game, uid: int, ev: str, name: str, text: str = ""):
    link = f'<a href="tg://user?id={uid}">{esc(name)}</a>'
    out = fx_text(uid, ev, link, text)
    if out:
        await send(g.chat_id, out)




# chipta -> qaysi rollar uchun
TICKETS = {"t_kom": ("kom",), "t_doc": ("doc",), "t_don": ("don",),
           "t_mafia": ("mafia", "don", "adv", "spy", "pois", "hypno", "thief", "killer", "swindler")}
DEFAULT_PACKS = [(10, 5), (25, 15), (50, 35), (100, 80), (250, 220)]  # (Stars, olmos)


def item_price(key: str) -> int:
    v = kv_get("price_" + key)
    return int(v) if v is not None and v.lstrip("-").isdigit() else ITEMS[key]["price"]


def get_packs() -> list:
    try:
        raw = json.loads(kv_get("packs", "") or "[]")
        packs = [(int(a), int(b)) for a, b in raw]
        return packs or list(DEFAULT_PACKS)
    except Exception:
        return list(DEFAULT_PACKS)


def extend_vip(uid: int, days: int) -> bool:
    cur = VIPS.get(uid)
    if cur == 0:
        return False  # umrbod VIP
    until = max(int(time.time()), cur or 0) + days * 86400
    ensure_user(uid)
    db.execute("UPDATE users SET vip=1, vip_until=? WHERE user_id=?", (until, uid))
    db.commit()
    VIPS[uid] = until
    return True


def claim_daily(uid: int):
    ensure_user(uid)
    last = db.execute("SELECT last_daily FROM users WHERE user_id=?", (uid,)).fetchone()[0] or 0
    now = int(time.time())
    if now - last < 86400:
        left = 86400 - (now - last)
        return False, f"⏳ Keyingi bonusga {left // 3600} soat {left % 3600 // 60} daqiqa qoldi."
    amt = DAILY_BONUS * (2 if is_vip(uid) else 1) + tinfo(uid).get("daily", 0)
    db.execute("UPDATE users SET last_daily=?, money=COALESCE(money,0)+? WHERE user_id=?", (now, amt, uid))
    db.commit()
    return True, f"🎁 Kunlik bonus: <b>+{amt}</b>💵" + (" (⭐ VIP ×2)" if is_vip(uid) else "")


# ── qayta tug'ilish ──
async def notify_dead(g: Game, p: Player, text: str):
    kb = None
    if not p.reborn:
        b = InlineKeyboardBuilder()
        b.button(text=f"♻️ Qayta tug'ilish — {REBIRTH_COST}💎", callback_data=f"rb:{g.chat_id}")
        kb = b.as_markup()
        text += (f"\n\n♻️ {REBIRTH_COST}💎 evaziga qayta tug'ilishingiz mumkin "
                 "(o'yinda faqat 1 marta, kunduzgi muhokama vaqtida).")
    await send(p.id, text, reply_markup=kb)
    await ask_last_words(g, p)


@router.callback_query(F.data.startswith("rb:"))
async def rebirth_cb(cq: CallbackQuery):
    try:
        g = GAMES.get(int(cq.data.split(":")[1]))
    except ValueError:
        return await cq.answer()
    p = g.players.get(cq.from_user.id) if g else None
    if not g or not p or g.state == "end":
        return await cq.answer("O'yin tugagan.", show_alert=True)
    if p.alive:
        return await cq.answer("Siz hozir tirik.", show_alert=True)
    if p.reborn:
        return await cq.answer("Bu o'yinda qayta tug'ilish allaqachon ishlatilgan (faqat 1 marta).", show_alert=True)
    if g.state != "day":
        return await cq.answer("⏳ Qayta tug'ilish faqat kunduzi (muhokama vaqtida) mumkin. "
                               "Tong otishini kuting.", show_alert=True)
    if not spend(p.id, "diamonds", REBIRTH_COST):
        return await cq.answer(f"💎 Olmosingiz yetarli emas (kerak: {REBIRTH_COST}). "
                               "Botda Do'kon → Olmos sotib olish.", show_alert=True)
    p.alive = True
    p.reborn = True
    LASTWORDS.pop(p.id, None)
    if cq.message:
        await safe_edit(cq.message, "♻️ Siz qayta tug'ildingiz! O'yinga qaytdingiz.")
    await send(g.chat_id, f"♻️ {mention(p)} qayta tug'ildi va o'yinga qaytdi!")
    await cq.answer("♻️ Qayta tug'ildingiz!")


# ── chatlar va tasodifiy chat ──
async def refresh_chat_info(chat_id: int):
    try:
        c = await bot.get_chat(chat_id)
        n = await bot.get_chat_member_count(chat_id)
        me = await bot.get_chat_member(chat_id, bot.id)
        adm = 1 if me.status in ("administrator", "creator") else 0
        db.execute("UPDATE chats SET title=?, username=?, members=?, bot_admin=? WHERE chat_id=?",
                   (c.title or "", c.username or "", n, adm, chat_id))
        db.commit()
    except TelegramAPIError:
        db.execute("UPDATE chats SET bot_admin=0 WHERE chat_id=?", (chat_id,))
        db.commit()


def record_chat_game(chat_id: int):
    db.execute("UPDATE chats SET games=games+1 WHERE chat_id=?", (chat_id,))
    db.commit()
    spawn(refresh_chat_info(chat_id))


@router.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
async def bot_status_changed(ev: ChatMemberUpdated):
    touch_chat(ev.chat)
    await refresh_chat_info(ev.chat.id)


LAST_RCHAT: dict = {}


async def random_chat_msg(msg: Message, uid: int):
    rows = db.execute(
        "SELECT chat_id,title,username,members,games FROM chats "
        "WHERE username!='' AND bot_admin=1 AND hidden=0 ORDER BY (games*5+members) DESC LIMIT 10"
    ).fetchall()
    random.shuffle(rows)
    rows.sort(key=lambda r: r[0] == LAST_RCHAT.get(uid))  # oxirgi ko'rsatilganini oxiriga
    for cid, title, uname, members, games in rows:
        try:
            me = await bot.get_chat_member(cid, bot.id)
            if me.status not in ("administrator", "creator"):
                db.execute("UPDATE chats SET bot_admin=0 WHERE chat_id=?", (cid,))
                db.commit()
                continue
        except TelegramAPIError:
            db.execute("UPDATE chats SET bot_admin=0 WHERE chat_id=?", (cid,))
            db.commit()
            continue
        LAST_RCHAT[uid] = cid
        kb = InlineKeyboardBuilder()
        kb.button(text="➡️ Chatga o'tish", url=f"https://t.me/{uname}")
        kb.button(text="🎲 Boshqasi", callback_data="m:rchat")
        kb.adjust(1)
        await msg.answer(f"🎲 <b>Tasodifiy chat</b>\n\n💬 {esc(title)}\n👥 A'zolar: {members}\n"
                         f"🎮 O'yinlar: {games}", reply_markup=kb.as_markup())
        return
    await msg.answer("😕 Hozircha mos chat topilmadi. (Faqat bot admin bo'lgan ochiq guruhlar chiqadi.)")


# ── majburiy obuna ──
SUB_TEXT = ("🔒 <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>\n\n"
            "A'zo bo'lgach, «✅ Tekshirish» tugmasini bosing.")
SUB_CACHE: dict = {}
PENDING_JOIN: dict = {}


def sub_channels() -> list:
    try:
        return json.loads(kv_get("sub_channels", "") or "[]")
    except Exception:
        return []


async def missing_channels(uid: int) -> list:
    chans = sub_channels()
    if not chans or SUB_CACHE.get(uid, 0) > time.time():
        return []
    miss = []
    for ch in chans:
        try:
            m = await bot.get_chat_member(ch["id"], uid)
            ok = m.status in ("member", "administrator", "creator") or \
                (m.status == "restricted" and getattr(m, "is_member", False))
            if not ok:
                miss.append(ch)
        except TelegramAPIError as e:
            log.warning("Obuna tekshiruvi xato (%s): %s", ch.get("id"), e)  # xatoda foydalanuvchini bloklamaymiz
    if not miss:
        SUB_CACHE[uid] = time.time() + 300
    return miss


def sub_kb(miss: list):
    kb = InlineKeyboardBuilder()
    for ch in miss:
        kb.button(text=f"📢 {ch['title'][:30]}", url=ch["url"])
    kb.button(text="✅ Tekshirish", callback_data="sub:check")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "sub:check")
async def sub_check(cq: CallbackQuery):
    uid = cq.from_user.id
    SUB_CACHE.pop(uid, None)
    miss = await missing_channels(uid)
    if miss:
        return await cq.answer("❌ Hali hamma kanalga a'zo bo'lmadingiz.", show_alert=True)
    await cq.answer("✅ Rahmat!")
    if cq.message:
        await safe_edit(cq.message, "✅ Obuna tasdiqlandi!")
        pend = PENDING_JOIN.pop(uid, None)
        if pend:
            await join_game(cq.from_user, pend, cq.message)
        else:
            await cq.message.answer("🤵🏻 <b>Asosiy menyu</b>", reply_markup=private_menu(uid))


# ── do'kon va hamyon ──
def wallet_text(uid: int) -> str:
    m, d = get_bal(uid)
    return (f"👛 <b>Hamyon</b>\n\n💵 Pul: <b>{m}</b>\n💎 Olmos: <b>{d}</b>\n\n"
            f"💱 1💎 = {DIAMOND_RATE}💵\n♻️ Qayta tug'ilish: {REBIRTH_COST}💎 (o'yinda 1 marta)\n"
            f"🎮 O'yin: +{REWARD_PLAY}💵 · 🏆 G'alaba: +{REWARD_WIN}💵")


def wallet_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Olmos sotib olish (⭐ Stars)", callback_data="s:dia")
    kb.button(text="💱 Olmos → Pul", callback_data="s:conv")
    kb.button(text="🎁 Kunlik bonus", callback_data="s:daily")
    kb.button(text="🎒 Narsalarim", callback_data="s:inv")
    kb.button(text="🛒 Do'kon", callback_data="s:home")
    kb.button(text="⬅️ Orqaga", callback_data="s:menu")
    kb.adjust(1)
    return kb.as_markup()


def shop_view(uid: int, cat: str = ""):
    m, d = get_bal(uid)
    head = f"🛒 <b>Do'kon</b>\n\n💵 Pul: <b>{m}</b>   💎 Olmos: <b>{d}</b>\n"
    kb = InlineKeyboardBuilder()
    if cat not in ("money", "dia", "vip"):
        lines = [head,
                 "💵 <b>Pul do'koni</b> — oddiy va yaxshi narsalar.",
                 "💎 <b>Olmos do'koni</b> — kuchli narsalar, 🎭 Aktiv rol, 🔰 Geroydan himoya, zaxira hayot, 👑 Oltin aura.",
                 "🌟 <b>VIP do'kon</b> — faqat ⭐ VIP egalari uchun: maxsus ✨ auralar.\n",
                 f"⭐ <b>VIP (30 kun)</b> — <b>{VIP_DIAMONDS}</b>💎\n<i>30 kun davomida barcha o'tkazmalardan komissiya olinmaydi, kunlik bonus ×2, ⭐ belgisi, 🌟 VIP do'kon.</i>\n",
                 "Narx kuchga qarab belgilangan: kuchliroq narsa — qimmatroq.\n"
                 "Sotib olingan narsalar o'yinda <b>avtomatik</b> ishlaydi. Xohlamasangiz, "
                 "🎒 Narsalarim bo'limidan o'chirib qo'yishingiz mumkin."]
        kb.button(text="💵 Pul do'koni", callback_data="s:cat:money")
        kb.button(text="💎 Olmos do'koni", callback_data="s:cat:dia")
        kb.button(text="🌟 VIP do'kon" + ("" if is_vip(uid) else " 🔒"), callback_data="s:cat:vip")
        kb.button(text="🐺 Geroy (uy hayvoni)", callback_data="s:hero")
        kb.button(text="🏅 Unvonlar (⭐ Stars)", callback_data="s:tt")
        kb.button(text=f"⭐ VIP 30 kun — {VIP_DIAMONDS}💎", callback_data="s:vip")
        kb.button(text="🎒 Narsalarim", callback_data="s:inv")
        kb.button(text="👛 Hamyon", callback_data="s:wallet")
        kb.button(text="⬅️ Orqaga", callback_data="s:menu")
        kb.adjust(2, 1, 2, 1, 2, 1)
        return "\n".join(lines), kb.as_markup()
    titles = {"money": "💵 <b>Pul do'koni</b>", "dia": "💎 <b>Olmos do'koni</b>",
              "vip": "🌟 <b>VIP do'kon</b>\n<i>Faqat ⭐ VIP egalari uchun. Auralar faqat VIP muddati davomida ishlaydi.</i>"}
    lines = [head, titles[cat] + "\n"]
    if cat == "vip" and not is_vip(uid):
        lines.append("🔒 Bu do'kon faqat <b>⭐ VIP</b> egalari uchun.\nVIP olish: asosiy do'kon → ⭐ VIP 30 kun.")
        kb.button(text=f"⭐ VIP 30 kun — {VIP_DIAMONDS}💎", callback_data="s:vip")
        kb.button(text="⬅️ Do'konga", callback_data="s:home")
        kb.adjust(1)
        return "\n".join(lines), kb.as_markup()
    if cat == "vip":
        items = [(k, v) for k, v in ITEMS.items() if v.get("vip") and item_price(k) > 0]
    else:
        items = [(k, v) for k, v in ITEMS.items()
                 if v["cur"] == cat and not v.get("vip") and item_price(k) > 0 and not k.startswith("t_")]
    items.sort(key=lambda kv: (kv[1]["tier"], item_price(kv[0])))
    for key, v in items:
        pr = item_price(key)
        sym = CUR_SYM[v["cur"]]
        lines.append(f"{TIERS[v['tier']]} · {v['name']} — <b>{pr}</b>{sym}\n<i>{v['desc']}</i>\n")
        kb.button(text=f"{v['name']} — {pr}{sym}", callback_data=f"s:buy:{key}")
    fxs = [(k, v) for k, v in FX.items() if (v["vip"] if cat == "vip" else (not v["vip"] and v["cur"] == cat)) and fx_price(k) > 0]
    if fxs:
        lines.append("✨ <b>Effektlar</b> (chatga chiroyli e'lon):\n")
    for key, v in fxs:
        pr = fx_price(key)
        sym = CUR_SYM[v["cur"]]
        own = " ✅" if inv_qty(uid, key) > 0 else ""
        lines.append(f"{TIERS[v['tier']]} · {v['name']} — <b>{pr}</b>{sym}{own}\n<i>{v['desc']}</i>\n")
        kb.button(text=f"✨ {v['name']} — {pr}{sym}", callback_data=f"s:fxb:{key}")
    if not items and not fxs:
        lines.append("Hozircha sotuvda narsa yo'q.")
    kb.button(text="⬅️ Do'konga", callback_data="s:home")
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


def fx_view(uid: int):
    own = fx_owned(uid)
    cur = fx_active(uid)
    kb = InlineKeyboardBuilder()
    lines = ["✨ <b>Effektlarim</b>\n",
             "Effekt o'yinga qo'shilganingizda, g'alaba qilganingizda, o'lganingizda va oxirgi so'zingizda "
             "guruhga chiroyli e'lon chiqaradi. Bir vaqtda bittasi yoqiladi.\n"]
    if not own:
        lines.append("Hozircha effektingiz yo'q. 💎 Olmos do'koni yoki 🌟 VIP do'konidan oling.")
    for k in own:
        v = FX[k]
        on = (k == cur)
        warn = " (⭐ VIP kerak)" if v["vip"] and not is_vip(uid) else ""
        lines.append(f"{'✅' if on else '▫️'} {v['name']}{warn}")
        kb.button(text=("⛔ O'chirish: " if on else "✅ Yoqish: ") + v["name"], callback_data=f"s:fxe:{k}")
        kb.button(text="👁 Ko'rish", callback_data=f"s:fxp:{k}")
    kb.button(text="💎 Olmos do'koni", callback_data="s:cat:dia")
    kb.button(text="⬅️ Orqaga", callback_data="s:inv")
    kb.adjust(*([2] * len(own) + [1, 1]))
    return "\n".join(lines), kb.as_markup()


async def show_shop(msg: Message, uid: int, edit: bool = False, cat: str = ""):
    text, kb = shop_view(uid, cat)
    if edit:
        await safe_edit(msg, text, reply_markup=kb)
    else:
        await msg.answer(text, reply_markup=kb)


def active_pick_view(uid: int):
    cur = kv_get(f"ar_{uid}")
    kb = InlineKeyboardBuilder()
    for r in ACTIVE_ROLES:
        kb.button(text=("✅ " if r == cur else "") + rname(r), callback_data=f"s:ar:{r}")
    kb.button(text="⬅️ Orqaga", callback_data="s:inv")
    kb.adjust(2)
    text = ("🎭 <b>Aktiv rol</b>\n\nQaysi rol bilan o'yinni boshlamoqchisiz?\n"
            "<i>Keyingi o'yinda shunday rol bo'lsa, shu rol sizga beriladi (1 marta).</i>")
    if cur in ACTIVE_ROLES:
        text += f"\n\nHozirgi tanlov: <b>{rname(cur)}</b>"
    return text, kb.as_markup()


def back_to(cb: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Orqaga", callback_data=cb)
    return kb.as_markup()


def inv_view(uid: int):
    kb = InlineKeyboardBuilder()
    have = [k for k, v in ITEMS.items() if "grants" not in v and inv_qty(uid, k) > 0]
    for k in have:
        on = not inv_is_off(uid, k)
        kb.button(text=f"{'✅' if on else '⛔'} {ITEMS[k]['name']} ×{inv_qty(uid, k)}", callback_data=f"s:tg:{k}")
    rows = [1] * len(have)
    if inv_qty(uid, "active") > 0:
        kb.button(text="🎭 Aktiv rolni tanlash", callback_data="s:ar:pick")
        rows.append(1)
    kb.button(text="✨ Effektlarim", callback_data="s:fx")
    rows.append(1)
    kb.button(text="🛒 Do'kon", callback_data="s:home")
    kb.button(text="⬅️ Orqaga", callback_data="s:wallet")
    rows.append(2)
    kb.adjust(*rows)
    text = ("🎒 <b>Narsalarim</b>\n\n" +
            ("Narsani bosib yoqing/o'chiring:\n✅ — keyingi o'yinda ishlatiladi\n⛔ — saqlanadi, ishlatilmaydi"
             if have else "Hozircha narsa yo'q. 🛒 Do'kondan oling."))
    ar = kv_get(f"ar_{uid}")
    if ar in ACTIVE_ROLES and inv_qty(uid, "active") > 0:
        text += f"\n\n🎭 Aktiv rol: <b>{rname(ar)}</b>"
    return text, kb.as_markup()


def hero_view(uid: int):
    lvl = hero_level(uid)
    table = ", ".join(f"{l}-lvl: {hero_pct(l)}%" for l in range(1, HERO_MAX)) + f", {HERO_MAX}-lvl: ☠️ darrov o'ldiradi"
    kb = InlineKeyboardBuilder()
    base = ("🐺 <b>Geroy</b> — uy hayvoni\n\nBir marta olasiz va u <b>hech qachon yo'qolmaydi</b>. "
            "Bu rol emas: sizning o'z rolingiz bilan birga ishlaydi.\n"
            "• Tunda rolingizdan tashqari Geroyga ham buyruq berasiz: u tanlangan o'yinchiga hujum qiladi.\n"
            "• O'yinchiga xabar boradi: «Geroy sizga hujum qildi, joningizning X% i ketdi».\n"
            "• Zarar levelga bog'liq; 12-levelda hujum darrov o'ldiradi.\n"
            f"• Hujumdan keyin <b>{HERO_REST} tun</b> dam oladi, so'ng yana hujum qiladi "
            "(o'yin uzoq bo'lsa, bir necha marta).\n• Hamma 100❤️ bilan boshlaydi, har tunda +10❤️ tiklanadi.\n"
            "• 👑 Imperator unvoniga va 🔰 Geroydan himoya narsasiga Geroy hujumi ta'sir qilmaydi.\n\n"
            f"🗡 Zarar: {table}\n")
    if not lvl:
        text = base + f"\n💰 Narxi: <b>{HERO_BUY}💎</b> (bir marta)"
        kb.button(text=f"🐺 Sotib olish — {HERO_BUY}💎", callback_data="s:hbuy")
    else:
        pc = hero_pct(lvl)
        text = base + (f"\n✅ Sizda bor. Level: <b>{lvl}/{HERO_MAX}</b> — hujum: "
                       + ("<b>darrov o'ldiradi</b>" if pc is None else f"<b>{pc}%</b>"))
        nxt = HERO_UP.get(lvl + 1)
        if nxt:
            cur, price = nxt
            kb.button(text=f"⬆️ {lvl + 1}-levelga — {price}{CUR_SYM[cur]}", callback_data="s:hup")
        else:
            text += "\n🔥 Maksimal level!"
        kb.button(text=("✅ O'yinda Geroyni ishlatish: YOQIQ" if hero_on(uid) else "⛔ O'yinda Geroyni ishlatish: O'CHIQ"),
                  callback_data="s:htg")
    m, d2 = get_bal(uid)
    text += f"\n\n💵 {m}   💎 {d2}"
    kb.button(text="⬅️ Do'konga", callback_data="s:home")
    kb.adjust(1)
    return text, kb.as_markup()


def titles_view(uid: int):
    own = TOWNED.get(uid, set())
    lines = ["🏅 <b>Unvonlar</b> (Telegram Stars ⭐ bilan)\n",
             "Unvon doimiy. Eng yuqorisi amal qiladi. Do'stingizga sovg'a qilish ham mumkin 🎁\n"]
    kb = InlineKeyboardBuilder()
    for k, v in TITLES.items():
        lines.append(f"{v['name']} — <b>{tprice(k)}⭐</b>{' ✅' if k in own else ''}\n<i>{v['desc']}</i>\n")
        kb.button(text=f"{v['name']} — {tprice(k)}⭐", callback_data=f"s:ttv:{k}")
    kb.button(text="⬅️ Do'konga", callback_data="s:home")
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


def title_detail(uid: int, key: str):
    v = TITLES[key]
    owned = key in TOWNED.get(uid, ())
    text = (f"{v['name']}\n\n{v['desc']}\n\n💫 Narxi: <b>{tprice(key)}⭐</b>"
            + ("\n✅ Bu unvon sizda bor." if owned else ""))
    kb = InlineKeyboardBuilder()
    if not owned:
        kb.button(text=f"⭐ Sotib olish — {tprice(key)}⭐", callback_data=f"s:ttbuy:{key}")
    kb.button(text="🎁 Do'stga sovg'a qilish", callback_data=f"s:ttgift:{key}")
    kb.button(text="⬅️ Unvonlar", callback_data="s:tt")
    kb.adjust(1)
    return text, kb.as_markup()


async def send_title_invoice(buyer: int, target: int, key: str):
    v = TITLES[key]
    stars = tprice(key)
    gift = target != buyer
    await bot.send_invoice(
        chat_id=buyer, title=f"{v['name']} unvoni" + (" (sovg'a)" if gift else ""),
        description=v["desc"][:250], payload=f"ttl|{buyer}|{target}|{key}|{stars}", currency="XTR",
        prices=[LabeledPrice(label=v["name"], amount=stars)])


class TTLState(dict):
    """Kutilayotgan kiritish holati: 10 daqiqadan keyin o'zi o'chadi (aks holda keyingi xabarlarni 'yutib' yuboradi)."""
    TTL = 600

    def __init__(self):
        super().__init__()
        self._t = {}

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._t[k] = time.time()

    def _alive(self, k):
        if dict.__contains__(self, k) and time.time() - self._t.get(k, 0) > self.TTL:
            self.pop(k, None)
        return dict.__contains__(self, k)

    def __contains__(self, k):
        return self._alive(k)

    def get(self, k, default=None):
        return dict.get(self, k, default) if self._alive(k) else default

    def pop(self, k, *d):
        self._t.pop(k, None)
        return dict.pop(self, k, *d)


GIFT_STATE = TTLState()   # user_id -> {"key": unvon}


@router.callback_query(F.data.startswith("s:"))
async def shop_cb(cq: CallbackQuery):
    if not cq.data.startswith("s:ttgift"):
        GIFT_STATE.pop(cq.from_user.id, None)
    uid = cq.from_user.id
    msg = cq.message
    if msg is None or msg.chat.type != "private":
        return await cq.answer("🛒 Do'kon faqat shaxsiy chatda — botga yozing.", show_alert=True)
    parts = cq.data.split(":")
    act = parts[1]

    if act == "menu":
        await safe_edit(msg, "🤵🏻 <b>Asosiy menyu</b>", reply_markup=private_menu(uid))
    elif act == "home":
        await show_shop(msg, uid, edit=True)
    elif act == "cat":
        await show_shop(msg, uid, edit=True, cat=parts[2])
    elif act == "wallet":
        await safe_edit(msg, wallet_text(uid), reply_markup=wallet_kb())
    elif act == "buy":
        key = parts[2]
        if key not in ITEMS or item_price(key) <= 0:
            return await cq.answer("Bu narsa hozir sotilmaydi.", show_alert=True)
        it = ITEMS[key]
        if it.get("vip") and not is_vip(uid):
            return await cq.answer("🌟 Bu do'kon faqat ⭐ VIP egalari uchun.", show_alert=True)
        col = CUR_COL[it["cur"]]
        if not spend(uid, col, item_price(key)):
            if it["cur"] == "money":
                return await cq.answer("💵 Pulingiz yetarli emas. O'yin o'ynang yoki 🎁 kunlik bonus oling.",
                                       show_alert=True)
            return await cq.answer("💎 Olmosingiz yetarli emas. Hamyon → Olmos sotib olish.", show_alert=True)
        for gk, gq in (it.get("grants") or {key: 1}).items():
            inv_add(uid, gk, gq)
        if key == "active":
            text, kb = active_pick_view(uid)
            await safe_edit(msg, text, reply_markup=kb)
            return await cq.answer("✅ Sotib olindi — endi rolni tanlang")
        await show_shop(msg, uid, edit=True, cat="vip" if it.get("vip") else it["cur"])
        return await cq.answer(f"✅ Sotib olindi: {it['name']}")
    elif act == "fxb":
        key = parts[2]
        fx = FX.get(key)
        if not fx or fx_price(key) <= 0:
            return await cq.answer("Bu effekt hozir sotilmaydi.", show_alert=True)
        if fx["vip"] and not is_vip(uid):
            return await cq.answer("🌟 Bu effekt faqat ⭐ VIP egalari uchun.", show_alert=True)
        if inv_qty(uid, key) > 0:
            return await cq.answer("Bu effekt sizda allaqachon bor ✅", show_alert=True)
        if not spend(uid, CUR_COL[fx["cur"]], fx_price(key)):
            return await cq.answer(f"{CUR_SYM[fx['cur']]} yetarli emas (kerak: {fx_price(key)}).", show_alert=True)
        inv_add(uid, key, 1)
        kv_set(f"fx_{uid}", key)    # avtomatik yoqiladi
        text, kb = fx_view(uid)
        await safe_edit(msg, f"🎉 <b>{fx['name']}</b> sizniki! U yoqildi.\n\n" + text, reply_markup=kb)
        return await cq.answer("✨ Effekt yoqildi!", show_alert=True)
    elif act == "fx":
        text, kb = fx_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "fxe":
        key = parts[2]
        if key in FX and fx_has(uid, key):
            if fx_active(uid) == key:
                kv_set(f"fx_{uid}", "")
            else:
                kv_set(f"fx_{uid}", key)
        text, kb = fx_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "fxp":
        key = parts[2]
        if key in FX and fx_has(uid, key):
            link = f'<a href="tg://user?id={uid}">{esc(cq.from_user.full_name)}</a>'
            await msg.answer("👁 <b>Ko'rib chiqish:</b>\n\n" + FX[key]["join"].format(n=link, t="")
                             + "\n\n" + FX[key]["win"].format(n=link, t="")
                             + "\n\n" + FX[key]["last"].format(n=link, t="Hammaga rahmat, yaxshi o'yin edi!"))
    elif act == "vip":
        if VIPS.get(uid) == 0:
            return await cq.answer("Sizda umrbod VIP bor 😎", show_alert=True)
        if not spend(uid, "diamonds", VIP_DIAMONDS):
            return await cq.answer("💎 Olmosingiz yetarli emas.", show_alert=True)
        extend_vip(uid, 30)
        await show_shop(msg, uid, edit=True)
        return await cq.answer("⭐ VIP 30 kunga faollashtirildi!", show_alert=True)
    elif act == "hero":
        text, kb = hero_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "hbuy":
        if hero_level(uid) > 0:
            return await cq.answer("Geroy sizda allaqachon bor!", show_alert=True)
        if not spend(uid, "diamonds", HERO_BUY):
            return await cq.answer(f"💎 Olmosingiz yetarli emas (kerak: {HERO_BUY}).", show_alert=True)
        db.execute("INSERT OR IGNORE INTO hero(user_id,level) VALUES(?,1)", (uid,))
        db.commit()
        text, kb = hero_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
        return await cq.answer("🐺 Geroy sizniki! U endi hech qachon yo'qolmaydi.", show_alert=True)
    elif act == "hup":
        lvl = hero_level(uid)
        nxt = HERO_UP.get(lvl + 1)
        if not lvl or not nxt:
            return await cq.answer("Level oshirib bo'lmaydi.", show_alert=True)
        cur, price = nxt
        if not spend(uid, "money" if cur == "money" else "diamonds", price):
            return await cq.answer(f"{CUR_SYM[cur]} yetarli emas (kerak: {price}).", show_alert=True)
        db.execute("UPDATE hero SET level=level+1 WHERE user_id=?", (uid,))
        db.commit()
        text, kb = hero_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
        return await cq.answer(f"⬆️ Geroy {lvl + 1}-levelga ko'tarildi!")
    elif act == "htg":
        if hero_level(uid):
            db.execute("UPDATE hero SET off=1-COALESCE(off,0) WHERE user_id=?", (uid,))
            db.commit()
        text, kb = hero_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "tt":
        GIFT_STATE.pop(uid, None)
        text, kb = titles_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "ttv":
        if parts[2] not in TITLES:
            return await cq.answer()
        text, kb = title_detail(uid, parts[2])
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "ttbuy":
        key = parts[2]
        if key not in TITLES:
            return await cq.answer()
        if key in TOWNED.get(uid, ()):
            return await cq.answer("Bu unvon sizda allaqachon bor.", show_alert=True)
        try:
            await send_title_invoice(uid, uid, key)
        except TelegramAPIError as e:
            log.warning("unvon invoice xato: %s", e)
            return await cq.answer("❌ To'lov oynasini ochib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)
    elif act == "ttgift":
        key = parts[2]
        if key not in TITLES:
            return await cq.answer()
        GIFT_STATE[uid] = {"key": key}
        await safe_edit(msg, f"🎁 <b>{TITLES[key]['name']}</b> unvonini kimga sovg'a qilasiz?\n\n"
                             "Do'stingizning <b>ID</b> raqamini yoki <b>@username</b> ini yuboring, yoki undan xabar forward "
                             "qiling. (U botga kamida bir marta /start bosgan bo'lishi kerak.)\nBekor qilish: /cancel",
                        reply_markup=back_to("s:tt"))
    elif act == "dia":
        kb = InlineKeyboardBuilder()
        for i, (stars, dia) in enumerate(get_packs()):
            kb.button(text=f"⭐ {stars} → 💎 {dia}", callback_data=f"s:pay:{i}")
        kb.button(text="⬅️ Orqaga", callback_data="s:wallet")
        kb.adjust(1)
        await safe_edit(msg, "💎 <b>Olmos sotib olish</b>\n\nTelegram Stars (⭐) orqali to'lanadi. Paketni tanlang:",
                        reply_markup=kb.as_markup())
    elif act == "pay":
        packs = get_packs()
        try:
            stars, dia = packs[int(parts[2])]
        except (ValueError, IndexError):
            return await cq.answer("Paket topilmadi.", show_alert=True)
        try:
            await bot.send_invoice(
                chat_id=uid, title=f"💎 {dia} olmos",
                description=f"{dia} ta olmos hamyoningizga qo'shiladi.",
                payload=f"dia|{uid}|{stars}|{dia}", currency="XTR",
                prices=[LabeledPrice(label=f"{dia} olmos", amount=stars)],
            )
        except TelegramAPIError as e:
            log.warning("invoice xato: %s", e)
            return await cq.answer("❌ To'lov oynasini ochib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)
    elif act == "conv":
        m, d = get_bal(uid)
        kb = InlineKeyboardBuilder()
        for n in (1, 5, 10):
            kb.button(text=f"{n}💎 → {n * DIAMOND_RATE}💵", callback_data=f"s:cv:{n}")
        kb.button(text=f"Hammasi ({d}💎)", callback_data="s:cv:all")
        kb.button(text="⬅️ Orqaga", callback_data="s:wallet")
        kb.adjust(2, 2, 1)
        await safe_edit(msg, f"💱 <b>Olmos → Pul</b>\n\n💎 Olmosingiz: <b>{d}</b>\nKurs: 1💎 = {DIAMOND_RATE}💵",
                        reply_markup=kb.as_markup())
    elif act == "cv":
        m, d = get_bal(uid)
        n = d if parts[2] == "all" else int(parts[2])
        if n <= 0 or not spend(uid, "diamonds", n):
            return await cq.answer("💎 Olmosingiz yetarli emas.", show_alert=True)
        add_money(uid, n * DIAMOND_RATE)
        await safe_edit(msg, wallet_text(uid), reply_markup=wallet_kb())
        return await cq.answer(f"✅ {n}💎 → {n * DIAMOND_RATE}💵")
    elif act == "daily":
        ok, text = claim_daily(uid)
        if not ok:
            return await cq.answer(text.replace("⏳ ", "⏳ "), show_alert=True)
        await safe_edit(msg, wallet_text(uid) + "\n\n" + text, reply_markup=wallet_kb())
    elif act == "ar":
        if inv_qty(uid, "active") <= 0:
            return await cq.answer("Avval 🎭 Aktiv rolni do'kondan oling.", show_alert=True)
        if len(parts) > 2 and parts[2] in ACTIVE_ROLES:
            kv_set(f"ar_{uid}", parts[2])
            text, kb = inv_view(uid)
            await safe_edit(msg, f"✅ Aktiv rol tanlandi: <b>{rname(parts[2])}</b>\n\n" + text, reply_markup=kb)
            return await cq.answer("✅ Tanlandi")
        text, kb = active_pick_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "inv":
        text, kb = inv_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    elif act == "tg":
        key = parts[2]
        if key in ITEMS and inv_qty(uid, key) > 0:
            inv_toggle(uid, key)
        text, kb = inv_view(uid)
        await safe_edit(msg, text, reply_markup=kb)
    await cq.answer()


# ───────────────────────── CHATDA: PUL O'TKAZISH va SOVGA ─────────────────────────
TRANSFER_FEE_PCT = int(os.getenv("TRANSFER_FEE_PCT", "5"))   # o'tkazma komissiyasi (%). ⭐ VIP uchun yo'q
DROP_TTL = int(os.getenv("DROP_TTL", "600"))                  # sovga necha soniyada qaytariladi

PAY_HELP = ("💸 <b>Pul o'tkazish</b>\nGuruhda o'yinchining xabariga <b>javob (reply)</b> qilib yozing:\n"
            "<code>/pay 500</code> — 500💵\n<code>/pay 2 olmos</code> — 2💎\n"
            "<code>/pay hammasi</code> — hamma pulingiz\n\n"
            f"Komissiya: {TRANSFER_FEE_PCT}% (⭐ VIP uchun — yo'q). O'zingizdagi miqdordan ortig'ini yubora olmaysiz.")
DROP_HELP = ("🎁 <b>Sovga tashlash</b>\nGuruhda yozing:\n<code>/sovga 100</code> — 100💵\n"
             "<code>/sovga 2 olmos</code> — 2💎\n\nChatda tugma paydo bo'ladi — uni <b>birinchi bosgan</b> oladi. "
             "Hech kim olmasa, bir ozdan keyin sizga qaytariladi.")
CUR_LABEL = {"money": "💵", "diamonds": "💎"}


def parse_money_args(text: str):
    """'500', '500 pul', '2 olmos', '5💎', 'hammasi' -> (miqdor | 'all' | None, 'money' | 'diamonds')"""
    cur, amt = "money", None
    for t in (text or "").lower().replace(",", " ").split():
        if t.endswith("💎"):
            cur, t = "diamonds", t[:-1]
        elif t.endswith("💵"):
            t = t[:-1]
        if t in ("olmos", "dia", "diamond", "diamonds"):
            cur = "diamonds"
        elif t in ("pul", "money", "som", "so'm", ""):
            pass
        elif t in ("hammasi", "all", "barchasi"):
            amt = "all"
        elif t.isdigit() and amt is None:
            amt = int(t)
        else:
            return None, cur
    return amt, cur


def _credit(uid: int, cur: str, n: int):
    (add_dia if cur == "diamonds" else add_money)(uid, n)


@router.message(Command("pay", "otkaz", "send"))
async def cmd_pay(m: Message, command: CommandObject):
    rep_msg = m.reply_to_message
    if m.chat.type == "private" or not rep_msg or not rep_msg.from_user or rep_msg.from_user.is_bot:
        return await m.answer(PAY_HELP)
    me, to = m.from_user, rep_msg.from_user
    if to.id == me.id:
        return await m.answer("🙃 O'zingizga pul o'tkaza olmaysiz.")
    amt, cur = parse_money_args(command.args or "")
    if amt is None:
        return await m.answer(PAY_HELP)
    mny, dia = get_bal(me.id)
    bal = dia if cur == "diamonds" else mny
    if amt == "all":
        amt = bal
    sym = CUR_LABEL[cur]
    if amt <= 0:
        return await m.answer("❌ Miqdor noto'g'ri yoki hisobingizda mablag' yo'q.")
    if amt > bal:
        return await m.answer(f"❌ Hisobingizda yetarli mablag' yo'q. Sizda: <b>{bal}</b>{sym}")
    vip = is_vip(me.id)
    fee = 0 if vip else amt * TRANSFER_FEE_PCT // 100
    got = amt - fee
    if got <= 0:
        return await m.answer("❌ Miqdor juda kichik.")
    if not spend(me.id, cur, amt):
        return await m.answer("❌ Hisobingizda yetarli mablag' yo'q.")
    ensure_user(to.id)
    _credit(to.id, cur, got)
    fee_txt = "komissiya yo'q (⭐ VIP)" if vip else f"komissiya: {fee}{sym} ({TRANSFER_FEE_PCT}%)"
    await m.answer(f"💸 <b>{esc(me.full_name)}</b> → <b>{esc(to.full_name)}</b>\n"
                   f"Yuborildi: <b>{amt}</b>{sym} · qabul qildi: <b>{got}</b>{sym}\n<i>{fee_txt}</i>")


def refund_drop_row(did: int):
    """Hech kim olmagan sovgani egasiga qaytaradi. Qaytarilgan bo'lsa, qatorni qaytaradi."""
    row = db.execute("SELECT chat_id,msg_id,owner,cur,amount FROM drops WHERE id=? AND claimed_by IS NULL",
                     (did,)).fetchone()
    if not row:
        return None
    c = db.execute("UPDATE drops SET claimed_by=-1 WHERE id=? AND claimed_by IS NULL", (did,))
    db.commit()
    if c.rowcount != 1:
        return None
    _credit(row[2], row[3], row[4])
    return row


async def _drop_closed_text(row, text: str):
    chat_id, msg_id = row[0], row[1]
    if not msg_id:
        return
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=None)
    except TelegramAPIError:
        pass


async def drop_expire(did: int):
    await asyncio.sleep(DROP_TTL)
    row = refund_drop_row(did)
    if row:
        await _drop_closed_text(row, "⌛ Sovgani hech kim olmadi — egasiga qaytarildi.")


async def refund_open_drops():
    """Bot qayta ishga tushganda taymerlar yo'qoladi — olinmagan sovgalar egasiga qaytariladi."""
    for (did,) in db.execute("SELECT id FROM drops WHERE claimed_by IS NULL").fetchall():
        row = refund_drop_row(did)
        if row:
            await _drop_closed_text(row, "⌛ Sovga qaytarildi (bot qayta ishga tushdi).")


@router.message(Command("sovga", "drop", "giveaway"))
async def cmd_drop(m: Message, command: CommandObject):
    if m.chat.type not in ("group", "supergroup"):
        return await m.answer(DROP_HELP)
    amt, cur = parse_money_args(command.args or "")
    if amt is None:
        return await m.answer(DROP_HELP)
    me = m.from_user
    mny, dia = get_bal(me.id)
    bal = dia if cur == "diamonds" else mny
    if amt == "all":
        amt = bal
    sym = CUR_LABEL[cur]
    if amt <= 0:
        return await m.answer("❌ Miqdor noto'g'ri yoki hisobingizda mablag' yo'q.")
    if amt > bal:
        return await m.answer(f"❌ Hisobingizda yetarli mablag' yo'q. Sizda: <b>{bal}</b>{sym}")
    if not spend(me.id, cur, amt):
        return await m.answer("❌ Hisobingizda yetarli mablag' yo'q.")
    c = db.execute("INSERT INTO drops(chat_id,msg_id,owner,cur,amount,created) VALUES(?,?,?,?,?,?)",
                   (m.chat.id, 0, me.id, cur, amt, int(time.time())))
    did = c.lastrowid
    db.commit()
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{sym} Olish", callback_data=f"dr:{did}")
    msg = await send(m.chat.id, f"🎁 <b>{esc(me.full_name)}</b> sovga tashladi!\n\n{sym} <b>{amt}</b>\n\n"
                                "Birinchi bo'lib tugmani bosgan oladi 👇", reply_markup=kb.as_markup())
    if not msg:
        refund_drop_row(did)
        return await m.answer("❌ Sovgani yuborib bo'lmadi, pulingiz qaytarildi.")
    db.execute("UPDATE drops SET msg_id=? WHERE id=?", (msg.message_id, did))
    db.commit()
    spawn(drop_expire(did))


@router.callback_query(F.data.startswith("dr:"))
async def drop_cb(cq: CallbackQuery):
    try:
        did = int(cq.data.split(":")[1])
    except ValueError:
        return await cq.answer()
    row = db.execute("SELECT owner,cur,amount,claimed_by FROM drops WHERE id=?", (did,)).fetchone()
    if not row or row[3] is not None:
        return await cq.answer("😔 Kech qoldingiz — sovga allaqachon olingan.", show_alert=True)
    owner, cur, amount, _ = row
    uid = cq.from_user.id
    if uid == owner:
        return await cq.answer("Bu sovgani o'zingiz tashlagansiz 🙂", show_alert=True)
    c = db.execute("UPDATE drops SET claimed_by=? WHERE id=? AND claimed_by IS NULL", (uid, did))
    db.commit()
    if c.rowcount != 1:
        return await cq.answer("😔 Kech qoldingiz — sovga allaqachon olingan.", show_alert=True)
    _credit(uid, cur, amount)
    sym = CUR_LABEL[cur]
    await cq.answer(f"🎉 Siz {amount}{sym} oldingiz!", show_alert=True)
    if cq.message:
        await safe_edit(cq.message, f"🎉 <b>{esc(cq.from_user.full_name)}</b> sovgani birinchi bo'lib oldi: "
                                    f"<b>{amount}</b>{sym}!\n🎁 Sovga egasi: {esc(user_name(owner))}")


@router.message(Command("shop"))
async def cmd_shop(m: Message):
    if m.chat.type != "private":
        return await m.answer("🛒 Do'kon shaxsiy chatda ishlaydi — botga yozing.")
    await show_shop(m, m.from_user.id)


@router.message(Command("wallet", "balance"))
async def cmd_wallet(m: Message):
    if m.chat.type != "private":
        return await m.answer("👛 Hamyon shaxsiy chatda ishlaydi — botga yozing.")
    await m.answer(wallet_text(m.from_user.id), reply_markup=wallet_kb())


@router.message(Command("bonus"))
async def cmd_bonus(m: Message):
    ok, text = claim_daily(m.from_user.id)
    await m.answer(text)


# ── Telegram Stars to'lovi ──
@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    if q.invoice_payload.startswith("ttl|"):
        ok = False
        try:
            _, buyer, target, key, stars = q.invoice_payload.split("|")
            ok = (int(buyer) == q.from_user.id and key in TITLES and q.currency == "XTR"
                  and int(stars) == tprice(key) == q.total_amount
                  and key not in TOWNED.get(int(target), ()))
        except Exception:
            ok = False
        await q.answer(ok=ok, error_message=None if ok else "Unvon narxi o'zgargan yoki u allaqachon mavjud. Qaytadan urinib ko'ring.")
        return
    ok = False
    try:
        kind, uid, stars, dia = q.invoice_payload.split("|")
        ok = (kind == "dia" and int(uid) == q.from_user.id and q.currency == "XTR"
              and q.total_amount == int(stars) and (int(stars), int(dia)) in get_packs())
    except Exception:
        ok = False
    await q.answer(ok=ok, error_message=None if ok else "Paket topilmadi yoki narxi o'zgargan. Qaytadan urinib ko'ring.")


@router.message(F.successful_payment)
async def on_paid(m: Message):
    sp = m.successful_payment
    if sp.invoice_payload.startswith("ttl|"):
        return await on_paid_title(m, sp)
    try:
        kind, uid, stars, dia = sp.invoice_payload.split("|")
        uid, stars, dia = int(uid), int(stars), int(dia)
    except Exception:
        log.warning("Noto'g'ri payload: %s", sp.invoice_payload)
        return
    if kind != "dia" or uid != m.from_user.id or sp.currency != "XTR" or sp.total_amount != stars:
        log.warning("To'lov tekshiruvdan o'tmadi: %s", sp)
        return
    try:
        db.execute("INSERT INTO payments(user_id,stars,diamonds,charge_id,ts) VALUES(?,?,?,?,?)",
                   (uid, stars, dia, sp.telegram_payment_charge_id, int(time.time())))
        db.commit()
    except sqlite3.IntegrityError:
        return  # bu to'lov allaqachon hisoblangan
    add_dia(uid, dia)
    await m.answer(f"✅ To'lov qabul qilindi!\n💎 +{dia} olmos hamyoningizga qo'shildi.\n\n" + wallet_text(uid),
                   reply_markup=wallet_kb())
    for oid in OWNER_IDS:
        await send(oid, f"💰 Yangi to'lov: <b>{stars}⭐</b> → {dia}💎\n👤 {ulink(uid)} (<code>{uid}</code>)")


async def on_paid_title(m: Message, sp):
    try:
        _, buyer, target, key, stars = sp.invoice_payload.split("|")
        buyer, target, stars = int(buyer), int(target), int(stars)
    except Exception:
        log.warning("Noto'g'ri unvon payload: %s", sp.invoice_payload)
        return
    if buyer != m.from_user.id or key not in TITLES or sp.currency != "XTR" or sp.total_amount != stars:
        log.warning("Unvon to'lovi tekshiruvdan o'tmadi: %s", sp)
        return
    try:
        db.execute("INSERT INTO payments(user_id,stars,diamonds,charge_id,ts,item) VALUES(?,?,?,?,?,?)",
                   (buyer, stars, 0, sp.telegram_payment_charge_id, int(time.time()), f"{key}:{target}"))
        db.commit()
    except sqlite3.IntegrityError:
        return
    grant_title(target, key)
    v = TITLES[key]
    if target == buyer:
        await m.answer(f"✅ To'lov qabul qilindi!\n{v['name']} unvoni endi sizniki!\n\n{v['desc']}")
    else:
        await m.answer(f"✅ To'lov qabul qilindi!\n🎁 {v['name']} unvoni {ulink(target)} ga sovg'a qilindi!")
        await send(target, f"🎁 {ulink(buyer)} sizga <b>{v['name']}</b> unvonini sovg'a qildi!\n\n{v['desc']}")
    for oid in OWNER_IDS:
        await send(oid, f"💰 Yangi to'lov: <b>{stars}⭐</b> → {v['name']}\n👤 {ulink(buyer)} (<code>{buyer}</code>)"
                        + (f" → 🎁 {ulink(target)}" if target != buyer else ""))


def has_gift(m: Message) -> bool:
    return (m.from_user is not None and m.from_user.id in GIFT_STATE and m.from_user.id not in ADMIN_STATE
            and not (m.text or "").startswith("/"))


@router.message(F.chat.type == "private", has_gift)
async def gift_input(m: Message):
    uid = m.from_user.id
    st = GIFT_STATE.get(uid)
    if not st:
        return
    t = (m.text or "").strip()
    target = None
    fo = getattr(m, "forward_origin", None)
    su = getattr(fo, "sender_user", None)
    if su:
        target = su.id
    elif t.lstrip("-").isdigit():
        target = int(t)
    elif t.startswith("@"):
        target = find_user_by_username(t)
    if not target or not db.execute("SELECT 1 FROM users WHERE user_id=?", (target,)).fetchone():
        await m.answer("❌ Foydalanuvchi topilmadi. U botga kamida bir marta /start bosgan bo'lishi kerak.\n"
                       "ID, @username yuboring yoki undan xabar forward qiling. Bekor qilish: /cancel")
        return
    if target == uid:
        await m.answer("O'zingiz uchun «⭐ Sotib olish» tugmasidan foydalaning.")
        return
    key = st["key"]
    if key in TOWNED.get(target, ()):
        GIFT_STATE.pop(uid, None)
        await m.answer("ℹ️ Bu foydalanuvchida bu unvon allaqachon bor.")
        return
    GIFT_STATE.pop(uid, None)
    try:
        await send_title_invoice(uid, target, key)
    except TelegramAPIError as e:
        log.warning("sovg'a invoice xato: %s", e)
        await m.answer("❌ To'lov oynasini ochib bo'lmadi. Keyinroq urinib ko'ring.")
        return
    await m.answer(f"👆 {ulink(target)} uchun to'lov oynasi. To'lagach unvon unga beriladi.")


@router.message(Command("paysupport"))
async def cmd_paysupport(m: Message):
    owners = ", ".join(ulink(o) for o in OWNER_IDS) or "admin"
    await m.answer("💬 To'lov bilan bog'liq muammo bo'lsa, admin bilan bog'laning: " + owners +
                   "\nTo'lov ma'lumotlari (to'lov ID) bilan yozing.")


@router.message(Command("backup"))
async def cmd_backup(m: Message):
    if m.from_user.id not in OWNER_IDS:
        return
    if RESTORE_FAILED:
        return await m.answer("⚠️ Ishga tushganda zaxiradan tiklab bo'lmadi, shuning uchun eski zaxira buzilmasligi "
                              "uchun yangi zaxira to'xtatildi. Render'da Manual Deploy qiling va loglarni tekshiring.")
    res = await backup_now(force=True)
    if res:
        await m.answer(f"💾 Zaxira yuborildi va pin qilindi (chat: <code>{BACKUP_CHAT_ID}</code>).")
    else:
        await m.answer("⚠️ Zaxira yuborilmadi. Zaxira oladigan akkaunt botga shaxsiy chatda /start bosganmi? "
                       "Render loglarini tekshiring.")


@router.message(Command("dbinfo"))
async def cmd_dbinfo(m: Message):
    if m.from_user.id not in OWNER_IDS:
        return
    q = lambda sql: db.execute(sql).fetchone()[0]
    await m.answer(
        "🗄 <b>Baza holati</b>\n"
        f"Ishga tushganda: {esc(RESTORE_INFO)}\n"
        f"Baza fayli: <code>{esc(DB_PATH)}</code>\n"
        f"Foydalanuvchilar: <b>{q('SELECT COUNT(*) FROM users')}</b> · puli bor: {q('SELECT COUNT(*) FROM users WHERE COALESCE(money,0)>0')} "
        f"· olmosi bor: {q('SELECT COUNT(*) FROM users WHERE COALESCE(diamonds,0)>0')}\n"
        f"Statistika qatorlari: {q('SELECT COUNT(*) FROM stats')}\n"
        f"Oxirgi zaxira xabari: <code>{BACKUP_MSG_ID}</code> (chat {BACKUP_CHAT_ID})\n"
        f"Zaxira: {'to`xtatilgan (tiklash xatosi)' if RESTORE_FAILED else 'yoqilgan' if BACKUP_ENABLED else 'o`chirilgan'}")


@router.message(Command("payments"))
async def cmd_payments(m: Message):
    if m.from_user.id not in OWNER_IDS:
        return
    rows = db.execute("SELECT user_id,stars,diamonds,charge_id,refunded FROM payments "
                      "ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        return await m.answer("To'lovlar hali yo'q.")
    lines = [f"{'↩️' if r[4] else '✅'} {r[0]} — {r[1]}⭐ → {r[2]}💎\n<code>{r[3]}</code>" for r in rows]
    await m.answer("💰 <b>Oxirgi to'lovlar</b>\nQaytarish: <code>/refund TO'LOV_ID</code>\n\n" + "\n\n".join(lines))


@router.message(Command("refund"))
async def cmd_refund(m: Message, command: CommandObject):
    if m.from_user.id not in OWNER_IDS:
        return
    cid = (command.args or "").strip()
    row = db.execute("SELECT user_id,diamonds,refunded,item FROM payments WHERE charge_id=?", (cid,)).fetchone()
    if not row:
        return await m.answer("❌ To'lov topilmadi. Format: /refund TO'LOV_ID  (ro'yxat: /payments)")
    if row[2]:
        return await m.answer("ℹ️ Bu to'lov allaqachon qaytarilgan.")
    try:
        await bot.refund_star_payment(user_id=row[0], telegram_payment_charge_id=cid)
    except TelegramAPIError as e:
        return await m.answer(f"❌ Qaytarib bo'lmadi: {esc(str(e))}")
    db.execute("UPDATE payments SET refunded=1 WHERE charge_id=?", (cid,))
    db.commit()
    if row[3]:
        tkey, _, ttarget = row[3].partition(":")
        if tkey in TITLES and ttarget.isdigit():
            revoke_title(int(ttarget), tkey)
        await m.answer(f"↩️ Qaytarildi. {ttarget} dan {tkey} unvoni olib tashlandi.")
    else:
        add_dia(row[0], -row[1])
        await m.answer(f"↩️ Qaytarildi. Foydalanuvchidan {row[1]}💎 ayirildi.")
    await send(row[0], "↩️ To'lovingiz qaytarildi (Stars hisobingizga qaytdi).")


# ───────────────────────── ADMIN PANEL ─────────────────────────
PERMS = {
    "stats": "📊 Statistika",
    "broadcast": "📢 Xabar yuborish",
    "ban": "🚫 Ban / Unban",
    "vip": "⭐ VIP berish",
    "games": "🎮 O'yinlarni boshqarish",
    "settings": "⚙️ Sozlamalar",
    "admins": "👑 Adminlarni boshqarish",
    "channels": "📢 Kanallar va chatlar",
    "economy": "💰 Iqtisod (pul, olmos, do'kon, unvon)",
    "gifs": "🎞 GIFlar",
}
SETTING_LABELS = {
    "REG_TIME": "⏳ Ro'yxat vaqti (soniya)",
    "NIGHT_TIME": "🌙 Tun vaqti (soniya)",
    "DAY_TIME": "☀️ Muhokama vaqti (soniya)",
    "VOTE_TIME": "🗳 Ovoz berish vaqti (soniya)",
    "CONFIRM_TIME": "👍👎 Osishni tasdiqlash vaqti (soniya)",
    "LAST_WORD_TIME": "🕯 Oxirgi so'z yozish vaqti (soniya)",
    "MIN_PLAYERS": "👥 Minimal o'yinchi",
    "MAX_PLAYERS": "👥 Maksimal o'yinchi",
    "REWARD_PLAY": "🎮 O'yin mukofoti (pul)",
    "REWARD_WIN": "🏆 G'alaba mukofoti (pul)",
    "DAILY_BONUS": "🎁 Kunlik bonus (pul)",
    "DIAMOND_RATE": "💱 1 olmos = necha pul",
    "REBIRTH_COST": "♻️ Qayta tug'ilish narxi (olmos)",
    "VIP_DIAMONDS": "⭐ VIP 30 kun narxi (olmos)",
}
ECON_LIMITS = {
    "REWARD_PLAY": (0, 1_000_000), "REWARD_WIN": (0, 1_000_000), "DAILY_BONUS": (0, 1_000_000),
    "DIAMOND_RATE": (1, 1_000_000), "REBIRTH_COST": (1, 100), "VIP_DIAMONDS": (1, 100_000),
}
ADMIN_STATE = TTLState()   # admin_id -> {"k": ...}
class GuardMW(BaseMiddleware):
    """Foydalanuvchilarni yozib boradi, bloklanganlarni va obuna bo'lmaganlarni to'xtatadi."""

    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat
        if u and not u.is_bot:
            try:
                touch_user(u, bool(chat and chat.type == "private"))
                if chat and chat.type in ("group", "supergroup") and touch_chat(chat):
                    spawn(refresh_chat_info(chat.id))
            except Exception:
                log.exception("touch xato")
            if u.id in BANNED and u.id not in OWNER_IDS:
                if isinstance(event, CallbackQuery):
                    await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
                elif chat and chat.type == "private":
                    await event.answer("🚫 Siz bloklangansiz.")
                return None
            # majburiy obuna (faqat shaxsiy chatda; adminlar uchun emas)
            if chat and chat.type == "private" and not is_panel_user(u.id):
                skip = ((isinstance(event, Message) and event.successful_payment is not None)
                        or (isinstance(event, CallbackQuery) and event.data == "sub:check"))
                if not skip:
                    miss = await missing_channels(u.id)
                    if miss:
                        if isinstance(event, Message):
                            txt = event.text or ""
                            if txt.startswith("/start join_"):
                                try:
                                    PENDING_JOIN[u.id] = int(txt.split("join_", 1)[1].strip())
                                except ValueError:
                                    pass
                        else:
                            await event.answer("🔒 Avval kanallarga a'zo bo'ling!", show_alert=True)
                        await send(chat.id, SUB_TEXT, reply_markup=sub_kb(miss))
                        return None
        t0 = time.perf_counter()
        try:
            return await handler(event, data)
        finally:
            dt = time.perf_counter() - t0
            if dt > 1.5:
                what = getattr(event, "data", None) or getattr(event, "text", None)
                log.warning("⏱ Sekin ishladi: %.1f soniya — %s", dt, what)


router.message.outer_middleware(GuardMW())
router.callback_query.outer_middleware(GuardMW())


def has_perm(uid: int, perm: str) -> bool:
    return uid in OWNER_IDS or perm in ADMINS.get(uid, ())


def is_panel_user(uid: int) -> bool:
    return uid in OWNER_IDS or uid in ADMINS


def can_edit_admin(uid: int, target: int) -> bool:
    if target in OWNER_IDS:
        return False
    if uid in OWNER_IDS:
        return True
    return "admins" in ADMINS.get(uid, ()) and "admins" not in ADMINS.get(target, ())


def save_admin(uid: int):
    ensure_user(uid)
    db.execute("INSERT INTO admins(user_id,perms) VALUES(?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET perms=excluded.perms",
               (uid, ",".join(sorted(ADMINS.get(uid, ())))))
    db.commit()


def set_ban(uid: int, flag: bool):
    ensure_user(uid)
    db.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if flag else 0, uid))
    db.commit()
    (BANNED.add if flag else BANNED.discard)(uid)


def set_vip(uid: int, days: int):
    ensure_user(uid)
    until = 0 if days == 0 else int(time.time()) + days * 86400
    db.execute("UPDATE users SET vip=1, vip_until=? WHERE user_id=?", (until, uid))
    db.commit()
    VIPS[uid] = until


def del_vip(uid: int):
    db.execute("UPDATE users SET vip=0, vip_until=0 WHERE user_id=?", (uid,))
    db.commit()
    VIPS.pop(uid, None)


def setting_ok(key: str, val: int) -> bool:
    if key.endswith("_TIME"):
        return 1 <= val <= 86400      # istalgan soniya
    if key == "MIN_PLAYERS":
        return 4 <= val <= 60 and val <= MAX_PLAYERS
    if key == "MAX_PLAYERS":
        return max(4, MIN_PLAYERS) <= val <= 60
    if key in ECON_LIMITS:
        lo, hi = ECON_LIMITS[key]
        return lo <= val <= hi
    return False


def parse_id(m: Message) -> Optional[int]:
    fo = getattr(m, "forward_origin", None)
    su = getattr(fo, "sender_user", None)
    if su:
        return su.id
    t = (m.text or "").strip()
    return int(t) if t.lstrip("-").isdigit() else None


def back_kb(to: str = "ad:home"):
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Orqaga", callback_data=to)
    return kb.as_markup()


def panel_text(uid: int) -> str:
    if uid in OWNER_IDS:
        who = "👑 Owner (to'liq huquq)"
        perms = ""
    else:
        who = "🛡 Admin"
        names = [PERMS[p] for p in sorted(ADMINS.get(uid, ())) if p in PERMS]
        perms = "\nHuquqlaringiz: " + (", ".join(names) if names else "hozircha yo'q")
    tip = ""
    if has_perm(uid, "economy"):
        tip = ("\n\n🎁 <b>Istalgan narsani berish:</b> <code>/give ID narsa miqdor</code> "
               "(yordam: <code>/give</code>)")
    return f"👑 <b>Admin panel</b>\n\nSiz: {who}{perms}{tip}"


def admin_main_kb(uid: int):
    kb = InlineKeyboardBuilder()
    items = [
        ("stats", "📊 Statistika", "ad:stats"),
        ("stats", "🔎 Foydalanuvchi", "ad:find"),
        ("broadcast", "📢 Xabar yuborish", "ad:bc"),
        ("ban", "🚫 Ban / Unban", "ad:ban"),
        ("vip", "⭐ VIP", "ad:vip"),
        ("games", "🎮 O'yinlar", "ad:games"),
        ("settings", "⚙️ Sozlamalar", "ad:set"),
        ("admins", "👑 Adminlar", "ad:adm"),
        ("channels", "📢 Kanallar", "ad:ch"),
        ("economy", "💰 Iqtisod", "ad:eco"),
        ("gifs", "🎞 GIFlar", "ad:gif"),
    ]
    for perm, text, cb in items:
        if has_perm(uid, perm):
            kb.button(text=text, callback_data=cb)
    kb.adjust(2)
    return kb.as_markup()


def admin_edit_view(target: int):
    perms = ADMINS.get(target, set())
    kb = InlineKeyboardBuilder()
    for p, label in PERMS.items():
        kb.button(text=f"{'✅' if p in perms else '❌'} {label}", callback_data=f"ad:ap:{target}:{p}")
    kb.button(text="🗑 Adminlikdan olish", callback_data=f"ad:adel:{target}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:adm")
    kb.adjust(1)
    text = (f"🛡 <b>Admin:</b> {ulink(target)} (<code>{target}</code>)\n\n"
            "Huquqlarni tugmalar bilan yoqing/o'chiring:")
    return text, kb.as_markup()


def user_info_text(t: int) -> str:
    r = db.execute("SELECT name,banned,started FROM users WHERE user_id=?", (t,)).fetchone()
    s = db.execute("SELECT games,wins FROM stats WHERE user_id=?", (t,)).fetchone()
    if not r and not s:
        return f"❌ <code>{t}</code> ID bo'yicha foydalanuvchi topilmadi."
    games, wins = s if s else (0, 0)
    status = []
    if t in OWNER_IDS:
        status.append("👑 Owner")
    elif t in ADMINS:
        status.append("🛡 Admin")
    if is_vip(t):
        until = VIPS.get(t, 0)
        status.append("⭐ VIP (umrbod)" if until == 0 else
                      "⭐ VIP (" + time.strftime("%d.%m.%Y", time.localtime(until)) + " gacha)")
    if t in BANNED:
        status.append("🚫 Bloklangan")
    return (f"🔎 <b>Foydalanuvchi</b>\n\n👤 {ulink(t)}\n🆔 <code>{t}</code>\n"
            f"🎮 O'yinlar: {games}\n🏆 G'alabalar: {wins}\n"
            f"💵 Pul: {get_bal(t)[0]}\n💎 Olmos: {get_bal(t)[1]}\n"
            f"📩 Botni ishga tushirgan: {'ha' if r and r[2] else 'yoq'}\n"
            f"Holat: {', '.join(status) if status else 'oddiy foydalanuvchi'}")


@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if m.chat.type != "private":
        await m.answer("🔒 Admin panel faqat shaxsiy chatda ochiladi — botga yozing: /admin")
        return
    uid = m.from_user.id
    if not is_panel_user(uid):
        await m.answer("⛔️ Siz admin emassiz.")
        return
    ADMIN_STATE.pop(uid, None)
    GIFT_STATE.pop(uid, None)
    await m.answer(panel_text(uid), reply_markup=admin_main_kb(uid))


GIVE_RAW = lambda: sorted(k for k, v in ITEMS.items() if "grants" not in v and "gives" not in v and "box" not in v)


def give_help() -> str:
    return ("🎁 <b>/give</b> — istalgan narsani istalgan kishiga, istalgancha berish\n\n"
            "<code>/give ID narsa miqdor</code>\n<code>/give @username narsa miqdor</code>\n"
            "yoki odamning xabariga <b>javob (reply)</b> qilib: <code>/give narsa miqdor</code>\n\n"
            "<b>Narsalar:</b>\n"
            "• <code>pul 5000</code> · <code>olmos 50</code> (minus yozsangiz — ayiradi)\n"
            "• <code>vip 30</code> — kun (<code>vip 0</code> = umrbod, <code>unvip</code> = VIP'ni olish)\n"
            "• <code>unvon KALIT</code> — " + ", ".join(TITLES) + "\n"
            "• <code>geroy 12</code> — Geroy leveli (1–12)\n"
            "• <code>effekt KALIT</code> — " + ", ".join(FX) + "\n"
            "• <code>narsa KALIT MIQDOR</code> — " + ", ".join(GIVE_RAW()) + "\n\n"
            "Hammaga: <code>/giveall pul 1000</code> (pul / olmos)")


def _give_target(m: Message, toks: list):
    """(target_id, qolgan_tokenlar) yoki (None, xabar)"""
    rp = m.reply_to_message
    if rp and rp.from_user and not rp.from_user.is_bot:
        return rp.from_user.id, toks
    if not toks:
        return None, "❌ Kimga berilishi kerak: ID, @username yoki reply."
    t = toks[0]
    if t.startswith("@"):
        tid = find_user_by_username(t)
        if not tid:
            return None, "❌ Bu @username bazada yo'q. Raqamli ID yuboring."
        return tid, toks[1:]
    if t.lstrip("-").isdigit():
        return int(t), toks[1:]
    if t.lower() in ("me", "men", "o'zimga"):
        return m.from_user.id, toks[1:]
    return None, "❌ Kimga berilishi kerak: ID, @username yoki reply."


@router.message(Command("give", "bering"))
async def cmd_give(m: Message):
    uid = m.from_user.id
    if not has_perm(uid, "economy"):
        return
    toks = (m.text or "").split()[1:]
    if not toks:
        return await m.answer(give_help())
    target, rest = _give_target(m, toks)
    if target is None:
        return await m.answer(rest + "\n\n" + give_help())
    if not rest:
        return await m.answer("❌ Nima berilsin?\n\n" + give_help())
    what = rest[0].lower()
    args = rest[1:]
    ensure_user(target)

    def num(i=0, default=None):
        if len(args) > i and args[i].lstrip("+-").isdigit():
            v = int(args[i])
            return v if abs(v) <= 1_000_000_000_000 else None
        return default

    msg_out = None
    dm = None
    if what in ("pul", "money", "som", "so'm"):
        n = num()
        if n is None:
            return await m.answer("❌ Miqdor yozing: <code>/give ID pul 5000</code>")
        add_money(target, n)
        msg_out, dm = f"💵 {n:+d}", f"💵 <b>{n:+d}</b>"
    elif what in ("olmos", "dia", "diamond"):
        n = num()
        if n is None:
            return await m.answer("❌ Miqdor yozing: <code>/give ID olmos 50</code>")
        add_dia(target, n)
        msg_out, dm = f"💎 {n:+d}", f"💎 <b>{n:+d}</b>"
    elif what == "vip":
        days = num(0, 30)
        if days is None or days < 0:
            return await m.answer("❌ Kun soni: <code>/give ID vip 30</code> (0 = umrbod)")
        set_vip(target, days)
        txt = "umrbod" if days == 0 else f"{days} kun"
        msg_out, dm = f"⭐ VIP ({txt})", f"⭐ <b>VIP</b> ({txt})"
    elif what in ("unvip", "-vip"):
        del_vip(target)
        msg_out = "⭐ VIP olib tashlandi"
    elif what in ("unvon", "title"):
        key = args[0].lower() if args else ""
        if key not in TITLES:
            return await m.answer("❌ Unvon kaliti: " + ", ".join(TITLES))
        grant_title(target, key)
        msg_out, dm = f"{TITLES[key]['name']} unvoni", f"{TITLES[key]['name']} <b>unvoni</b>"
    elif what in ("geroy", "hero"):
        lvl = num(0, 1)
        if lvl is None or not 1 <= lvl <= HERO_MAX:
            return await m.answer(f"❌ Level 1–{HERO_MAX}: <code>/give ID geroy 12</code>")
        db.execute("INSERT INTO hero(user_id,level) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET level=?",
                   (target, lvl, lvl))
        db.commit()
        msg_out, dm = f"🐺 Geroy {lvl}-level", f"🐺 <b>Geroy</b> ({lvl}-level)"
    elif what in ("effekt", "fx", "aura"):
        key = args[0].lower() if args else ""
        if key not in FX:
            return await m.answer("❌ Effekt kaliti: " + ", ".join(FX))
        if key == "fx_owner" and uid not in OWNER_IDS:
            return await m.answer("❌ Owner aurani faqat owner bera oladi.")
        if inv_qty(target, key) <= 0:
            inv_add(target, key, 1)
        if not kv_get(f"fx_{target}"):
            kv_set(f"fx_{target}", key)
        msg_out, dm = f"✨ {FX[key]['name']}", f"✨ <b>{FX[key]['name']}</b> effekti"
    elif what in ("narsa", "item"):
        key = args[0] if args else ""
        n = num(1, 1)
        if key not in ITEMS or n is None:
            return await m.answer("❌ Narsa kaliti: " + ", ".join(GIVE_RAW()) + "\nMasalan: <code>/give ID narsa shield 5</code>")
        it = ITEMS[key]
        for gk, gq in (it.get("grants") or {key: 1}).items():
            inv_add(target, gk, gq * n)
        msg_out, dm = f"{it['name']} ×{n}", f"{it['name']} ×{n}"
    else:
        return await m.answer("❌ Tushunmadim.\n\n" + give_help())

    await m.answer(f"✅ {ulink(target)} (<code>{target}</code>) ga berildi: {msg_out}")
    if dm:
        await send(target, f"🎁 Admin sizga berdi: {dm}")


@router.message(Command("giveall"))
async def cmd_giveall(m: Message):
    if not has_perm(m.from_user.id, "economy"):
        return
    toks = (m.text or "").split()[1:]
    cols = {"pul": "money", "money": "money", "olmos": "diamonds", "dia": "diamonds"}
    if len(toks) != 2 or toks[0].lower() not in cols or not toks[1].lstrip("+-").isdigit() \
            or abs(int(toks[1])) > 1_000_000_000:
        return await m.answer("Format: <code>/giveall pul 1000</code> (pul / olmos)")
    col, n = cols[toks[0].lower()], int(toks[1])
    cur = db.execute(f"UPDATE users SET {col}=MAX(0,COALESCE({col},0)+?) WHERE started=1", (n,))
    db.commit()
    await m.answer(f"✅ {cur.rowcount} ta foydalanuvchiga {n:+d} ({toks[0]}) berildi.")


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    a = ADMIN_STATE.pop(m.from_user.id, None)
    b = GIFT_STATE.pop(m.from_user.id, None)
    if a is not None or b is not None:
        await m.answer("❎ Bekor qilindi.")


async def do_broadcast(admin_id: int, src_chat: int, src_msg: int):
    targets = [r[0] for r in db.execute("SELECT user_id FROM users WHERE started=1 AND banned=0")]
    targets += [r[0] for r in db.execute("SELECT chat_id FROM chats")]
    ok = fail = 0
    for cid in targets:
        for _ in range(2):
            try:
                await bot.copy_message(cid, src_chat, src_msg)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramAPIError:
                fail += 1
                break
        await asyncio.sleep(0.05)
    await send(admin_id, f"📢 <b>Xabar yuborish tugadi</b>\n\n✅ Yetkazildi: {ok}\n❌ Xato: {fail}")


@router.callback_query(F.data.startswith("ad:"))
async def admin_cb(cq: CallbackQuery):
    uid = cq.from_user.id
    msg = cq.message
    if msg is None or msg.chat.type != "private" or not is_panel_user(uid):
        return await cq.answer("⛔️ Ruxsat yo'q.", show_alert=True)
    parts = cq.data.split(":")
    act = parts[1]
    GIFT_STATE.pop(uid, None)

    async def deny():
        await cq.answer("⛔️ Bu bo'lim uchun huquqingiz yo'q.", show_alert=True)

    if act == "home" or act == "cancel":
        ADMIN_STATE.pop(uid, None)
        await safe_edit(msg, panel_text(uid), reply_markup=admin_main_kb(uid))
        return await cq.answer()

    # ── statistika
    if act == "stats":
        if not has_perm(uid, "stats"):
            return await deny()

        def q(sql):
            return db.execute(sql).fetchone()[0]

        text = (
            "📊 <b>Bot statistikasi</b>\n\n"
            f"👤 Foydalanuvchilar: {q('SELECT COUNT(*) FROM users')}\n"
            f"📩 Botni ishga tushirganlar: {q('SELECT COUNT(*) FROM users WHERE started=1')}\n"
            f"👥 Guruhlar: {q('SELECT COUNT(*) FROM chats')}\n"
            f"📅 Oylik faol foydalanuvchilar: {fmt_num(monthly_users())}\n"
            f"🎮 Hozir faol o'yinlar: {len(GAMES)}\n"
            f"🏁 Tugagan o'yinlar: {kv_get('cnt_games', '0')}\n"
            f"⭐ VIP: {sum(1 for x in VIPS if is_vip(x))}\n"
            f"🛡 Adminlar: {len(ADMINS)}\n"
            f"🚫 Bloklanganlar: {len(BANNED)}\n"
            f"⭐ Stars daromadi: {q('SELECT COALESCE(SUM(stars),0) FROM payments WHERE refunded=0')} "
            f"(💎 sotilgan: {q('SELECT COALESCE(SUM(diamonds),0) FROM payments WHERE refunded=0')})\n"
            f"🔒 Majburiy kanallar: {len(sub_channels())}"
        )
        await safe_edit(msg, text, reply_markup=back_kb())
        return await cq.answer()

    # ── foydalanuvchini topish
    if act == "find":
        if not has_perm(uid, "stats"):
            return await deny()
        ADMIN_STATE[uid] = {"k": "find"}
        await safe_edit(msg, "🔎 Foydalanuvchi <b>ID</b> raqamini yuboring yoki undan xabar forward qiling.\n"
                             "Bekor qilish: /cancel", reply_markup=back_kb())
        return await cq.answer()

    # ── xabar yuborish
    if act == "bc":
        if not has_perm(uid, "broadcast"):
            return await deny()
        ADMIN_STATE[uid] = {"k": "bc"}
        await safe_edit(msg, "📢 Yubormoqchi bo'lgan xabarni yuboring (matn, rasm, video — hammasi bo'ladi).\n"
                             "Bekor qilish: /cancel", reply_markup=back_kb())
        return await cq.answer()

    if act == "bcgo":
        st = ADMIN_STATE.get(uid)
        if not has_perm(uid, "broadcast") or not st or st.get("k") != "bc_confirm":
            return await deny()
        ADMIN_STATE.pop(uid, None)
        task = asyncio.create_task(do_broadcast(uid, st["chat"], st["mid"]))
        BG_TASKS.add(task)
        task.add_done_callback(BG_TASKS.discard)
        await safe_edit(msg, "📢 Yuborish boshlandi... Tugagach xabar beraman.", reply_markup=back_kb())
        return await cq.answer()

    # ── ban
    if act in ("ban", "banadd", "unban"):
        if not has_perm(uid, "ban"):
            return await deny()
        if act == "banadd":
            ADMIN_STATE[uid] = {"k": "ban"}
            await safe_edit(msg, "🚫 Bloklanadigan foydalanuvchi <b>ID</b> sini yuboring yoki undan xabar "
                                 "forward qiling.\nBekor qilish: /cancel", reply_markup=back_kb("ad:ban"))
            return await cq.answer()
        if act == "unban":
            set_ban(int(parts[2]), False)
            await cq.answer("✅ Blokdan chiqarildi")
        rows = db.execute("SELECT user_id FROM users WHERE banned=1 LIMIT 30").fetchall()
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Ban qilish", callback_data="ad:banadd")
        for (t,) in rows:
            kb.button(text=f"✅ Unban: {user_name(t)[:25]}", callback_data=f"ad:unban:{t}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:home")
        kb.adjust(1)
        await safe_edit(msg, f"🚫 <b>Bloklanganlar:</b> {len(BANNED)} ta", reply_markup=kb.as_markup())
        if act != "unban":
            await cq.answer()
        return

    # ── VIP
    if act in ("vip", "vipadd", "vipd", "vipdel"):
        if not has_perm(uid, "vip"):
            return await deny()
        if act == "vipadd":
            ADMIN_STATE[uid] = {"k": "vip_id"}
            await safe_edit(msg, "⭐ VIP beriladigan foydalanuvchi <b>ID</b> sini yuboring yoki undan xabar "
                                 "forward qiling.\nBekor qilish: /cancel", reply_markup=back_kb("ad:vip"))
            return await cq.answer()
        if act == "vipd":
            set_vip(int(parts[2]), int(parts[3]))
            await send(int(parts[2]), "⭐ Tabriklaymiz! Sizga <b>VIP</b> maqomi berildi.")
            await cq.answer("✅ VIP berildi")
        if act == "vipdel":
            del_vip(int(parts[2]))
            await cq.answer("🗑 VIP olib tashlandi")
        active = [x for x in VIPS if is_vip(x)]
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ VIP berish", callback_data="ad:vipadd")
        for t in active[:30]:
            kb.button(text=f"🗑 {user_name(t)[:25]}", callback_data=f"ad:vipdel:{t}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:home")
        kb.adjust(1)
        await safe_edit(msg, f"⭐ <b>VIP foydalanuvchilar:</b> {len(active)} ta\n"
                             "VIP: ⭐ belgisi, o'yinni o'zi boshlay olish.", reply_markup=kb.as_markup())
        if act == "vip":
            await cq.answer()
        return

    # ── o'yinlar
    if act in ("games", "gstop"):
        if not has_perm(uid, "games"):
            return await deny()
        if act == "gstop":
            g = GAMES.get(int(parts[2]))
            if g:
                if g.task:
                    g.task.cancel()
                cleanup(g)
                await send(g.chat_id, "🛑 O'yin admin tomonidan to'xtatildi.")
            await cq.answer("🛑 To'xtatildi")
        kb = InlineKeyboardBuilder()
        lines = []
        for g in list(GAMES.values()):
            lines.append(f"• {esc(g.title)} — {g.state}, {len(g.players)} o'yinchi")
            kb.button(text=f"🛑 {g.title[:25]}", callback_data=f"ad:gstop:{g.chat_id}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:home")
        kb.adjust(1)
        await safe_edit(msg, "🎮 <b>Faol o'yinlar</b>\n\n" + ("\n".join(lines) or "Hozir o'yin yo'q."),
                        reply_markup=kb.as_markup())
        if act == "games":
            await cq.answer()
        return

    # ── sozlamalar
    if act in ("set", "sk"):
        if not has_perm(uid, "settings"):
            return await deny()
        if act == "sk":
            key = parts[2]
            if key not in SETTING_LABELS:
                return await cq.answer()
            ADMIN_STATE[uid] = {"k": "set", "key": key}
            await safe_edit(msg, f"{SETTING_LABELS[key]}\nHozirgi qiymat: <b>{globals()[key]}</b>\n\n"
                                 "Yangi qiymatni raqam bilan yuboring.\nBekor qilish: /cancel",
                            reply_markup=back_kb("ad:set"))
            return await cq.answer()
        kb = InlineKeyboardBuilder()
        for key, label in SETTING_LABELS.items():
            kb.button(text=f"{label}: {globals()[key]}", callback_data=f"ad:sk:{key}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:home")
        kb.adjust(1)
        await safe_edit(msg, "⚙️ <b>O'yin sozlamalari</b>\nO'zgartirmoqchi bo'lganingizni tanlang:",
                        reply_markup=kb.as_markup())
        return await cq.answer()

    # ── adminlar
    if act in ("adm", "aadd", "ae", "ap", "adel"):
        if not has_perm(uid, "admins"):
            return await deny()
        if act == "aadd":
            ADMIN_STATE[uid] = {"k": "adm_add"}
            await safe_edit(msg, "👑 Yangi admin <b>ID</b> sini yuboring yoki undan xabar forward qiling.\n"
                                 "Bekor qilish: /cancel", reply_markup=back_kb("ad:adm"))
            return await cq.answer()
        if act in ("ae", "ap", "adel"):
            target = int(parts[2])
            if target not in ADMINS or not can_edit_admin(uid, target):
                return await cq.answer("⛔️ Bu adminni o'zgartira olmaysiz.", show_alert=True)
            if act == "ap":
                perm = parts[3]
                if perm not in PERMS or (perm == "admins" and uid not in OWNER_IDS):
                    return await cq.answer("⛔️ 'Adminlarni boshqarish' huquqini faqat Owner bera oladi.",
                                           show_alert=True)
                if perm in ADMINS[target]:
                    ADMINS[target].discard(perm)
                else:
                    ADMINS[target].add(perm)
                save_admin(target)
            if act == "adel":
                ADMINS.pop(target, None)
                db.execute("DELETE FROM admins WHERE user_id=?", (target,))
                db.commit()
                await send(target, "ℹ️ Sizning adminlik huquqlaringiz olib tashlandi.")
                await cq.answer("🗑 Admin olib tashlandi")
            else:
                text, kbm = admin_edit_view(target)
                await safe_edit(msg, text, reply_markup=kbm)
                return await cq.answer()
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Admin qo'shish", callback_data="ad:aadd")
        for t in ADMINS:
            kb.button(text=f"🛡 {user_name(t)[:25]}", callback_data=f"ad:ae:{t}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:home")
        kb.adjust(1)
        owners = ", ".join(ulink(o) for o in OWNER_IDS) or "—"
        await safe_edit(msg, f"👑 <b>Adminlar</b>\n\nOwner: {owners}\nAdminlar soni: {len(ADMINS)}\n\n"
                             "Huquqini o'zgartirish uchun adminni tanlang:", reply_markup=kb.as_markup())
        if act == "adm":
            await cq.answer()
        return

    return await admin_cb_more(cq, uid, msg, parts, act)


# ── qo'shimcha admin bo'limlar: kanallar, iqtisod ──
def ch_view():
    main = (kv_get("main_channel", "") or "").strip() or "yo'q"
    text = (f"📢 <b>Kanallar va chatlar</b>\n\n📢 Asosiy kanal: <b>{esc(main)}</b>\n"
            f"🔒 Majburiy obuna kanallari: <b>{len(sub_channels())}</b>\n\n"
            "Asosiy kanal /start dan keyin tugma bo'lib chiqadi.")
    kb = InlineKeyboardBuilder()
    kb.button(text="📢 Asosiy kanalni o'rnatish", callback_data="ad:chmain")
    kb.button(text="🗑 Asosiy kanalni o'chirish", callback_data="ad:chmaindel")
    kb.button(text="🔒 Majburiy obuna", callback_data="ad:sub")
    kb.button(text="💬 Tasodifiy chat ro'yxati", callback_data="ad:chats")
    kb.button(text="⬅️ Orqaga", callback_data="ad:home")
    kb.adjust(1)
    return text, kb.as_markup()


def sub_view():
    chans = sub_channels()
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Kanal qo'shish", callback_data="ad:subadd")
    for ch in chans:
        kb.button(text=f"🗑 {ch['title'][:28]}", callback_data=f"ad:subdel:{ch['id']}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:ch")
    kb.adjust(1)
    lst = "\n".join(f"• {esc(c['title'])}" for c in chans) or "Hozircha yo'q."
    return (f"🔒 <b>Majburiy obuna</b>\n\n{lst}\n\nBot bu kanallarda <b>admin</b> bo'lishi shart — "
            "aks holda a'zolikni tekshira olmaydi."), kb.as_markup()


def chats_view():
    rows = db.execute("SELECT chat_id,title,members,games,hidden,bot_admin FROM chats WHERE username!='' "
                      "ORDER BY (games*5+members) DESC LIMIT 15").fetchall()
    kb = InlineKeyboardBuilder()
    lines = []
    for cid, title, mem, games, hidden, adm in rows:
        lines.append(f"{'🙈' if hidden else '👁'} {esc(title)} — 👥{mem} 🎮{games}" + ("" if adm else " (bot admin emas)"))
        kb.button(text=f"{'👁 Ko`rsatish' if hidden else '🙈 Yashirish'}: {title[:20]}", callback_data=f"ad:chhide:{cid}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:ch")
    kb.adjust(1)
    return ("💬 <b>Tasodifiy chat ro'yxati</b>\nFaqat ochiq (username'li) guruhlar, bot admin bo'lganlari "
            "chiqadi. Mashhurlik: o'yinlar va a'zolar soni.\n\n" + ("\n".join(lines) or "Hozircha yo'q.")), kb.as_markup()


def eco_view():
    q = lambda sql: db.execute(sql).fetchone()[0]
    text = (f"💰 <b>Iqtisod</b>\n\n⭐ Stars daromadi: <b>{q('SELECT COALESCE(SUM(stars),0) FROM payments WHERE refunded=0')}</b>\n"
            f"💎 Sotilgan olmos: {q('SELECT COALESCE(SUM(diamonds),0) FROM payments WHERE refunded=0')}\n"
            f"🧾 To'lovlar soni: {q('SELECT COUNT(*) FROM payments')}\n\n"
            "Stars botning balansiga tushadi (botni yaratgan akkaunt egasiga). To'lovlar ro'yxati: /payments")
    kb = InlineKeyboardBuilder()
    kb.button(text="💎 Olmos paketlari", callback_data="ad:packs")
    kb.button(text="🏪 Do'kon narxlari", callback_data="ad:shop")
    kb.button(text="🎁 Pul berish/olish", callback_data="ad:give:money")
    kb.button(text="💎 Olmos berish/olish", callback_data="ad:give:dia")
    kb.button(text="👑 Owner aura berish/olish", callback_data="ad:give:aura")
    kb.button(text="🏅 Unvon narxlari", callback_data="ad:tt")
    kb.button(text="🎁 Unvon berish/olish", callback_data="ad:tgive")
    kb.button(text="⚙️ Mukofot va narxlar", callback_data="ad:set")
    kb.button(text="⬅️ Orqaga", callback_data="ad:home")
    kb.adjust(1)
    return text, kb.as_markup()


def packs_view():
    lst = "\n".join(f"⭐ {a} → 💎 {b}" for a, b in get_packs())
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ O'zgartirish", callback_data="ad:packedit")
    kb.button(text="⬅️ Orqaga", callback_data="ad:eco")
    kb.adjust(1)
    return f"💎 <b>Olmos paketlari</b> (Stars → olmos)\n\n{lst}", kb.as_markup()


def shop_admin_view():
    kb = InlineKeyboardBuilder()
    lines = []
    for key, v in ITEMS.items():
        pr = item_price(key)
        name = v["name"]
        if key in ("xray", "megaboost") and pr <= 0:
            continue   # sotilmaydigan (Owner aura / eski inventar) narsalar ro'yxatda ko'rinmasin
        lines.append(f"{TIERS[v['tier']]} {name} — {pr}{CUR_SYM[v['cur']]}" if pr > 0 else f"{name} — ❌ o'chirilgan")
        kb.button(text=f"✏️ {name}", callback_data=f"ad:shopi:{key}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:eco")
    kb.adjust(1)
    return "🏪 <b>Do'kon narxlari</b>\nNarxni o'zgartirish uchun narsani tanlang (0 = sotuvdan olish).\n\n" + "\n".join(lines), kb.as_markup()


async def resolve_channel(m: Message) -> dict:
    fo = getattr(m, "forward_origin", None)
    fch = getattr(fo, "chat", None)
    if fch:
        ref = fch.id
    else:
        t = (m.text or "").strip()
        for pre in ("https://t.me/", "http://t.me/", "t.me/"):
            if t.startswith(pre):
                t = t[len(pre):]
        if t.lstrip("-").isdigit():
            ref = int(t)
        else:
            ref = "@" + t.lstrip("@").split("/")[0].split("?")[0]
    c = await bot.get_chat(ref)
    me = await bot.get_chat_member(c.id, bot.id)
    if me.status not in ("administrator", "creator"):
        raise ValueError("Bot bu kanalda admin emas. Avval botni kanalga admin qiling.")
    url = f"https://t.me/{c.username}" if c.username else ""
    if not url:
        try:
            url = await bot.export_chat_invite_link(c.id)
        except TelegramAPIError:
            raise ValueError("Kanal uchun havola olib bo'lmadi. Botga 'havola yaratish' huquqini bering.")
    return {"id": c.id, "title": c.title or str(c.id), "url": url}


def title_admin_view():
    kb = InlineKeyboardBuilder()
    lines = []
    for k, v in TITLES.items():
        lines.append(f"{v['name']} — {tprice(k)}⭐")
        kb.button(text=f"✏️ {v['name']}", callback_data=f"ad:tti:{k}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:eco")
    kb.adjust(1)
    return "🏅 <b>Unvon narxlari</b> (Stars)\nNarxni o'zgartirish uchun unvonni tanlang.\n\n" + "\n".join(lines), kb.as_markup()


def gif_view():
    kb = InlineKeyboardBuilder()
    lines = []
    for c, label in GIF_CATS.items():
        n = len(gif_list(c))
        lines.append(f"{label}: <b>{n}</b> ta")
        kb.button(text=f"{label} ({n})", callback_data=f"ad:gifc:{c}")
    kb.button(text="⬅️ Orqaga", callback_data="ad:home")
    kb.adjust(1)
    return ("🎞 <b>GIFlar</b>\n\nHar bo'lim uchun bir nechta GIF qo'shsangiz, o'yinda tasodifiy tanlanadi. "
            "GIF bo'lmasa, oddiy matn chiqadi.\n\n" + "\n".join(lines)), kb.as_markup()


async def admin_cb_more(cq: CallbackQuery, uid: int, msg: Message, parts: list, act: str):
    async def deny():
        await cq.answer("⛔️ Bu bo'lim uchun huquqingiz yo'q.", show_alert=True)

    # ── GIFlar
    if act in ("gif", "gifc", "gifadd", "gifclr"):
        if not has_perm(uid, "gifs"):
            return await deny()
        ADMIN_STATE.pop(uid, None)
        if act == "gif":
            text, kb = gif_view()
            await safe_edit(msg, text, reply_markup=kb)
            return await cq.answer()
        cat = parts[2] if len(parts) > 2 else ""
        if cat not in GIF_CATS:
            return await cq.answer()
        if act == "gifadd":
            ADMIN_STATE[uid] = {"k": "gif", "cat": cat}
            await safe_edit(msg, f"🎞 <b>{GIF_CATS[cat]}</b>\n\nGIF (animatsiya) yoki qisqa video yuboring. "
                                 "Bir nechtasini ketma-ket yuborishingiz mumkin.\nTugatish: /cancel",
                            reply_markup=back_kb(f"ad:gifc:{cat}"))
            return await cq.answer()
        if act == "gifclr":
            kv_set("gif_" + cat, "[]")
            await cq.answer("🗑 Tozalandi")
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ GIF qo'shish", callback_data=f"ad:gifadd:{cat}")
        kb.button(text="🗑 Hammasini o'chirish", callback_data=f"ad:gifclr:{cat}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:gif")
        kb.adjust(1)
        await safe_edit(msg, f"🎞 <b>{GIF_CATS[cat]}</b>\nHozir: <b>{len(gif_list(cat))}</b> ta GIF.", reply_markup=kb.as_markup())
        if act == "gifc":
            await cq.answer()
        return

    # ── unvonlar (admin)
    if act in ("tt", "tti", "tgive"):
        if not has_perm(uid, "economy"):
            return await deny()
        if act == "tti":
            key = parts[2]
            if key not in TITLES:
                return await cq.answer()
            ADMIN_STATE[uid] = {"k": "tprice", "key": key}
            await safe_edit(msg, f"{TITLES[key]['name']}\nHozirgi narx: <b>{tprice(key)}⭐</b>\n\n"
                                 "Yangi narxni (Stars) raqam bilan yuboring.\nBekor qilish: /cancel",
                            reply_markup=back_kb("ad:tt"))
            return await cq.answer()
        if act == "tgive":
            ADMIN_STATE[uid] = {"k": "tgive"}
            names = ", ".join(TITLES)
            await safe_edit(msg, "🎁 <code>ID unvon</code> ko'rinishida yuboring, masalan:\n"
                                 "<code>123456789 lord</code> — berish\n<code>123456789 -lord</code> — olib tashlash\n\n"
                                 f"Unvonlar: <code>{names}</code>\nBekor qilish: /cancel", reply_markup=back_kb("ad:eco"))
            return await cq.answer()
        text, kb = title_admin_view()
        await safe_edit(msg, text, reply_markup=kb)
        return await cq.answer()

    # ── kanallar
    if act in ("ch", "chmain", "chmaindel", "sub", "subadd", "subdel", "chats", "chhide"):
        if not has_perm(uid, "channels"):
            return await deny()
        if act == "chmain":
            ADMIN_STATE[uid] = {"k": "main_ch"}
            await safe_edit(msg, "📢 <b>Asosiy kanal</b>\n\n@username yoki havola yuboring, yoki kanaldan xabar "
                                 "forward qiling.\nBekor qilish: /cancel", reply_markup=back_kb("ad:ch"))
            return await cq.answer()
        if act == "chmaindel":
            kv_set("main_channel", "")
            await cq.answer("🗑 O'chirildi")
        if act == "subadd":
            ADMIN_STATE[uid] = {"k": "sub_add"}
            await safe_edit(msg, "🔒 Majburiy obuna kanalini yuboring: @username, havola, kanal ID yoki "
                                 "kanaldan xabar forward qiling.\n⚠️ Bot kanalda <b>admin</b> bo'lishi kerak.\n"
                                 "Bekor qilish: /cancel", reply_markup=back_kb("ad:sub"))
            return await cq.answer()
        if act == "subdel":
            cid = int(parts[2])
            kv_set("sub_channels", json.dumps([c for c in sub_channels() if c["id"] != cid]))
            SUB_CACHE.clear()
            await cq.answer("🗑 Olib tashlandi")
        if act == "chhide":
            db.execute("UPDATE chats SET hidden=1-hidden WHERE chat_id=?", (int(parts[2]),))
            db.commit()
        text, kb = {"ch": ch_view, "chmain": ch_view, "chmaindel": ch_view, "sub": sub_view, "subdel": sub_view,
                    "chats": chats_view, "chhide": chats_view}[act]()
        await safe_edit(msg, text, reply_markup=kb)
        if act in ("ch", "sub", "chats"):
            await cq.answer()
        return

    # ── iqtisod
    if act in ("eco", "packs", "packedit", "shop", "shopi", "give"):
        if not has_perm(uid, "economy"):
            return await deny()
        if act == "packedit":
            ADMIN_STATE[uid] = {"k": "packs"}
            await safe_edit(msg, "💎 Yangi paketlarni yuboring — har qatorda <code>STARS=OLMOS</code>:\n\n"
                                 "<code>10=5\n25=15\n50=35</code>\n\nEng ko'pi 8 ta. Bekor qilish: /cancel",
                            reply_markup=back_kb("ad:packs"))
            return await cq.answer()
        if act == "shopi":
            key = parts[2]
            if key not in ITEMS:
                return await cq.answer()
            ADMIN_STATE[uid] = {"k": "price", "item": key}
            await safe_edit(msg, f"{ITEMS[key]['name']}\nHozirgi narx: <b>{item_price(key)}</b>{CUR_SYM[ITEMS[key]['cur']]}\n\n"
                                 "Yangi narxni raqam bilan yuboring (0 = sotuvdan olish).\nBekor qilish: /cancel",
                            reply_markup=back_kb("ad:shop"))
            return await cq.answer()
        if act == "give":
            cur = parts[2]
            ADMIN_STATE[uid] = {"k": "give", "cur": cur}
            if cur == "aura" and uid not in OWNER_IDS:
                return await cq.answer("Owner aurani faqat owner bera oladi.", show_alert=True)
            name = {"money": "💵 pul", "aura": "👑 Owner aura"}.get(cur, "💎 olmos")
            if cur == "aura":
                hint = ("<code>123456789 1</code> — aura berish\n<code>123456789 0</code> — auradan mahrum qilish\n")
            else:
                hint = ("<code>123456789 500</code> — qo'shish\n<code>123456789 -100</code> — ayirish\n")
            await safe_edit(msg, f"🎁 {name} berish/olish\n\n<code>ID MIQDOR</code> ko'rinishida yuboring, masalan:\n"
                                 + hint + "Bekor qilish: /cancel", reply_markup=back_kb("ad:eco"))
            return await cq.answer()
        text, kb = {"eco": eco_view, "packs": packs_view, "shop": shop_admin_view}[act]()
        await safe_edit(msg, text, reply_markup=kb)
        return await cq.answer()

    await cq.answer()


async def admin_input_more(m: Message, uid: int, st: dict, k: str) -> bool:
    """Yangi holatlar uchun kirish. True qaytarsa — xabar qayta ishlangan."""
    if k in ("main_ch", "sub_add"):
        if not has_perm(uid, "channels"):
            return True
        if k == "main_ch":
            fo = getattr(m, "forward_origin", None)
            fch = getattr(fo, "chat", None)
            val = ("@" + fch.username) if (fch and getattr(fch, "username", None)) else (m.text or "").strip()
            if not (val.startswith("@") or val.startswith("http")):
                await m.answer("❌ @username yoki https:// havola yuboring (yoki ochiq kanaldan forward qiling).")
                return True
            kv_set("main_channel", val)
            ADMIN_STATE.pop(uid, None)
            await m.answer(f"✅ Asosiy kanal o'rnatildi: {esc(val)}", reply_markup=back_kb("ad:ch"))
            return True
        try:
            ch = await resolve_channel(m)
        except (TelegramAPIError, ValueError) as e:
            await m.answer(f"❌ {esc(str(e))}\nQayta yuboring yoki /cancel.")
            return True
        chans = [c for c in sub_channels() if c["id"] != ch["id"]] + [ch]
        kv_set("sub_channels", json.dumps(chans))
        SUB_CACHE.clear()
        ADMIN_STATE.pop(uid, None)
        await m.answer(f"✅ Majburiy obunaga qo'shildi: <b>{esc(ch['title'])}</b>", reply_markup=back_kb("ad:sub"))
        return True

    if k == "gif":
        if not has_perm(uid, "gifs"):
            return True
        if m.animation:
            item = "a:" + m.animation.file_id
        elif m.video:
            item = "v:" + m.video.file_id
        else:
            await m.answer("❌ GIF (animatsiya) yoki video yuboring. Tugatish: /cancel")
            return True
        lst = gif_list(st["cat"])
        if len(lst) >= 20:
            await m.answer("❌ Bir bo'limda ko'pi bilan 20 ta GIF bo'lishi mumkin.")
            return True
        lst.append(item)
        kv_set("gif_" + st["cat"], json.dumps(lst))
        await m.answer(f"✅ Saqlandi ({GIF_CATS[st['cat']]}): jami <b>{len(lst)}</b> ta. Yana yuboring yoki /cancel.")
        return True

    if k in ("tprice", "tgive"):
        if not has_perm(uid, "economy"):
            return True
        t = (m.text or "").strip()
        if k == "tprice":
            if not t.isdigit() or not (1 <= int(t) <= 100000):
                await m.answer("❌ 1 dan 100000 gacha raqam yuboring.")
                return True
            kv_set("tprice_" + st["key"], int(t))
            ADMIN_STATE.pop(uid, None)
            text, kb = title_admin_view()
            await m.answer("✅ Saqlandi!\n\n" + text, reply_markup=kb)
            return True
        bits = t.split()
        if len(bits) != 2 or not bits[0].isdigit():
            await m.answer("❌ Format: <code>ID unvon</code> (masalan: <code>123456789 lord</code>).")
            return True
        target, key = int(bits[0]), bits[1].lower()
        remove = key.startswith("-")
        key = key.lstrip("-")
        if key not in TITLES:
            await m.answer("❌ Unvon topilmadi: " + ", ".join(TITLES))
            return True
        ADMIN_STATE.pop(uid, None)
        if remove:
            revoke_title(target, key)
            await m.answer(f"🗑 {ulink(target)} dan {TITLES[key]['name']} olib tashlandi.", reply_markup=back_kb("ad:eco"))
        else:
            grant_title(target, key)
            await m.answer(f"✅ {ulink(target)} ga {TITLES[key]['name']} berildi.", reply_markup=back_kb("ad:eco"))
            await send(target, f"🎁 Admin sizga <b>{TITLES[key]['name']}</b> unvonini berdi!")
        return True

    if k in ("packs", "price", "give"):
        if not has_perm(uid, "economy"):
            return True
        t = (m.text or "").strip()
        if k == "packs":
            packs = []
            for line in t.splitlines():
                bits = [x for x in re.split(r"[=:\s]+", line.strip()) if x]
                if len(bits) != 2 or not all(x.isdigit() for x in bits):
                    await m.answer("❌ Format noto'g'ri. Har qatorda <code>STARS=OLMOS</code> bo'lsin.")
                    return True
                a, b = int(bits[0]), int(bits[1])
                if not (1 <= a <= 10000 and 1 <= b <= 1_000_000):
                    await m.answer("❌ Stars 1–10000, olmos 1–1 000 000 oralig'ida bo'lishi kerak.")
                    return True
                packs.append([a, b])
            if not packs or len(packs) > 8:
                await m.answer("❌ 1 tadan 8 tagacha paket bo'lishi kerak.")
                return True
            kv_set("packs", json.dumps(packs))
            ADMIN_STATE.pop(uid, None)
            text, kb = packs_view()
            await m.answer("✅ Saqlandi!\n\n" + text, reply_markup=kb)
            return True
        if k == "price":
            if not t.isdigit() or int(t) > 1_000_000:
                await m.answer("❌ 0 dan 1 000 000 gacha raqam yuboring.")
                return True
            kv_set("price_" + st["item"], int(t))
            ADMIN_STATE.pop(uid, None)
            text, kb = shop_admin_view()
            await m.answer("✅ Saqlandi!\n\n" + text, reply_markup=kb)
            return True
        # give
        bits = t.replace(",", " ").split()
        if len(bits) != 2 or not bits[1].lstrip("+-").isdigit():
            await m.answer("❌ Format: <code>ID MIQDOR</code> yoki <code>@username MIQDOR</code> "
                           "(masalan: <code>123456789 500</code>).")
            return True
        if bits[0].startswith("@"):
            target = find_user_by_username(bits[0])
            if not target:
                await m.answer("❌ Bu @username bo'yicha foydalanuvchi bazada yo'q. Raqamli ID yuboring.")
                return True
        elif bits[0].lstrip("-").isdigit():
            target = int(bits[0])
        else:
            await m.answer("❌ ID raqam bo'lishi yoki @username bo'lishi kerak.")
            return True
        amount = int(bits[1])
        known = bool(db.execute("SELECT 1 FROM users WHERE user_id=?", (target,)).fetchone())
        if abs(amount) > 1_000_000_000_000:
            await m.answer("❌ Miqdor juda katta.")
            return True
        if st["cur"] == "aura":
            if uid not in OWNER_IDS:
                return True
            ensure_user(target)
            ADMIN_STATE.pop(uid, None)
            if amount > 0:
                if inv_qty(target, "fx_owner") <= 0:
                    inv_add(target, "fx_owner", 1)
                kv_set(f"fx_{target}", "fx_owner")
                await m.answer(f"✅ {ulink(target)} (<code>{target}</code>) ga 👑 Owner aura berildi.",
                               reply_markup=back_kb("ad:eco"))
                await send(target, "👑 Sizga <b>Owner aura</b> berildi. Yoqish: Do'kon → Narsalarim → Effektlarim.")
            else:
                db.execute("UPDATE inv SET qty=0 WHERE user_id=? AND item='fx_owner'", (target,))
                db.commit()
                if kv_get(f"fx_{target}") == "fx_owner":
                    kv_set(f"fx_{target}", "")
                await m.answer(f"✅ {ulink(target)} (<code>{target}</code>) dan Owner aura olib tashlandi.",
                               reply_markup=back_kb("ad:eco"))
            return True
        if st["cur"] == "money":
            add_money(target, amount)
            what = "💵"
        else:
            add_dia(target, amount)
            what = "💎"
        ADMIN_STATE.pop(uid, None)
        mny, dia = get_bal(target)
        await m.answer(f"✅ {ulink(target)} (<code>{target}</code>): {amount:+d}{what}\nHozirgi balans: 💵 {mny} · 💎 {dia}"
                       + ("" if known else "\nℹ️ Bu ID botda hali yo'q edi — hisob ochildi, u botga kirgach pul o'z joyida bo'ladi."),
                       reply_markup=back_kb("ad:eco"))
        if amount > 0:
            await send(target, f"🎁 Admin sizga <b>+{amount}</b>{what} berdi!")
        return True

    return False


def has_state(m: Message) -> bool:
    return m.from_user is not None and m.from_user.id in ADMIN_STATE


@router.message(F.chat.type == "private", has_state)
async def admin_input(m: Message):
    uid = m.from_user.id
    st = ADMIN_STATE.get(uid)
    if not st or not is_panel_user(uid):
        ADMIN_STATE.pop(uid, None)
        return
    k = st["k"]
    if await admin_input_more(m, uid, st, k):
        return

    if k == "bc":
        if not has_perm(uid, "broadcast"):
            return
        n_users = db.execute("SELECT COUNT(*) FROM users WHERE started=1 AND banned=0").fetchone()[0]
        n_chats = db.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
        ADMIN_STATE[uid] = {"k": "bc_confirm", "chat": m.chat.id, "mid": m.message_id}
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Yuborish", callback_data="ad:bcgo")
        kb.button(text="❌ Bekor qilish", callback_data="ad:cancel")
        await m.answer(f"📢 Shu xabar <b>{n_users}</b> ta foydalanuvchi va <b>{n_chats}</b> ta guruhga "
                       "yuboriladi. Tasdiqlaysizmi?", reply_markup=kb.as_markup())
        return

    if k == "bc_confirm":
        await m.answer("Yuqoridagi tugmalardan birini tanlang yoki /cancel bosing.")
        return

    if k == "set":
        if not has_perm(uid, "settings"):
            return
        t = (m.text or "").strip()
        key = st["key"]
        if not t.isdigit() or not setting_ok(key, int(t)):
            await m.answer("❌ Noto'g'ri qiymat. Vaqt 1–86400 soniya, minimal o'yinchi 4–60, maksimal o'yinchi 4–60, "
                           "pul/olmos qiymatlari 0–1 000 000 (qayta tug'ilish 1–100) oralig'ida bo'lishi kerak. "
                           "Qayta yuboring yoki /cancel.")
            return
        globals()[key] = int(t)
        kv_set(key, int(t))
        ADMIN_STATE.pop(uid, None)
        await m.answer(f"✅ {SETTING_LABELS[key]} → <b>{t}</b>", reply_markup=back_kb("ad:set"))
        return

    target = parse_id(m)
    if target is None:
        await m.answer("❌ ID topilmadi. Raqamli ID yuboring yoki foydalanuvchidan xabar forward qiling. "
                       "(Bekor qilish: /cancel)")
        return

    if k == "find":
        if not has_perm(uid, "stats"):
            return
        ADMIN_STATE.pop(uid, None)
        await m.answer(user_info_text(target), reply_markup=back_kb())

    elif k == "ban":
        if not has_perm(uid, "ban"):
            return
        if target in OWNER_IDS or (target in ADMINS and uid not in OWNER_IDS):
            await m.answer("⛔️ Bu foydalanuvchini bloklay olmaysiz.")
            return
        ADMIN_STATE.pop(uid, None)
        flag = target not in BANNED
        set_ban(target, flag)
        await m.answer(("🚫 Bloklandi: " if flag else "✅ Blokdan chiqarildi: ") + f"<code>{target}</code>",
                       reply_markup=back_kb("ad:ban"))

    elif k == "vip_id":
        if not has_perm(uid, "vip"):
            return
        ADMIN_STATE.pop(uid, None)
        kb = InlineKeyboardBuilder()
        for label, days in (("7 kun", 7), ("30 kun", 30), ("90 kun", 90), ("♾ Umrbod", 0)):
            kb.button(text=label, callback_data=f"ad:vipd:{target}:{days}")
        kb.button(text="⬅️ Orqaga", callback_data="ad:vip")
        kb.adjust(2, 2, 1)
        await m.answer(f"⭐ <code>{target}</code> ga VIP qancha muddatga beriladi?", reply_markup=kb.as_markup())

    elif k == "adm_add":
        if not has_perm(uid, "admins"):
            return
        if target in OWNER_IDS:
            await m.answer("ℹ️ Bu foydalanuvchi Owner — unda allaqachon barcha huquqlar bor.")
            return
        ADMIN_STATE.pop(uid, None)
        ADMINS.setdefault(target, set())
        save_admin(target)
        await send(target, "🛡 Siz botda <b>admin</b> etib tayinlandingiz! Panelni ochish: /admin")
        text, kbm = admin_edit_view(target)
        await m.answer("✅ Admin qo'shildi!\n\n" + text, reply_markup=kbm)


# ───────────────────────── CHAT NAZORATI ─────────────────────────
@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def mafia_relay(m: Message):
    """Tunda mafiya a'zolarining xabarlarini o'zaro uzatish."""
    cid = USER_GAME.get(m.from_user.id)
    g = GAMES.get(cid) if cid else None
    if not g or g.state != "night":
        return
    p = g.players.get(m.from_user.id)
    if not p or not p.alive or team(p.role) != "mafia":
        return
    for t in g.alive():
        if team(t.role) == "mafia" and t.id != p.id:
            await send(t.id, f"💬 <b>{esc(p.name)}</b>: {esc(m.text)}")


@router.message(Command("ping"))
async def cmd_ping(m: Message):
    """Faqat egalar: Telegram va baza tezligini o'lchaydi."""
    if m.from_user.id not in OWNER_IDS:
        return
    t0 = time.perf_counter()
    kv_set("ping_test", int(time.time()))
    db_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    sent = await m.answer("🏓 O'lchanmoqda...")
    api_ms = (time.perf_counter() - t1) * 1000
    t2 = time.perf_counter()
    miss = await missing_channels(m.from_user.id) if sub_channels() else []
    sub_ms = (time.perf_counter() - t2) * 1000
    try:
        await sent.edit_text(
            f"🏓 <b>Tezlik</b>\n\n📡 Telegram javobi: <b>{api_ms:.0f}</b> ms\n"
            f"💾 Baza yozish: <b>{db_ms:.0f}</b> ms\n"
            f"🔒 Obuna tekshiruvi: <b>{sub_ms:.0f}</b> ms ({len(sub_channels())} kanal)\n\n"
            "Telegram 700 ms dan oshsa — internet/ulanish sekin.\n"
            "Baza 100 ms dan oshsa — fayl sekin diskda (masalan OneDrive'li Desktop).")
    except TelegramAPIError:
        pass


@router.message(Command("id", "myid"))
async def cmd_id(m: Message):
    uid = m.from_user.id
    st = "👑 Owner" if uid in OWNER_IDS else ("🛡 Admin" if uid in ADMINS else "oddiy foydalanuvchi")
    hint = ""
    if uid not in OWNER_IDS and uid not in ADMINS:
        hint = "\n\nAdmin bo'lish uchun Render'dagi <code>OWNER_ID</code> o'zgaruvchisiga shu ID ni yozing va botni qayta ishga tushiring."
    await m.answer(f"🆔 Sizning ID: <code>{uid}</code>\nBot sizni shunday ko'radi: <b>{st}</b>{hint}")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_guard(m: Message):
    """O'yin vaqtida o'lganlar/tashqaridagilar va tunda hamma xabarlari o'chiriladi."""
    g = GAMES.get(m.chat.id)
    if not g or g.state in ("reg",) or m.from_user is None:
        return
    p = g.players.get(m.from_user.id)
    if g.state in ("night", "resolving") or not p or not p.alive:
        try:
            await m.delete()
        except TelegramAPIError:
            pass


@router.callback_query()
async def stale_cb(cq: CallbackQuery):
    """Hech qaysi ishlovchiga tushmagan (eskirgan) tugmalar — aylanib turmasligi uchun javob beramiz."""
    log.info("Noma'lum tugma: %s", cq.data)
    await cq.answer("Bu tugma eskirgan. /start ni bosing.")


async def on_error(event: ErrorEvent):
    log.error("❌ Ishlovchida xato: %r", event.exception, exc_info=event.exception)
    try:
        cb = event.update.callback_query
        if cb:
            await cb.answer("⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.", show_alert=True)
    except Exception:
        pass
    return True


# ───────────────────────── ISHGA TUSHIRISH ─────────────────────────
async def on_startup(bot: Bot):
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
    if BASE_URL:
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text="🌐 Ochish", web_app=WebAppInfo(url=BASE_URL + "/app")))
        except Exception as e:
            log.warning("Menyu tugmasi o'rnatilmadi: %s", e)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Menyu"),
            BotCommand(command="roles", description="Rollar ro'yxati"),
            BotCommand(command="rules", description="Qoidalar"),
            BotCommand(command="top", description="Reyting"),
            BotCommand(command="profile", description="Profilim"),
            BotCommand(command="shop", description="Do'kon"),
            BotCommand(command="wallet", description="Hamyon"),
            BotCommand(command="bonus", description="Kunlik bonus"),
            BotCommand(command="id", description="Mening ID raqamim"),
        ], scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands([
            BotCommand(command="game", description="O'yinni boshlash"),
            BotCommand(command="join", description="O'yinga qo'shilish"),
            BotCommand(command="leave", description="Ro'yxatdan chiqish"),
            BotCommand(command="begin", description="Hoziroq boshlash"),
            BotCommand(command="st", description="O'yinni boshlash (admin)"),
            BotCommand(command="vaqtsiz", description="Ro'yxat vaqtini o'chirish/yoqish"),
            BotCommand(command="extend", description="Vaqtni uzaytirish"),
            BotCommand(command="players", description="O'yinchilar"),
            BotCommand(command="stop", description="O'yinni to'xtatish"),
            BotCommand(command="menu", description="Menyu"),
            BotCommand(command="roles", description="Rollar"),
            BotCommand(command="rules", description="Qoidalar"),
            BotCommand(command="top", description="Reyting"),
            BotCommand(command="profile", description="Profil"),
            BotCommand(command="pay", description="Pul o'tkazish (reply)"),
            BotCommand(command="sovga", description="Sovga tashlash"),
        ], scope=BotCommandScopeAllGroupChats())
        from aiogram.types import BotCommandScopeChat
        for oid in OWNER_IDS:
            try:
                await bot.set_my_commands([
                    BotCommand(command="admin", description="Admin panel"),
                    BotCommand(command="start", description="Menyu"),
                    BotCommand(command="roles", description="Rollar ro'yxati"),
                    BotCommand(command="rules", description="Qoidalar"),
                    BotCommand(command="top", description="Reyting"),
                    BotCommand(command="me", description="Mening statistikam"),
                ], scope=BotCommandScopeChat(chat_id=oid))
            except TelegramAPIError:
                pass
    except Exception as e:  # buyruqlar o'rnatilmasa ham bot ishlayveradi
        log.warning("Buyruqlar menyusini o'rnatib bo'lmadi: %s", e)
    try:
        await refund_open_drops()
    except Exception:
        log.exception("sovgalarni qaytarishda xato")
    spawn(stats_loop())
    spawn(backup_loop())
    t0 = time.perf_counter()
    kv_set("ping_test", int(time.time()))
    db_ms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    await bot.get_me()
    api_ms = (time.perf_counter() - t1) * 1000
    log.info("Bot ishga tushdi: @%s | Ownerlar: %s | Telegram: %.0f ms | Baza: %.0f ms",
             BOT_USERNAME, sorted(OWNER_IDS), api_ms, db_ms)
    if api_ms > 700:
        log.warning("⚠️ Telegram javobi sekin (%.0f ms) — internet ulanishini tekshiring.", api_ms)
    if db_ms > 100:
        log.warning("⚠️ Baza yozishi sekin (%.0f ms) — botni OneDrive'siz papkaga ko'chiring.", db_ms)


LAST_DESC = ""


async def stats_loop():
    """Bot profilidagi qisqa tavsifni (owner va guruh) o'rnatib turadi."""
    global LAST_DESC
    await asyncio.sleep(20)
    while True:
        try:
            desc = os.getenv("BOT_BIO", "Owner: @arifjanov09 | My group: @mafia_zone_uz")
            if desc != LAST_DESC:
                await bot.set_my_short_description(short_description=desc[:120])
                LAST_DESC = desc
        except Exception as e:
            log.warning("Qisqa tavsifni yangilab bo'lmadi: %s", e)
        await asyncio.sleep(6 * 3600)


# ───────────────────────── 🌐 MINI APP (sayt) ─────────────────────────
def verify_init(init: str):
    """Telegram WebApp initData imzosini tekshiradi; to'g'ri bo'lsa foydalanuvchi dict qaytaradi."""
    try:
        data = dict(urllib.parse.parse_qsl(init or "", keep_blank_values=True))
        h = data.pop("hash", "")
        chk = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if not h or not hmac.compare_digest(hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest(), h):
            return None
        if time.time() - int(data.get("auth_date", "0")) > 86400:
            return None
        return json.loads(data["user"])
    except Exception:
        return None


def app_state(uid: int, name: str) -> dict:
    ensure_user(uid)
    row = db.execute("SELECT games,wins FROM stats WHERE user_id=?", (uid,)).fetchone()
    games, wins = row if row else (0, 0)
    mny, dia = get_bal(uid)
    items = []
    for k, it in ITEMS.items():
        pr = item_price(k)
        if pr <= 0 or k == "active" or it.get("vip"):
            continue
        items.append({"key": k, "name": it["name"], "desc": it["desc"], "cur": it["cur"], "price": pr,
                      "qty": inv_qty(uid, k) if "grants" not in it else 0})
    act = fx_active(uid)
    fxs = []
    for k, v in FX.items():
        pr = fx_price(k)
        own = fx_has(uid, k)
        if (pr <= 0 and not own) or (k == "fx_owner" and not own):
            continue
        fxs.append({"key": k, "name": v["name"], "desc": v["desc"], "cur": v["cur"], "price": pr,
                    "vip": bool(v["vip"]), "owned": own, "active": act == k})
    role = "Owner" if uid in OWNER_IDS else "Admin" if uid in ADMINS else "VIP" if is_vip(uid) else "O'yinchi"
    return {"id": uid, "name": name, "role": role, "games": games, "wins": wins,
            "rate": (wins * 100 // games) if games else 0, "money": mny, "dia": dia,
            "items": items, "fx": fxs, "vip": is_vip(uid)}


async def _api_user(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    u = verify_init(body.get("init", ""))
    if not u or "id" not in u:
        raise web.HTTPUnauthorized(text="auth")
    if u["id"] in BANNED:
        raise web.HTTPForbidden(text="banned")
    return u, body


async def api_me(request):
    u, _ = await _api_user(request)
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or "Foydalanuvchi"
    return web.json_response(app_state(u["id"], name))


async def api_act(request):
    u, b = await _api_user(request)
    uid = u["id"]
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or "Foydalanuvchi"
    act, key = b.get("act"), str(b.get("key", ""))
    msg = ""
    ok = True
    if act == "buy":
        it = ITEMS.get(key)
        pr = item_price(key) if it else 0
        if not it or pr <= 0 or key == "active" or it.get("vip"):
            ok, msg = False, "Bu narsa sotilmaydi"
        elif not spend(uid, CUR_COL[it["cur"]], pr):
            ok, msg = False, f"{CUR_SYM[it['cur']]} yetarli emas"
        else:
            for gk, gq in (it.get("grants") or {key: 1}).items():
                inv_add(uid, gk, gq)
            msg = f"Sotib olindi: {it['name']}"
    elif act == "fxbuy":
        fx = FX.get(key)
        pr = fx_price(key) if fx else 0
        if not fx or pr <= 0:
            ok, msg = False, "Bu aura sotilmaydi"
        elif fx["vip"] and not is_vip(uid):
            ok, msg = False, "Bu aura faqat VIP uchun"
        elif inv_qty(uid, key) > 0:
            ok, msg = False, "Bu aura sizda bor"
        elif not spend(uid, CUR_COL[fx["cur"]], pr):
            ok, msg = False, f"{CUR_SYM[fx['cur']]} yetarli emas"
        else:
            inv_add(uid, key, 1)
            kv_set(f"fx_{uid}", key)
            msg = f"{fx['name']} yoqildi"
    elif act == "fxtoggle":
        if key in FX and fx_has(uid, key):
            if fx_active(uid) == key:
                kv_set(f"fx_{uid}", "")
                msg = "Aura o'chirildi"
            else:
                kv_set(f"fx_{uid}", key)
                msg = "Aura yoqildi"
        else:
            ok, msg = False, "Bu aura sizda yo'q"
    elif act == "bonus":
        ok, msg = False, "Kunlik bonus: botda /bonus"
    else:
        ok, msg = False, "Noma'lum amal"
    return web.json_response({"ok": ok, "msg": msg, "state": app_state(uid, name)})


APP_HTML = """<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Mafia</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:var(--tg-theme-bg-color,#0f1218);--tx:var(--tg-theme-text-color,#eef1f6);--hint:var(--tg-theme-hint-color,#8a93a3);
--card:var(--tg-theme-secondary-bg-color,#181d27);--btn:var(--tg-theme-button-color,#3b82f6);--btx:var(--tg-theme-button-text-color,#fff)}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;padding-bottom:84px}
.top{padding:22px 16px 10px;text-align:center}
.av{width:68px;height:68px;border-radius:50%;background:linear-gradient(135deg,#ef4444,#7c2d12);display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:700;margin:0 auto 8px}
.nm{font-size:19px;font-weight:700}.rl{color:var(--hint);font-size:13px}
.bal{display:flex;gap:10px;padding:8px 16px}.bal div{flex:1;background:var(--card);border-radius:14px;padding:12px;text-align:center}
.bal b{display:block;font-size:20px}.bal span{color:var(--hint);font-size:12px}
.sec{padding:6px 16px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.st{background:var(--card);border-radius:14px;padding:12px 6px;text-align:center}.st b{display:block;font-size:18px}.st span{color:var(--hint);font-size:12px}
.card{background:var(--card);border-radius:14px;padding:12px 14px;margin:8px 0;display:flex;gap:10px;align-items:center}
.card .in{flex:1;min-width:0}.card .t{font-weight:600}.card .d{color:var(--hint);font-size:12.5px;margin-top:2px}
button{border:0;border-radius:10px;padding:9px 14px;font:600 14px inherit;font-family:inherit;color:var(--btx);background:var(--btn);white-space:nowrap}
button.g{background:#16a34a}button.o{background:transparent;color:var(--hint);border:1px solid var(--hint)}button.r{background:#dc2626}
button:disabled{opacity:.45}
.tabs{position:fixed;bottom:0;left:0;right:0;display:flex;background:var(--card);padding:8px 8px calc(8px + env(safe-area-inset-bottom));gap:6px;border-top:1px solid rgba(128,128,128,.2)}
.tabs a{flex:1;text-align:center;padding:9px 0;border-radius:12px;color:var(--hint);font-weight:600;font-size:13px}
.tabs a.on{background:var(--btn);color:var(--btx)}
h3{margin:14px 0 4px;font-size:14px;color:var(--hint);text-transform:uppercase;letter-spacing:.04em}
#toast{position:fixed;top:14px;left:50%;transform:translateX(-50%);background:#111;color:#fff;padding:10px 16px;border-radius:12px;opacity:0;transition:.25s;pointer-events:none;max-width:90%;text-align:center}
#toast.on{opacity:1}.pg{display:none}.pg.on{display:block}
</style></head><body>
<div id="toast"></div>
<div class="top"><div class="av" id="av">?</div><div class="nm" id="nm">...</div><div class="rl" id="rl"></div></div>
<div class="bal"><div><b id="mn">0</b><span>💵 Pul</span></div><div><b id="dm">0</b><span>💎 Olmos</span></div></div>
<div id="p-me" class="pg on sec"><h3>Statistika</h3><div class="grid">
<div class="st"><b id="gm">0</b><span>O'yin</span></div><div class="st"><b id="wn">0</b><span>G'alaba</span></div><div class="st"><b id="rt">0%</b><span>Foiz</span></div></div>
<h3>Narsalarim</h3><div id="inv"></div></div>
<div id="p-shop" class="pg sec"><h3>Narsalar</h3><div id="shop"></div></div>
<div id="p-fx" class="pg sec"><h3>Auralar</h3><div id="fx"></div></div>
<div class="tabs"><a class="on" data-p="me">👤 Profil</a><a data-p="shop">🛒 Do'kon</a><a data-p="fx">✨ Auralar</a></div>
<script>
const tg=window.Telegram&&Telegram.WebApp;if(tg){tg.ready();tg.expand();}
const init=tg?tg.initData:"";let S=null;
const $=i=>document.getElementById(i);
function toast(t){const e=$('toast');e.textContent=t;e.classList.add('on');setTimeout(()=>e.classList.remove('on'),2200)}
async function call(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({init},body||{}))});
 if(!r.ok)throw new Error(r.status);return r.json()}
const sym=c=>c==='dia'?'💎':'💵';
function el(tag,cls,txt){const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e}
function row(t,d,btn){const c=el('div','card'),i=el('div','in');i.append(el('div','t',t),el('div','d',d));c.append(i);if(btn)c.append(btn);return c}
function b(txt,cls,fn){const x=el('button',cls,txt);x.onclick=async()=>{x.disabled=true;await fn();x.disabled=false};return x}
async function act(a,key){try{const r=await call('/api/act',{act:a,key});toast(r.msg);if(r.ok&&tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred('success');S=r.state;render()}catch(e){toast('Xatolik, qayta urining')}}
function render(){
 $('av').textContent=(S.name||'?')[0].toUpperCase();$('nm').textContent=S.name;$('rl').textContent=S.role+' · ID '+S.id;
 $('mn').textContent=S.money;$('dm').textContent=S.dia;$('gm').textContent=S.games;$('wn').textContent=S.wins;$('rt').textContent=S.rate+'%';
 const inv=$('inv');inv.textContent='';const have=S.items.filter(x=>x.qty>0);
 if(!have.length)inv.append(el('div','d','Hozircha narsa yo\\'q. Do\\'kondan oling.'));
 have.forEach(x=>inv.append(row(x.name+' ×'+x.qty,x.desc)));
 const sh=$('shop');sh.textContent='';
 S.items.forEach(x=>sh.append(row(x.name,x.desc,b(x.price+' '+sym(x.cur),'',()=>act('buy',x.key)))));
 const fx=$('fx');fx.textContent='';
 S.fx.forEach(x=>{let btn;
  if(x.owned)btn=b(x.active?'O\\'chirish':'Yoqish',x.active?'o':'g',()=>act('fxtoggle',x.key));
  else btn=b(x.price+' '+sym(x.cur),'',()=>act('fxbuy',x.key));
  fx.append(row(x.name+(x.vip?' · VIP':''),x.desc,btn))});
}
document.querySelectorAll('.tabs a').forEach(a=>a.onclick=()=>{document.querySelectorAll('.tabs a').forEach(z=>z.classList.remove('on'));a.classList.add('on');
 document.querySelectorAll('.pg').forEach(p=>p.classList.remove('on'));$('p-'+a.dataset.p).classList.add('on')});
call('/api/me').then(s=>{S=s;render()}).catch(()=>{$('nm').textContent='Botdan oching';$('rl').textContent='Bu sahifa faqat Telegram ichida ishlaydi'});
</script></body></html>"""


async def app_page(_request):
    return web.Response(text=APP_HTML, content_type="text/html")


def register_web(app):
    app.router.add_get("/app", app_page)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/act", api_act)


async def health(_request):
    return web.Response(text="Mafia bot ishlayapti ✅")


def load_state():
    for uid, perms in db.execute("SELECT user_id,perms FROM admins"):
        ADMINS[uid] = {x for x in (perms or "").split(",") if x}
    for uid, until in db.execute("SELECT user_id,vip_until FROM users WHERE vip=1"):
        VIPS[uid] = until
    for (uid,) in db.execute("SELECT user_id FROM users WHERE banned=1"):
        BANNED.add(uid)
    load_titles()
    for key in SETTING_LABELS:
        v = kv_get(key)
        if v and v.lstrip("-").isdigit():
            globals()[key] = int(v)
    globals()["MIN_PLAYERS"] = max(4, min(60, MIN_PLAYERS))   # o'yinchilar: 4..60
    globals()["MAX_PLAYERS"] = max(MIN_PLAYERS, min(60, MAX_PLAYERS))
    if not OWNER_IDS:
        log.warning("⚠️ OWNER_ID ga haqiqiy Telegram ID yozilmagan — admin panel hech kimga ochilmaydi!")


async def keepalive_loop():
    """Render bepul tarifida servis 15 daqiqa so'rovsiz qolsa uxlaydi — o'zini chaqirib turamiz."""
    await asyncio.sleep(90)
    while True:
        try:
            async with ClientSession(timeout=ClientTimeout(total=25)) as s:
                async with s.get(BASE_URL + "/") as r:
                    await r.read()
        except Exception as e:
            log.debug("keepalive xato: %s", e)
        await asyncio.sleep(540)


def main():
    load_state()
    dp.include_router(router)
    try:
        dp.errors.register(on_error)
    except Exception:  # eski versiyalar uchun
        log.warning("Xato ushlagichni ulab bo'lmadi")
    dp.startup.register(on_startup)

    if BASE_URL:  # Render: webhook rejimi
        secret = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:32]
        path = "/webhook"
        app = web.Application()
        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        register_web(app)
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=path)
        setup_application(app, dp, bot=bot)

        async def set_hook(_app):
            for attempt in range(1, 6):
                try:
                    await bot.set_webhook(
                        f"{BASE_URL}{path}", secret_token=secret, drop_pending_updates=True,
                        allowed_updates=dp.resolve_used_update_types(),
                    )
                    log.info("Webhook o'rnatildi: %s%s", BASE_URL, path)
                    break
                except Exception as e:
                    log.error("Webhook o'rnatilmadi (urinish %d/5): %s", attempt, e)
                    if attempt == 5:
                        raise
                    await asyncio.sleep(5)
            if KEEPALIVE:
                spawn(keepalive_loop())

        app.on_startup.append(set_hook)
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:  # lokal yoki USE_POLLING=1: polling rejimi
        async def run_polling():
            await bot.delete_webhook(drop_pending_updates=True)
            app = web.Application()
            app.router.add_get("/", health)
            app.router.add_get("/health", health)
            register_web(app)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", PORT).start()
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            finally:
                await runner.cleanup()
                await bot.session.close()

        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
