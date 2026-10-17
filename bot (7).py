# -*- coding: utf-8 -*-
"""
🤵🏻 MAFIA BOT — Telegram (aiogram 3.x)
- 16 ta rol, tun/kun/ovoz berish, DM orqali tungi harakatlar
- Shaxsiy chatda ham, guruhda ham menyu
- Render uchun tayyor (webhook yoki polling, avtomatik)

"""
import asyncio
import hashlib
import html
import json
import logging
import os
import random
import re
import sqlite3
import time
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
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import ClientSession, ClientTimeout, web

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

# Token va owner ID faqat muhit o'zgaruvchilaridan olinadi (GitHub'ga sir yozilmaydi).
# Lokal: .env fayl, Render: Dashboard > Environment.
BOT_TOKEN = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TOKEN") or "") \
    .strip().strip('"').strip("'").strip()
# Bir nechta owner bo'lsa vergul bilan: 111,222
OWNER_IDS = {8773630118} | {int(x) for x in re.split(r"[,\s]+", os.getenv("OWNER_ID", "")) if x.lstrip("-").isdigit()}
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
MIN_PLAYERS = int(os.getenv("MIN_PLAYERS", "5"))
MAX_PLAYERS = int(os.getenv("MAX_PLAYERS", "30"))

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
    "civ": ("👨🏼 Tinch aholi", "town",
            "Siz oddiy fuqarosiz. Kunduzi muhokama qilib, ovoz berib mafiyani toping."),
    "kom": ("🕵🏻‍♂️ Komissar Katani", "town",
            "Har kecha bitta o'yinchini tekshirasiz (mafiyami yoki yo'qmi) yoki otib o'ldirasiz."),
    "ser": ("👮🏻‍♂️ Serjant", "town",
            "Komissarning yordamchisi. Komissar o'lsa, uning o'rnini egallaysiz."),
    "doc": ("👨🏻‍⚕️ Doktor", "town",
            "Har kecha bitta o'yinchini davolaysiz. O'zingizni faqat bir marta davolay olasiz."),
    "luck": ("🤞 Omadli", "town",
             "Sizga hujum bo'lsa, 50% ehtimol bilan omon qolasiz."),
    "kam": ("💣 Kamikaze", "town",
            "Agar sizni osishsa, sizga ovoz berganlardan birini o'zingiz bilan olib ketasiz."),
    "bomj": ("🧙‍♂️ Bomj", "town",
             "Kechasi bitta o'yinchi eshigiga borasiz va u yerga yana kimlar kelganini ko'rasiz."),
    "kez": ("💃 Kezuvchi", "town",
            "Har kecha bitta o'yinchini band qilasiz — u o'sha tunda hech qanday harakat qila olmaydi."),
    "guard": ("🛡 Soqchi", "town",
              "Bitta o'yinchini qo'riqlaysiz. Unga hujum bo'lsa, uning o'rniga siz o'lasiz."),
    "hunter": ("🏹 Ovchi", "town",
               "Agar sizni tunda o'ldirishsa, qotilingizni o'zingiz bilan olib ketasiz."),
    "mafia": ("🤵🏻 Mafiya", "mafia",
              "Mafiya a'zosisiz. Har kecha jamoa bilan birga bitta odamni o'ldirasiz."),
    "don": ("🎩 Don", "mafia",
            "Mafiya boshlig'i. Ovozlar teng bo'lsa, sizning ovozingiz hal qiladi. Komissar sizni tinch aholi deb ko'radi."),
    "adv": ("👨🏼‍💼 Advokat", "mafia",
            "Har kecha bitta mafiya a'zosini himoya qilasiz — komissar tekshirsa, u tinch aholi bo'lib ko'rinadi."),
    "spy": ("🕶 Jasus", "mafia",
            "Har kecha bitta o'yinchining aniq rolini bilib olasiz."),
    "man": ("🔪 Manyak", "solo",
            "Yolg'iz o'ynaysiz. Har kecha bitta odamni o'ldirasiz. Oxirgi tirik qolsangiz — g'alaba."),
    "suit": ("🤦🏼 Suitsid", "solo",
             "Sizning maqsadingiz — kunduzi osilish. Sizni osishsa, g'alaba qozonasiz!"),
}

# kechasi harakat qiladigan rollar va ruxsat etilgan harakat turlari
ROLE_KINDS = {
    "mafia": {"k"}, "don": {"k"}, "adv": {"a"}, "spy": {"j"},
    "kom": {"c", "s"}, "doc": {"h"}, "kez": {"b"}, "guard": {"g"},
    "bomj": {"v"}, "man": {"m"},
}
PROMPTS = {
    "k": "🔪 Kimni o'ldiramiz?",
    "a": "👨🏼‍💼 Kimni himoya qilasiz? (u tekshiruvda tinch aholi bo'lib ko'rinadi)",
    "j": "🕶 Kimning rolini bilmoqchisiz?",
    "c": "🔍 Kimni tekshirasiz?",
    "s": "🔫 Kimni otasiz?",
    "h": "💉 Kimni davolaysiz?",
    "b": "💃 Kimni band qilasiz?",
    "g": "🛡 Kimni qo'riqlaysiz?",
    "v": "🧙‍♂️ Kimning uyiga borasiz?",
    "m": "🔪 Kimni o'ldirasiz?",
}


def rname(role: str) -> str:
    return ROLES[role][0]


def team(role: str) -> str:
    return ROLES[role][1]


# ───────────────────────── MA'LUMOTLAR BAZASI ─────────────────────────
def _open_db(path: str):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
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
    key = (u.full_name[:40], bool(private or (prev and prev[1])))
    if prev == key and now - SEEN_TS.get(u.id, 0) < 3600:
        return
    SEEN[u.id] = key
    SEEN_TS[u.id] = now
    db.execute(
        "INSERT INTO users(user_id,name,joined,started,last_seen) VALUES(?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, started=MAX(started,excluded.started), "
        "last_seen=excluded.last_seen",
        (u.id, key[0], now, 1 if key[1] else 0, now))
    db.commit()


def monthly_users() -> int:
    """Oxirgi 30 kunda botdan foydalangan (xabar yoki tugma bosgan) haqiqiy foydalanuvchilar soni."""
    since = int(time.time()) - 30 * 86400
    return db.execute("SELECT COUNT(*) FROM users WHERE last_seen>=?", (since,)).fetchone()[0]


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


# ───────────────────────── O'YIN MODELLARI ─────────────────────────
@dataclass
class Player:
    id: int
    name: str
    role: str = "civ"
    alive: bool = True
    healed_self: bool = False
    reborn: bool = False


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
    force: bool = False
    warned: bool = False
    acts: dict = field(default_factory=dict)
    votes: dict = field(default_factory=dict)
    vote_msg_id: int = 0
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
    return f'<a href="tg://user?id={p.id}">{esc(p.name)}</a>' + (" ⭐" if is_vip(p.id) else "")


async def send(chat_id, text, **kw):
    try:
        return await bot.send_message(chat_id, text, **kw)
    except TelegramAPIError as e:
        log.warning("send xato (%s): %s", chat_id, e)
        return None


async def safe_edit(msg: Message, text: str, **kw):
    try:
        await msg.edit_text(text, **kw)
    except TelegramAPIError:
        pass


def bot_link(payload: str = "") -> str:
    return f"https://t.me/{BOT_USERNAME}" + (f"?start={payload}" if payload else "")


def alive_list(g: Game) -> str:
    return "\n".join(f"{i}. {mention(p)}" for i, p in enumerate(g.alive(), 1))


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
              url=f"https://t.me/{BOT_USERNAME}?startgroup=true&admin=delete_messages")
    kb.button(text="🛒 Do'kon", callback_data="s:home")
    kb.button(text="👛 Hamyon", callback_data="s:wallet")
    kb.button(text="🎭 Rollar", callback_data="m:roles")
    kb.button(text="📖 Qoidalar", callback_data="m:rules")
    kb.button(text="🏆 Reyting", callback_data="m:top")
    kb.button(text="📊 Statistikam", callback_data="m:me")
    kb.button(text="🎲 Tasodifiy chat", callback_data="m:rchat")
    rows = [1, 2, 2, 2, 1]
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
    out = ["🎭 <b>Barcha rollar (16 ta)</b>\n"]
    for t, title in groups.items():
        out.append(title)
        for k, (n, tm, d) in ROLES.items():
            if tm == t:
                out.append(f"{n} — {d}")
        out.append("")
    return "\n".join(out)


def rules_text() -> str:
    return RULES_TEMPLATE.format(mn=MIN_PLAYERS, mx=MAX_PLAYERS)


RULES_TEMPLATE = (
    "📖 <b>Mafia o'yini qoidalari</b>\n\n"
    "1️⃣ O'yin <b>tun</b> va <b>kun</b> fasllaridan iborat.\n"
    "2️⃣ <b>Tunda</b> maxsus rollar botga (shaxsiy chatga) o'tib harakat qiladi: "
    "mafiya o'ldiradi, doktor davolaydi, komissar tekshiradi va hokazo.\n"
    "3️⃣ <b>Ertalab</b> kim o'lgani e'lon qilinadi va uning roli ochiladi.\n"
    "4️⃣ <b>Kunduzi</b> hamma muhokama qiladi, so'ng ovoz berib bitta odamni osadi.\n"
    "5️⃣ Tinch aholi barcha mafiya va manyakni topsa — g'alaba. "
    "Mafiya soni qolganlarga tenglashsa — mafiya g'alaba qiladi.\n"
    "6️⃣ Tunda mafiya a'zolari botga yozgan xabarlar o'zaro uzatiladi.\n"
    "7️⃣ O'yin vaqtida o'lganlar va tashqaridagilar yozishi mumkin emas "
    "(bot adminlik huquqiga ega bo'lsa, xabarlar o'chiriladi).\n\n"
    "👥 O'yinchilar: {mn}–{mx} ta."
)


def my_stats_text(u: User) -> str:
    row = db.execute("SELECT games,wins FROM stats WHERE user_id=?", (u.id,)).fetchone()
    games, wins = row if row else (0, 0)
    rate = f"{wins * 100 // games}%" if games else "0%"
    mny, dia = get_bal(u.id)
    badge = ""
    if u.id in OWNER_IDS:
        badge = "\n👑 Owner"
    elif u.id in ADMINS:
        badge = "\n🛡 Admin"
    if is_vip(u.id):
        badge += "\n⭐ VIP"
    return (f"📊 <b>{esc(u.full_name)}</b> statistikasi{badge}\n\n🎮 O'yinlar: {games}\n"
            f"🏆 G'alabalar: {wins}\n📈 G'alaba foizi: {rate}\n\n💵 Pul: {mny}\n💎 Olmos: {dia}")


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
    await m.answer(roles_text())


@router.message(Command("rules"))
async def cmd_rules(m: Message):
    await m.answer(rules_text())


@router.message(Command("top"))
async def cmd_top(m: Message):
    await m.answer(top_text())


@router.message(Command("me", "stats"))
async def cmd_me(m: Message):
    await m.answer(my_stats_text(m.from_user))


@router.callback_query(F.data.startswith("m:"))
async def menu_cb(cq: CallbackQuery):
    act = cq.data.split(":")[1]
    msg = cq.message
    if act == "roles":
        await msg.answer(roles_text())
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
    lst = "\n".join(f"{i}. {mention(p)}" for i, p in enumerate(g.players.values(), 1)) or "—"
    return (f"🎮 <b>Mafia o'yiniga ro'yxatga olish!</b>\n\n"
            f"👥 O'yinchilar ({len(g.players)}):\n{lst}\n\n"
            f"Kamida {MIN_PLAYERS} ta o'yinchi kerak.\n⏳ Taxminan {left // 60}:{left % 60:02d} qoldi")


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


async def start_registration(chat_id: int, title: str, user: User):
    if chat_id in GAMES:
        await send(chat_id, "⚠️ Bu chatda o'yin allaqachon boshlangan yoki ro'yxat ochiq.")
        return
    g = Game(chat_id=chat_id, title=title, creator=user.id)
    g.deadline = time.time() + REG_TIME
    GAMES[chat_id] = g
    msg = await send(chat_id, reg_text(g), reply_markup=join_kb(g))
    if msg:
        g.reg_msg_id = msg.message_id
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
    if g and g.state == "reg":
        g.deadline += 60
        await m.answer("⏱ Ro'yxatga olish 1 daqiqaga uzaytirildi.")
        await refresh_reg(g)


@router.message(Command("begin", "go"))
async def cmd_begin(m: Message):
    g = GAMES.get(m.chat.id)
    if not g or g.state != "reg":
        return
    if (m.from_user.id != g.creator and not is_vip(m.from_user.id)
            and not await is_admin(m.chat.id, m.from_user.id)):
        await m.answer("Faqat o'yin boshlovchisi, admin yoki VIP boshlay oladi.")
        return
    if len(g.players) < MIN_PLAYERS:
        await m.answer(f"❌ Kamida {MIN_PLAYERS} ta o'yinchi kerak.")
        return
    g.force = True


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
def build_roles(n: int) -> list:
    m = max(1, round(n / 4))
    if m == 1:
        mafia = ["mafia"]
    else:
        order = ["don", "mafia", "adv", "spy"] + ["mafia"] * 20
        mafia = order[:m]
    solo = []
    if n >= 9:
        solo.append("man")
    if n >= 12:
        solo.append("suit")
    town_n = n - len(mafia) - len(solo)
    spec_order = ["kom", "doc", "kez", "luck", "guard", "bomj", "ser", "kam", "hunter"]
    civ_min = max(1, town_n // 6)
    specials = spec_order[:max(0, min(len(spec_order), town_n - civ_min))]
    roles = mafia + solo + specials + ["civ"] * (town_n - len(specials))
    random.shuffle(roles)
    return roles


def apply_tickets(plist: list):
    """🎟 Rol chiptalari: egasiga so'ralgan rolni beradi (agar o'yinda shunday rol bo'lsa)."""
    locked = set()
    for tk, wanted in TICKETS.items():
        for p in plist:
            if p.id in locked or not inv_ready(p.id, tk):
                continue
            if p.role in wanted:
                inv_use(p.id, tk)
                locked.add(p.id)
                continue
            cands = [q for q in plist if q.role in wanted and q.id not in locked]
            if not cands:
                continue
            q = random.choice(cands)
            p.role, q.role = q.role, p.role
            inv_use(p.id, tk)
            locked.add(p.id)


def check_win(g: Game) -> Optional[str]:
    al = g.alive()
    n = len(al)
    mafia = [p for p in al if team(p.role) == "mafia"]
    man = [p for p in al if p.role == "man"]
    if n == 0:
        return "draw"
    if not mafia and not man:
        return "town"
    if not mafia and man and n <= 2:
        return "man"
    if mafia and not man and len(mafia) * 2 >= n:
        return "mafia"
    if mafia and man and n <= 2:
        return "draw"
    return None


async def promote_roles(g: Game):
    al = g.alive()
    if not any(p.role == "kom" for p in al):
        for p in al:
            if p.role == "ser":
                p.role = "kom"
                await send(p.id, "🕵🏻‍♂️ Komissar halok bo'ldi! Endi <b>Komissar Katani</b> sizsiz.")
                break
    if any(team(p.role) == "mafia" for p in al) and not any(p.role in ("mafia", "don") for p in al):
        for p in al:
            if p.role in ("adv", "spy"):
                p.role = "mafia"
                await send(p.id, "🤵🏻 Mafiyaning qotillari qolmadi — endi siz <b>Mafiya</b>siz va o'ldira olasiz.")
                break


def cleanup(g: Game):
    if GAMES.get(g.chat_id) is g:
        del GAMES[g.chat_id]
    for uid in list(g.players):
        if USER_GAME.get(uid) == g.chat_id:
            del USER_GAME[uid]


# ───────────────────────── ASOSIY O'YIN SIKLI ─────────────────────────
async def game_main(g: Game):
    try:
        # 1) ro'yxatga olish
        while time.time() < g.deadline and not g.force:
            await asyncio.sleep(2)
            left = g.deadline - time.time()
            if left <= 30 and not g.warned:
                g.warned = True
                await send(g.chat_id, "⏰ Ro'yxat yopilishiga <b>30 soniya</b> qoldi!",
                           reply_markup=join_kb(g))
        if len(g.players) < MIN_PLAYERS:
            await send(g.chat_id, f"❌ O'yinchilar yetarli emas (kamida {MIN_PLAYERS}). O'yin bekor qilindi.")
            return
        try:
            await bot.edit_message_reply_markup(chat_id=g.chat_id, message_id=g.reg_msg_id, reply_markup=None)
        except TelegramAPIError:
            pass

        # 2) rollarni taqsimlash
        g.state = "starting"
        roles = build_roles(len(g.players))
        plist = list(g.players.values())
        random.shuffle(plist)
        for p, r in zip(plist, roles):
            p.role = r
        apply_tickets(plist)
        mafia_names = ", ".join(esc(p.name) for p in plist if team(p.role) == "mafia")
        for p in plist:
            text = f"🎭 Sizning rolingiz: <b>{rname(p.role)}</b>\n\n{ROLES[p.role][2]}"
            if team(p.role) == "mafia":
                text += f"\n\n🤵🏻 Mafiya jamoasi: {mafia_names}"
            await send(p.id, text)
        for p in plist:  # 🔮 Ko'ruvchi
            if team(p.role) != "mafia" and inv_ready(p.id, "seer"):
                cands = [q for q in plist if team(q.role) == "mafia"]
                if cands and inv_use(p.id, "seer"):
                    q = random.choice(cands)
                    await send(p.id, f"🔮 <b>Ko'ruvchi</b>: <b>{esc(q.name)}</b> — mafiya jamoasi a'zosi!")
        cnt = Counter(roles)
        comp = ", ".join(f"{rname(r)} ×{c}" if c > 1 else rname(r) for r, c in cnt.items())
        await send(g.chat_id,
                   f"🎲 <b>O'yin boshlandi!</b>\n\n👥 O'yinchilar: {len(plist)} ta\n"
                   f"🎭 Rollar: {comp}\n\n"
                   f"Rollar shaxsiy chatga yuborildi. Botga /start bosib qo'ying.",
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
    finally:
        cleanup(g)


def bot_btn():
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 Botga o'tish", url=bot_link())
    return kb.as_markup()


# ───────────────────────── TUN ─────────────────────────
def can_target(p: Player, q: Player, kind: str) -> bool:
    if not q.alive:
        return False
    if kind == "k":
        return team(q.role) != "mafia"
    if kind == "a":
        return team(q.role) == "mafia"
    if kind == "h":
        return q.id != p.id or not p.healed_self
    return q.id != p.id


def target_kb(g: Game, p: Player, kind: str):
    kb = InlineKeyboardBuilder()
    for q in g.alive():
        if can_target(p, q, kind):
            kb.button(text=q.name, callback_data=f"n:{g.chat_id}:{kind}:{q.id}")
    kb.button(text="⏭ O'tkazish", callback_data=f"n:{g.chat_id}:x:0")
    kb.adjust(2)
    return kb.as_markup()


def all_acted(g: Game) -> bool:
    return all(p.id in g.acts for p in g.alive() if p.role in ROLE_KINDS)


async def send_night_prompts(g: Game):
    for p in g.alive():
        if p.role not in ROLE_KINDS:
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
    g.night_event = asyncio.Event()
    await send(g.chat_id,
               f"🌙 <b>Tun {g.day}</b>\nShahar uyquga ketdi... Maxsus rollar botga o'tib harakat qilsin.\n\n"
               f"👥 Tirik o'yinchilar:\n{alive_list(g)}",
               reply_markup=bot_btn())
    await send_night_prompts(g)
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
    if kind == "x":
        g.acts[p.id] = ("x", 0)
        await safe_edit(cq.message, "⏭ Bu tun harakat qilmadingiz.")
    else:
        q = g.players.get(target)
        if kind not in ROLE_KINDS.get(p.role, set()) or not q or not can_target(p, q, kind):
            return await cq.answer("Noto'g'ri tanlov.", show_alert=True)
        g.acts[p.id] = (kind, target)
        if kind == "h" and target == p.id:
            p.healed_self = True
        await safe_edit(cq.message, f"✅ Tanlov: <b>{esc(q.name)}</b>")
        if kind == "k":  # mafiya jamoasiga bildirish
            for t in g.alive():
                if team(t.role) == "mafia" and t.id != p.id:
                    await send(t.id, f"🗳 {esc(p.name)} → <b>{esc(q.name)}</b>")
    await cq.answer()
    if all_acted(g) and g.night_event:
        g.night_event.set()


async def resolve_night(g: Game):
    pl = g.players
    acts = g.acts
    blocked = {t for u, (k, t) in acts.items() if k == "b" and pl[u].alive}
    valid = {u: (k, t) for u, (k, t) in acts.items()
             if k != "x" and u not in blocked and pl[u].alive}
    for b in blocked:
        if pl[b].alive:
            await send(b, "💃 Bu tun sizni kezuvchi band qildi — harakat qila olmadingiz!")

    attacks = []
    kills = [(u, t) for u, (k, t) in valid.items() if k == "k"]
    if kills:
        cnt = Counter(t for _, t in kills)
        mx = max(cnt.values())
        tops = [t for t, c in cnt.items() if c == mx]
        don_vote = [t for u, t in kills if pl[u].role == "don" and t in tops]
        target = don_vote[0] if don_vote else random.choice(tops)
        voters = [u for u, t in kills if t == target]
        attacker = next((u for u in voters if pl[u].role == "don"), voters[0])
        attacks.append((target, attacker))
    for u, (k, t) in valid.items():
        if k in ("m", "s"):
            attacks.append((t, u))

    heals = {t: u for u, (k, t) in valid.items() if k == "h"}
    guards = {t: u for u, (k, t) in valid.items() if k == "g"}
    adv_protected = {t for u, (k, t) in valid.items() if k == "a"}
    visits = defaultdict(list)
    for u, (k, t) in valid.items():
        visits[t].append(u)

    deaths = []
    extra = []
    for target, attacker in attacks:
        tp = pl.get(target)
        if not tp or not tp.alive:
            continue
        if target in heals:
            await send(target, "👨🏻‍⚕️ Bu tun sizga hujum bo'ldi, lekin doktor sizni qutqardi!")
            await send(heals[target], f"✅ Siz <b>{esc(tp.name)}</b> ni o'limdan qutqardingiz!")
            continue
        gu = guards.get(target)
        if gu and pl[gu].alive:
            pl[gu].alive = False
            deaths.append((pl[gu], "soqchi"))
            await send(target, "🛡 Sizga hujum bo'ldi, lekin soqchi o'zini qurbon qildi!")
            continue
        if inv_use(target, "shield"):
            await send(target, "🛡 Sizga hujum bo'ldi, lekin <b>Himoya</b> narsangiz sizni qutqardi!")
            continue
        if tp.role == "luck" and random.random() < 0.5:
            await send(target, "🤞 Sizga hujum bo'ldi, lekin omadingiz keldi — tirik qoldingiz!")
            continue
        if inv_use(target, "extralife"):
            await send(target, "❤️ Sizga hujum bo'ldi, lekin <b>Zaxira hayot</b> sizni o'limdan qutqardi!")
            continue
        tp.alive = False
        deaths.append((tp, "hujum"))
        if tp.role == "hunter":
            a = pl.get(attacker)
            if a and a.alive:
                a.alive = False
                deaths.append((a, "ovchi"))
                extra.append(f"🏹 Ovchi {mention(tp)} o'lar ekan, qotilini ham o'zi bilan olib ketdi!")

    # axborot rollari
    for u, (k, t) in valid.items():
        tp = pl.get(t)
        if not tp:
            continue
        if k == "c":
            is_mafia = tp.role in ("mafia", "adv", "spy") and t not in adv_protected
            if is_mafia and inv_use(t, "fakedoc"):
                is_mafia = False
            res = "🔴 <b>Mafiya</b>" if is_mafia else "🟢 <b>Tinch aholi</b> (mafiya emas)"
            await send(u, f"🔍 Tekshiruv natijasi: <b>{esc(tp.name)}</b> — {res}")
        elif k == "j":
            await send(u, f"🕶 <b>{esc(tp.name)}</b> — {rname(tp.role)}")
        elif k == "v":
            vis = [esc(pl[x].name) for x in visits[t] if x != u]
            txt = ", ".join(vis) if vis else "hech kim kelmadi"
            await send(u, f"🧙‍♂️ <b>{esc(tp.name)}</b> uyiga bu tun: {txt}")

    # ertalab
    g.state = "day"
    lines = [f"🌅 <b>Tong otdi! ({g.day}-kun)</b>\n"]
    if not deaths:
        lines.append("Bu kecha hech kim o'lmadi 😮‍💨")
    for d, _ in deaths:
        lines.append(f"💀 Tunda {mention(d)} vafot etdi. U — {rname(d.role)} edi.")
        await notify_dead(g, d, "☠️ Siz o'ldingiz. O'yin tugaguncha guruhda yozmang.")
    lines.extend(extra)
    await send(g.chat_id, "\n".join(lines))
    await promote_roles(g)


# ───────────────────────── KUN VA OVOZ BERISH ─────────────────────────
async def day_phase(g: Game):
    if check_win(g):
        return
    g.state = "day"
    await send(g.chat_id,
               f"☀️ <b>Kun {g.day}</b>\nMuhokama vaqti! Kim mafiya? ({DAY_TIME} soniya)\n\n"
               f"👥 Tirik o'yinchilar:\n{alive_list(g)}")
    await asyncio.sleep(DAY_TIME)


def vote_text(g: Game) -> str:
    lines = ["🗳 <b>Ovoz berish!</b>\nKimni osamiz?\n"]
    for voter, t in g.votes.items():
        tgt = esc(g.players[t].name) if t and t in g.players else "hech kim"
        lines.append(f"• {esc(g.players[voter].name)} → {tgt}")
    return "\n".join(lines)


def vote_kb(g: Game):
    cnt = Counter(g.votes.values())
    kb = InlineKeyboardBuilder()
    for q in g.alive():
        c = cnt.get(q.id, 0)
        kb.button(text=f"{q.name}" + (f" ({c})" if c else ""), callback_data=f"v:{g.chat_id}:{q.id}")
    kb.button(text="🚫 Hech kim" + (f" ({cnt.get(0)})" if cnt.get(0) else ""),
              callback_data=f"v:{g.chat_id}:0")
    kb.adjust(2)
    return kb.as_markup()


async def vote_phase(g: Game) -> Optional[str]:
    if check_win(g):
        return None
    g.state = "vote"
    g.votes = {}
    g.vote_event = asyncio.Event()
    msg = await send(g.chat_id, vote_text(g), reply_markup=vote_kb(g))
    g.vote_msg_id = msg.message_id if msg else 0
    try:
        await asyncio.wait_for(g.vote_event.wait(), VOTE_TIME)
    except asyncio.TimeoutError:
        pass
    g.state = "resolving"
    try:
        await bot.edit_message_reply_markup(chat_id=g.chat_id, message_id=g.vote_msg_id, reply_markup=None)
    except TelegramAPIError:
        pass

    tally = Counter()
    for voter, tgt in g.votes.items():
        w = 2 if (tgt and inv_use(voter, "vote2")) else 1
        tally[tgt] += w
    skip = tally.pop(0, 0)
    if not tally:
        await send(g.chat_id, "⚖️ Hech kim osilmadi.")
        return None
    top = tally.most_common()
    best_id, best_c = top[0]
    if (len(top) > 1 and top[1][1] == best_c) or best_c <= skip:
        await send(g.chat_id, "⚖️ Ovozlar kelishmadi — hech kim osilmadi.")
        return None

    victim = g.players[best_id]
    if inv_use(victim.id, "immune"):
        await send(g.chat_id, f"⚖️ {mention(victim)} osilishi kerak edi, lekin <b>Immunitet</b> uni saqlab qoldi!")
        await send(victim.id, "⚖️ Immunitet narsangiz sizni osilishdan saqladi!")
        return None
    if inv_use(victim.id, "extralife"):
        await send(g.chat_id, f"⚖️ {mention(victim)} osilishi kerak edi, lekin <b>Zaxira hayot</b> uni saqlab qoldi!")
        await send(victim.id, "❤️ Zaxira hayot sizni osilishdan saqladi!")
        return None
    victim.alive = False
    await send(g.chat_id, f"⚖️ Shahar qarori: {mention(victim)} osildi!\nU — {rname(victim.role)} edi.")
    await notify_dead(g, victim, "☠️ Siz osildingiz.")
    if victim.role == "suit":
        return "suit"
    if victim.role == "kam":
        voters = [g.players[v] for v, t in g.votes.items() if t == victim.id and g.players[v].alive]
        if voters:
            x = random.choice(voters)
            x.alive = False
            await send(g.chat_id,
                       f"💣 Kamikaze portladi va {mention(x)} ni o'zi bilan olib ketdi! "
                       f"U — {rname(x.role)} edi.")
            await notify_dead(g, x, "☠️ Kamikaze sizni o'zi bilan olib ketdi.")
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
    if target and (target not in g.players or not g.players[target].alive):
        return await cq.answer("Noto'g'ri tanlov.", show_alert=True)
    g.votes[p.id] = target
    await cq.answer("✅ Ovozingiz qabul qilindi")
    try:
        await cq.message.edit_text(vote_text(g), reply_markup=vote_kb(g))
    except TelegramAPIError:
        pass
    if len(g.votes) >= len(g.alive()) and g.vote_event:
        g.vote_event.set()


# ───────────────────────── O'YIN YAKUNI ─────────────────────────
def team_won(p: Player, w: str) -> bool:
    if w == "town":
        return team(p.role) == "town"
    if w == "mafia":
        return team(p.role) == "mafia"
    if w == "man":
        return p.role == "man"
    if w == "suit":
        return p.role == "suit"
    return False


async def finish_game(g: Game, w: str):
    g.state = "end"
    titles = {"town": "👨🏼 Tinch aholi jamoasi", "mafia": "🤵🏻 Mafiya jamoasi",
              "man": "🔪 Manyak", "suit": "🤦🏼 Suitsid", "draw": "🤝 Durang"}
    lines = [f"🏁 <b>O'yin tugadi!</b>\n\n🏆 G'olib: <b>{titles[w]}</b>\n\n👥 O'yinchilar:"]
    rewards = {}
    for p in g.players.values():
        win = team_won(p, w)
        mark = "🏆" if win else ("🙂" if p.alive else "💀")
        lines.append(f"{mark} {mention(p)} — {rname(p.role)}")
        add_result(p.id, p.name, win)
        reward = REWARD_WIN if win else REWARD_PLAY
        mult = 4 if inv_use(p.id, "superboost") else (2 if inv_use(p.id, "boost") else 1)
        reward *= mult
        add_money(p.id, reward)
        rewards[p.id] = (reward, mult)
    kv_set("cnt_games", int(kv_get("cnt_games", "0") or 0) + 1)
    lines.append("\nYana o'ynash uchun: /game")
    await send(g.chat_id, "\n".join(lines))
    record_chat_game(g.chat_id)
    for uid, (amt, mult) in rewards.items():
        await send(uid, f"💵 O'yin mukofoti: <b>+{amt}</b>" + (f" (💰 Boost ×{mult})" if mult > 1 else "")
                   + "\nDo'kon: /shop")


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
    "kit": {"name": "🧿 Himoya to'plami", "cur": "dia", "price": 20, "tier": 5,
            "desc": "🛡 Himoya + ⚖️ Immunitet + ❤️ Zaxira hayot — bittadan, alohida olgandan arzonroq.",
            "grants": {"shield": 1, "immune": 1, "extralife": 1}},
}
CUR_SYM = {"money": "💵", "dia": "💎"}
# chipta -> qaysi rollar uchun
TICKETS = {"t_kom": ("kom",), "t_doc": ("doc",), "t_don": ("don",), "t_mafia": ("mafia", "don", "adv", "spy")}
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
    amt = DAILY_BONUS * (2 if is_vip(uid) else 1)
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
    kb.adjust(1, 1, 2, 1, 1)
    return kb.as_markup()


def shop_view(uid: int, cat: str = ""):
    m, d = get_bal(uid)
    head = f"🛒 <b>Do'kon</b>\n\n💵 Pul: <b>{m}</b>   💎 Olmos: <b>{d}</b>\n"
    kb = InlineKeyboardBuilder()
    if cat not in ("money", "dia"):
        lines = [head,
                 "💵 <b>Pul do'koni</b> — oddiy va yaxshi narsalar.",
                 "💎 <b>Olmos do'koni</b> — kuchli narsalar, rol chiptalari, zaxira hayot.\n",
                 f"⭐ <b>VIP (30 kun)</b> — <b>{VIP_DIAMONDS}</b>💎\n<i>⭐ belgisi, o'yinni boshlash, kunlik bonus ×2.</i>\n",
                 "Narx kuchga qarab belgilangan: kuchliroq narsa — qimmatroq.\n"
                 "Sotib olingan narsalar o'yinda <b>avtomatik</b> ishlaydi. Xohlamasangiz, "
                 "🎒 Narsalarim bo'limidan o'chirib qo'yishingiz mumkin."]
        kb.button(text="💵 Pul do'koni", callback_data="s:cat:money")
        kb.button(text="💎 Olmos do'koni", callback_data="s:cat:dia")
        kb.button(text=f"⭐ VIP 30 kun — {VIP_DIAMONDS}💎", callback_data="s:vip")
        kb.button(text="🎒 Narsalarim", callback_data="s:inv")
        kb.button(text="👛 Hamyon", callback_data="s:wallet")
        kb.button(text="⬅️ Orqaga", callback_data="s:menu")
        kb.adjust(2, 1, 2, 1)
        return "\n".join(lines), kb.as_markup()
    title = "💵 <b>Pul do'koni</b>" if cat == "money" else "💎 <b>Olmos do'koni</b>"
    lines = [head, title + "\n"]
    items = [(k, v) for k, v in ITEMS.items() if v["cur"] == cat and item_price(k) > 0]
    items.sort(key=lambda kv: (kv[1]["tier"], item_price(kv[0])))
    for key, v in items:
        pr = item_price(key)
        lines.append(f"{TIERS[v['tier']]} · {v['name']} — <b>{pr}</b>{CUR_SYM[cat]}\n<i>{v['desc']}</i>\n")
        kb.button(text=f"{v['name']} — {pr}{CUR_SYM[cat]}", callback_data=f"s:buy:{key}")
    if not items:
        lines.append("Hozircha sotuvda narsa yo'q.")
    kb.button(text="⬅️ Do'konga", callback_data="s:home")
    kb.adjust(1)
    return "\n".join(lines), kb.as_markup()


async def show_shop(msg: Message, uid: int, edit: bool = False, cat: str = ""):
    text, kb = shop_view(uid, cat)
    if edit:
        await safe_edit(msg, text, reply_markup=kb)
    else:
        await msg.answer(text, reply_markup=kb)


def inv_view(uid: int):
    kb = InlineKeyboardBuilder()
    have = [k for k, v in ITEMS.items() if "grants" not in v and inv_qty(uid, k) > 0]
    for k in have:
        on = not inv_is_off(uid, k)
        kb.button(text=f"{'✅' if on else '⛔'} {ITEMS[k]['name']} ×{inv_qty(uid, k)}", callback_data=f"s:tg:{k}")
    kb.button(text="🛒 Do'kon", callback_data="s:home")
    kb.button(text="⬅️ Orqaga", callback_data="s:wallet")
    kb.adjust(*([1] * len(have)), 2)
    text = ("🎒 <b>Narsalarim</b>\n\n" +
            ("Narsani bosib yoqing/o'chiring:\n✅ — keyingi o'yinda ishlatiladi\n⛔ — saqlanadi, ishlatilmaydi"
             if have else "Hozircha narsa yo'q. 🛒 Do'kondan oling."))
    return text, kb.as_markup()


@router.callback_query(F.data.startswith("s:"))
async def shop_cb(cq: CallbackQuery):
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
        col = "money" if it["cur"] == "money" else "diamonds"
        if not spend(uid, col, item_price(key)):
            if it["cur"] == "money":
                return await cq.answer("💵 Pulingiz yetarli emas. O'yin o'ynang yoki 🎁 kunlik bonus oling.",
                                       show_alert=True)
            return await cq.answer("💎 Olmosingiz yetarli emas. Hamyon → Olmos sotib olish.", show_alert=True)
        for gk, gq in (it.get("grants") or {key: 1}).items():
            inv_add(uid, gk, gq)
        await show_shop(msg, uid, edit=True, cat=it["cur"])
        return await cq.answer(f"✅ Sotib olindi: {it['name']}")
    elif act == "vip":
        if VIPS.get(uid) == 0:
            return await cq.answer("Sizda umrbod VIP bor 😎", show_alert=True)
        if not spend(uid, "diamonds", VIP_DIAMONDS):
            return await cq.answer("💎 Olmosingiz yetarli emas.", show_alert=True)
        extend_vip(uid, 30)
        await show_shop(msg, uid, edit=True)
        return await cq.answer("⭐ VIP 30 kunga faollashtirildi!", show_alert=True)
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


@router.message(Command("paysupport"))
async def cmd_paysupport(m: Message):
    owners = ", ".join(ulink(o) for o in OWNER_IDS) or "admin"
    await m.answer("💬 To'lov bilan bog'liq muammo bo'lsa, admin bilan bog'laning: " + owners +
                   "\nTo'lov ma'lumotlari (to'lov ID) bilan yozing.")


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
    row = db.execute("SELECT user_id,diamonds,refunded FROM payments WHERE charge_id=?", (cid,)).fetchone()
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
    "economy": "💰 Iqtisod (pul, olmos, do'kon)",
}
SETTING_LABELS = {
    "REG_TIME": "⏳ Ro'yxat vaqti (soniya)",
    "NIGHT_TIME": "🌙 Tun vaqti (soniya)",
    "DAY_TIME": "☀️ Muhokama vaqti (soniya)",
    "VOTE_TIME": "🗳 Ovoz berish vaqti (soniya)",
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
ADMIN_STATE: dict = {}   # admin_id -> {"k": ...}
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
        return 10 <= val <= 900
    if key == "MIN_PLAYERS":
        return 3 <= val <= 30 and val <= MAX_PLAYERS
    if key == "MAX_PLAYERS":
        return MIN_PLAYERS <= val <= 100
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
    return f"👑 <b>Admin panel</b>\n\nSiz: {who}{perms}"


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
    await m.answer(panel_text(uid), reply_markup=admin_main_kb(uid))


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    if ADMIN_STATE.pop(m.from_user.id, None) is not None:
        await m.answer("❎ Bekor qilindi. /admin")


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


async def admin_cb_more(cq: CallbackQuery, uid: int, msg: Message, parts: list, act: str):
    async def deny():
        await cq.answer("⛔️ Bu bo'lim uchun huquqingiz yo'q.", show_alert=True)

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
            name = "💵 pul" if cur == "money" else "💎 olmos"
            await safe_edit(msg, f"🎁 {name} berish/olish\n\n<code>ID MIQDOR</code> ko'rinishida yuboring, masalan:\n"
                                 "<code>123456789 500</code> — qo'shish\n<code>123456789 -100</code> — ayirish\n"
                                 "Bekor qilish: /cancel", reply_markup=back_kb("ad:eco"))
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
        bits = t.split()
        if len(bits) != 2 or not bits[0].lstrip("-").isdigit() or not bits[1].lstrip("-").isdigit():
            await m.answer("❌ Format: <code>ID MIQDOR</code> (masalan: <code>123456789 500</code>).")
            return True
        target, amount = int(bits[0]), int(bits[1])
        if abs(amount) > 10_000_000:
            await m.answer("❌ Miqdor juda katta.")
            return True
        if st["cur"] == "money":
            add_money(target, amount)
            what = "💵"
        else:
            add_dia(target, amount)
            what = "💎"
        ADMIN_STATE.pop(uid, None)
        mny, dia = get_bal(target)
        await m.answer(f"✅ {ulink(target)}: {amount:+d}{what}\nHozirgi balans: 💵 {mny} · 💎 {dia}",
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
            await m.answer("❌ Noto'g'ri qiymat. Vaqt 10–900 soniya, minimal o'yinchi 3–30, maksimal o'yinchi 5–100, "
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
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Menyu"),
            BotCommand(command="roles", description="Rollar ro'yxati"),
            BotCommand(command="rules", description="Qoidalar"),
            BotCommand(command="top", description="Reyting"),
            BotCommand(command="me", description="Mening statistikam"),
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
            BotCommand(command="extend", description="Vaqtni uzaytirish"),
            BotCommand(command="players", description="O'yinchilar"),
            BotCommand(command="stop", description="O'yinni to'xtatish"),
            BotCommand(command="menu", description="Menyu"),
            BotCommand(command="roles", description="Rollar"),
            BotCommand(command="rules", description="Qoidalar"),
            BotCommand(command="top", description="Reyting"),
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
    spawn(stats_loop())
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
    """Bot profilidagi qisqa tavsifga haqiqiy oylik foydalanuvchilar sonini yozib boradi (6 soatda 1 marta)."""
    global LAST_DESC
    await asyncio.sleep(20)
    while True:
        try:
            desc = f"👥 {fmt_num(monthly_users())} oylik foydalanuvchi · Mafia o'yin boti"
            if desc != LAST_DESC:
                await bot.set_my_short_description(short_description=desc[:120])
                LAST_DESC = desc
        except Exception as e:
            log.warning("Qisqa tavsifni yangilab bo'lmadi: %s", e)
        await asyncio.sleep(6 * 3600)


async def health(_request):
    return web.Response(text="Mafia bot ishlayapti ✅")


def load_state():
    for uid, perms in db.execute("SELECT user_id,perms FROM admins"):
        ADMINS[uid] = {x for x in (perms or "").split(",") if x}
    for uid, until in db.execute("SELECT user_id,vip_until FROM users WHERE vip=1"):
        VIPS[uid] = until
    for (uid,) in db.execute("SELECT user_id FROM users WHERE banned=1"):
        BANNED.add(uid)
    for key in SETTING_LABELS:
        v = kv_get(key)
        if v and v.lstrip("-").isdigit():
            globals()[key] = int(v)
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
