import os
import secrets
from dotenv import load_dotenv

import psycopg
from psycopg.rows import dict_row

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import openai

import re

MAX_TG = 4096

async def send_long_text(chat_id: int, text: str, context, parse_mode=None):
    """
    Делит длинный текст на части и отправляет по очереди,
    чтобы Telegram ничего не обрезал.
    Режем по пустым строкам и заголовкам "День N:".
    """
    parts = []
    buf = ""

    tokens = re.split(r'(?=День\s+\d+:)|\n{2,}', text or "")

    for t in tokens:
        if not t:
            continue
        if len(buf) + len(t) + 1 > MAX_TG - 50:
            if buf.strip():
                parts.append(buf.strip())
            buf = t
        else:
            buf += ("\n\n" if buf else "") + t

    if buf.strip():
        parts.append(buf.strip())

    for chunk in parts:
        await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode)

import time

def openai_chat(messages, *, max_tokens=1600, temperature=0.8, attempts=3):
    last_err = None
    for i in range(1, attempts + 1):
        try:
            r = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=temperature,
                max_tokens=max_tokens,
                messages=messages,
            )
            return r["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            print(f"[openai_chat] attempt {i}/{attempts} failed:", e)
            time.sleep(1.5 * i)
    raise last_err

print(">>> Бот загружен, bot.py — FIX (psycopg v3 + PTB21)")

# === Настройки окружения ===
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BOT_NAME = os.getenv("MAIN_BOT_USERNAME", "content_helper_assist_bot")
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан. Укажи его в .env или переменных окружения.")

# Храним ранее сгенерированные идеи/заголовки
cur.execute("""
CREATE TABLE IF NOT EXISTS used_ideas (
  user_id   BIGINT      NOT NULL,
  idea      TEXT        NOT NULL,
  created_at TIMESTAMP  NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, idea)
)
""")

# === Приложение PTB 21 ===
app = Application.builder().token(BOT_TOKEN).build()
ensure_schema()

# === Схема БД (PostgreSQL) ===
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS allowed_users (
        user_id BIGINT NOT NULL,
        bot_name TEXT NOT NULL,
        PRIMARY KEY (user_id, bot_name)
    );
    """
)
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS tokens (
        token TEXT PRIMARY KEY,
        bot_name TEXT NOT NULL,
        user_id BIGINT NOT NULL
    );
    """
)
# Админа добавим, если указан
if ADMIN_ID:
    cur.execute(
        "INSERT INTO allowed_users(user_id, bot_name) VALUES(%s, %s) ON CONFLICT DO NOTHING",
        (ADMIN_ID, BOT_NAME),
    )

# === Сессии в памяти (для диалога) ===
sessions: dict[int, dict] = {}

# === Утилиты ===
def get_user_session(update: Update) -> dict:
    user_id = update.effective_user.id
    return sessions.setdefault(
        user_id,
        {
            "state": "",
            "step": 0,
            "data": {},
            "products": [],
            "audience_segments": [],
            "planner_data": [],
            "reels_data": [],
            "copy_data": [],
        },
    )


def get_user_context(session: dict) -> str:
    data = session.get("data", {})
    if "info" in data and isinstance(data["info"], list):
        labels = [
            "Распаковка",
            "Позиционирование",
            "Характеристика продукта",
            "Анализ ЦА (кратко)",
        ]
        lines = []
        for i, val in enumerate(data["info"][:4]):
            label = labels[i] if i < len(labels) else f"Поле {i+1}"
            lines.append(f"{label}: {val}")
        extra = data.get("extra_info")
        if extra:
            lines.append(f"Доп.по ЦА: {extra}")
        return "\n".join(lines)
    return "Нет данных"


def sanitize_ad_text(text: str) -> str:
    return (
        text.replace("100%", "почти наверняка").replace("лучший", "один из лучших")
    )


# Разбиваем длинный текст по заголовкам "День N:" и пустым строкам,
# чтобы не рвать посреди дня/пункта.
async def send_long_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    MAX_TG = 4096
    parts = []
    buf = ""

    # Разделяем по "День N:" и по пустым строкам
    tokens = re.split(r'(?=День\s+\d+:)|\n{2,}', text or "")

    for t in tokens:
        if not t:
            continue
        if len(buf) + len(t) + 2 > MAX_TG - 50:  # небольшой запас
            if buf.strip():
                parts.append(buf.strip())
            buf = t
        else:
            buf += ("\n\n" if buf else "") + t

    if buf.strip():
        parts.append(buf.strip())

    for chunk in parts:
        await context.bot.send_message(chat_id=chat_id, text=chunk)

def normalize_platform(text: str) -> str | None:
    t = (text or "").strip().lower()
    if any(x in t for x in ["insta", "инста", "инстаграм", "инстаграмм", "ig"]):
        return "instagram"
    if any(x in t for x in ["tg", "тг", "telegram", "телеграм"]):
        return "telegram"
    if any(x in t for x in ["youtube", "ютуб"]):
        return "youtube"
    if any(x in t for x in ["vk", "вк", "вконтакте"]):
        return "vk"
    if any(x in t for x in ["tiktok", "тик ток", "тикток"]):
        return "tiktok"
    return None

# === Анти-повторы идей (извлечь / сохранить / загрузить) ===
import re  # если уже импортирован выше — повторять не надо

IDEA_RE = re.compile(r"Заголовок:\s*(.+?)(?:\n|$|•)", re.IGNORECASE)

def extract_ideas_from_plan(text: str) -> list[str]:
    """
    Достаём все значения после 'Заголовок:' из плана.
    Работает с строками вида:
    • Сторис — Заголовок: ...
    • Рилс/Пост — Заголовок: ...
    """
    ideas = []
    for m in IDEA_RE.finditer(text or ""):
        idea = m.group(1).strip()
        idea = re.sub(r"\s+", " ", idea)  # лёгкая чистка
        if idea:
            ideas.append(idea)

    # убираем дубли внутри одного плана, сохраняя порядок
    seen = set()
    uniq = []
    for i in ideas:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return uniq

def save_used_ideas(user_id: int, ideas: list[str]) -> None:
    if not ideas:
        return
    with conn.cursor() as c:
        c.executemany(
            "INSERT INTO used_ideas(user_id, idea) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [(user_id, i) for i in ideas]
        )

def load_used_ideas(user_id: int, limit: int = 400) -> list[str]:
    with conn.cursor() as c:
        c.execute(
            "SELECT idea FROM used_ideas WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        )
        rows = c.fetchall()
    # conn создан с row_factory=dict_row, поэтому rows — это список словарей
    return [r["idea"] for r in rows]


def is_allowed(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    cur.execute(
        "SELECT 1 FROM allowed_users WHERE user_id=%s AND bot_name=%s LIMIT 1",
        (user_id, BOT_NAME),
    )
    return cur.fetchone() is not None


# === Генерация токена (для главного бота/админа) ===
async def gentoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Используй: /gentoken <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Некорректный user_id.")
        return

    # Гарантируем уникальность токена
    token = secrets.token_hex(4)
    cur.execute(
        "INSERT INTO tokens(token, bot_name, user_id) VALUES(%s, %s, %s) ON CONFLICT DO NOTHING",
        (token, BOT_NAME, target_id),
    )
    # Если внезапно конфликт, можно перегенерить; для простоты считаем, что ок
    await update.message.reply_text(
        f"✅ Токен для {target_id}: {token}\nhttps://t.me/{BOT_NAME}?start={token}"
    )


def validate_token(token: str, user_id: int) -> bool:
    cur.execute(
        "SELECT user_id FROM tokens WHERE token=%s AND bot_name=%s",
        (token, BOT_NAME),
    )
    row = cur.fetchone()
    if row and row["user_id"] == user_id:
        # Разрешаем доступ пользователю и удаляем токен (одноразовый)
        cur.execute(
            "INSERT INTO allowed_users(user_id, bot_name) VALUES(%s, %s) ON CONFLICT DO NOTHING",
            (user_id, BOT_NAME),
        )
        cur.execute("DELETE FROM tokens WHERE token=%s", (token,))
        return True
    return False


# === Текст приветствия ===
WELCOME = """👋 Привет! Ты в боте «Контент-ассистент».

Он поможет:
• составить контент-план,
• написать пост или Reels,
• упаковать продукт.

🔐 Чтобы начать, подтверди согласие с
[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit)
и [Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).

✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!
"""

# Порядок вопросов по базе
INFO_QUESTIONS = [
    "✍️ Пришли свою распаковку личности и экспертности.",
    "🔥 Отлично! Теперь пришли своё позиционирование.",
    "✅ Теперь пришли характеристику продукта/услуги.",
    "📌 Пришли анализ твоей ЦА.",
]


# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if args:
        # Пришли через ссылку вида ?start=TOKEN
        if validate_token(args[0], user_id):
            await update.message.reply_text("✅ Доступ активирован! Добро пожаловать!")
            await update.message.reply_text(
                WELCOME,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
                ),
            )
            return
        else:
            await update.message.reply_text("❌ Неверный или использованный токен.")
            return

    # Если пользователь уже в allow — пропускаем токен
    if is_allowed(user_id):
        await update.message.reply_text(
            WELCOME,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
            ),
        )
        return

    await update.message.reply_text("Привет! Для доступа нужен токен. Обратись к админу/главному боту.")


# === Callback кнопки ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_allowed(user_id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return

    session = sessions.setdefault(
        user_id,
        {
            "state": "",
            "step": 0,
            "data": {},
            "products": [],
            "audience_segments": [],
            "planner_data": [],
            "reels_data": [],
            "copy_data": [],
        },
    )

    # --- Согласие ---
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")],
        ]
        await query.edit_message_text(
            "Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif query.data == "base_yes" or query.data == "fill_here":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Заполнить здесь", callback_data="fill_here")],
            [InlineKeyboardButton("Использовать другой бот", callback_data="use_other_bot")],
        ]
        await query.edit_message_text(
            "Давай соберём основу прямо здесь:", reply_markup=InlineKeyboardMarkup(kb)
        )

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Бот по распаковке в разработке.")

    # --- Продукты: цикл Да/Нет ---
    elif query.data == "add_product_yes":
        session["state"] = "collecting_base_info"
        session["step"] = 2
        await query.edit_message_text("✅ Пришли характеристику следующего продукта.")

    elif query.data == "add_product_no":
        session["state"] = "collecting_base_info"
        session["step"] = 3
        await query.edit_message_text("📌 Пришли анализ твоей ЦА.")

    # --- Сбор продуктов (альтернативный поток) ---
    elif query.data == "add_product":
        session["state"] = "collecting_more_products"
        await query.edit_message_text("✍️ Пришли характеристику следующего продукта.")

    elif query.data == "no_more_products":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("📌 Пришли первый сегмент анализа ЦА.")

    elif query.data == "add_audience_segment":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("✍️ Пришли следующий сегмент анализа ЦА.")

   
    elif query.data == "audience_done":
        # Сохраняем собранные сегменты одной строкой (как раньше extra_info)
        session.setdefault("data", {})["extra_info"] = "\n\n".join(session.get("audience_segments", []))

        # СРАЗУ показываем выбор помощников
        session["state"] = "menu_roles"
        kb = [
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Reels",       callback_data="role_reels")],
        ]
        await query.edit_message_text(
            "✅ Анализ ЦА собран! Выбери помощника:",
            reply_markup=InlineKeyboardMarkup(kb),
        )


    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await query.edit_message_text(
            "✅ Информация получена! Переходим к выбору помощников.",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif query.data == "roles_menu":
        session["state"] = "menu_roles"
        kb = [
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Reels", callback_data="role_reels")],
        ]
        await query.edit_message_text(
            "🤖 *Твои помощники*: выбери, кто тебе нужен👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    # === Помощники (оставил твою логику ниже без изменений) ===
    elif query.data == "role_planner":
        session["state"] = "planner_menu"
        kb = [
            [InlineKeyboardButton("🗓 Начать сбор данных", callback_data="planner_start")],
            [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")],
        ]
        await query.edit_message_text(
            "📅 Я — Планировщик. Готов составить стратегию!",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif query.data == "planner_start":
        session["state"] = "planner_goal"
        session["planner_data"] = []
        await query.edit_message_text(
            "🎯 Укажи главную цель контент-плана (привлечение, прогрев, продажи и т.д.)."
        )

    elif query.data == "role_copywriter":
        session["state"] = "copywriter_menu"
        kb = [
            [InlineKeyboardButton("📝 Пост", callback_data="copy_post")],
            [InlineKeyboardButton("📊 Карусель", callback_data="copy_carousel")],
            [InlineKeyboardButton("🎁 Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("📦 Упаковка продукта", callback_data="copy_package")],
            [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")],
        ]
        await query.edit_message_text(
            "✍️ Я — Копирайтер. Что создаём?",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif query.data.startswith("copy_"):
        task = query.data.split("_", 1)[1]
        session["state"] = f"copywriter_{task}"
        session["task"] = task
        session["step"] = 0
        session["copy_data"] = []
        await query.edit_message_text(
            "1️⃣ Укажи цель текста (имиджевая, вовлекающая, продающая, образовательная)."
        )

    elif query.data == "role_reels":
        session["state"] = "reels_menu"
        kb = [
            [InlineKeyboardButton("🎬 Начать сценарий Reels", callback_data="reels_start")],
            [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")],
        ]
        await query.edit_message_text(
            "🎥 Я — Продюсер Reels. Что будем снимать?",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif query.data == "reels_start":
        session["state"] = "reels_topic"
        session["reels_data"] = []
        await query.edit_message_text("🎬 Укажи тему и цель ролика.")

# === DB helpers (psycopg v3) ===
DATABASE_URL = os.getenv("DATABASE_URL")

_conn: psycopg.Connection | None = None

def db_connect() -> psycopg.Connection:
    """Singleton-подключение с keepalive, autocommit и dict_row."""
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn
    _conn = psycopg.connect(
        DATABASE_URL,
        sslmode="require",
        autocommit=True,
        row_factory=dict_row,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )
    return _conn

def ensure_schema() -> None:
    """Создаём таблицу used_ideas один раз при старте."""
    conn = db_connect()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS used_ideas (
            user_id    bigint      NOT NULL,
            idea       text        NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """)

# === ЕДИНЫЙ обработчик текстовых сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ У вас нет доступа.")
        return

    session = get_user_session(update)
    text = update.message.text

    # === Сбор основной информации (пошагово) ===
    if session.get("state") == "collecting_base_info":
        step = int(session.get("step", 0))
        session.setdefault("data", {}).setdefault("info", [])
        session.setdefault("products", [])

        if step == 0:
            session["data"]["info"].append(text)  # распаковка
            session["step"] = 1
            await update.message.reply_text("🔥 Отлично! Теперь пришли своё позиционирование.")
            return

        elif step == 1:
            session["data"]["info"].append(text)  # позиционирование
            session["step"] = 2
            await update.message.reply_text("✅ Теперь пришли характеристику продукта/услуги.")
            return

        elif step == 2:
            # продукт — сохраняем и спрашиваем, хотим ли ещё один
            session["products"].append(text)
            kb = [
                [InlineKeyboardButton("Да", callback_data="add_product_yes")],
                [InlineKeyboardButton("Нет", callback_data="add_product_no")],
            ]
            session["state"] = "product_decision"
            await update.message.reply_text(
                "Хочешь рассказать ещё об одном продукте?",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return

        elif step == 3:
            session.setdefault("audience_segments", []).append(text)
            session["state"] = "collecting_audience_multiple"
            kb = [
                [InlineKeyboardButton("Да",  callback_data="add_audience_segment")],
                [InlineKeyboardButton("Нет", callback_data="audience_done")],
            ]
            await update.message.reply_text(
                "✅ Сегмент #1 добавлен. Хочешь прислать ещё сегмент ЦА? (Да/Нет)",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return   # ← вот эту строку добавить


    # Добавление доп. продуктов (альтернативный поток через кнопки add_product/no_more_products)
    if session.get("state") == "collecting_more_products":
        session.setdefault("products", []).append(text)
        kb = [
            [InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
            [InlineKeyboardButton("Нет", callback_data="no_more_products")],
        ]
        await update.message.reply_text(
            "✅ Продукт добавлен. Добавить ещё?",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    # Многосегментная ЦА (если используешь)
    if session.get("state") == "collecting_audience_multiple":
        session["audience_segments"].append(text)
        kb = [
            [InlineKeyboardButton("Да",  callback_data="add_audience_segment")],
            [InlineKeyboardButton("Нет", callback_data="audience_done")],
        ]
        await update.message.reply_text(
            "✅ Сегмент добавлен. Хочешь прислать ещё сегмент ЦА? (Да/Нет)",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return   # ← добавить, чтобы не падать в «не понял команду»

    # Доп.инфа
    if session.get("state") == "waiting_extra_info":
        session.setdefault("data", {})["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text(
            "✅ Доп.информация получена. Переходим к помощникам.",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        session["state"] = "menu_roles"
        return

    # === Копирайтер ===
    if str(session.get("state", "")).startswith("copywriter_"):
        step = int(session.get("step", 0))
        session.setdefault("copy_data", []).append(text)
        session["step"] = step + 1

        if step == 0:
            await update.message.reply_text("2️⃣ Укажи тему текста.")
            return
        elif step == 1:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
            return
        elif step == 2:
            await update.message.reply_text("4️⃣ Хочешь развернутый текст или краткий, но ёмкий?")
            return
        elif step == 3:
            goal, topic, tone, length = session["copy_data"]
            context_text = get_user_context(session)

            # FIX: безопасные плейсхолдеры вместо необъявленных переменных
            used_ideas = ""
            days = ""
            history = "\n".join(load_used_ideas(user_id)) if 'load_used_ideas' in globals() else ""

            prompt = f"""
Ты профессиональный копирайтер и упаковщик. Создай {session['task']} для блогера/эксперта/бренда.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Цель поста: {goal}
📌 Тема: {topic}
🎨 Тональность: {tone}
📝 Формат текста: {length} (развернутый или краткий, но ёмкий)

=== ЦЕЛИ ПОСТОВ И ЧТО УЧИТЫВАТЬ ===
Имиджевая → истории о себе/бренде, ценности, миссия, кейсы  
Вовлекающая → опросы, челленджи, вопросы, дискуссии  
Образовательная → инструкции, гайды, разборы, чек-листы, экспертные советы  
Продающая → офферы, акции, отзывы, демонстрация продукта  
Прогревающая → истории клиентов, закулисье продукта, полезные факты  
Вирусная → тренды, мемы, провокационные темы, эмоциональные видео  
Информационная → анонсы, новости, релизы, события  
Развлекательная → юмор, подборки, легкие факты, блиц-опросы  

=== ЕСЛИ ФОРМАТ = ПОСТ-КАРУСЕЛЬ ===
✅ Используй структуру 10 слайдов:
1. Крючок – захват внимания (1-2 секунды)
2. Проблема – боль ЦА
3. Усиление боли – последствия, упущенные выгоды
4. Обещание решения – надежда на результат
5–8. Контент – пошаговая инструкция, советы, факты, чек-лист
9. Призыв к действию (CTA) – «Сохрани», «Напиши +», «Поделись»
10. Оффер/экспертность – автор, упоминание услуги, мягкий оффер

=== ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ЛЮБОГО ТЕКСТА ===
– Заголовок (цепляет, максимум 5–7 слов)  
– Вступление (подводит, цепляет эмоцией)  
– Основная часть (логично, структурно, без воды)  
– Вывод или CTA (побуждение к действию)  
– Оффер или УТП (если уместно)  

=== СТИЛЬ ПИСЬМА ===
– Пиши цепко, по-человечески, без клише  
– Используй стиль 2024–2025: коротко, просто, с эмоцией  
– Применяй сторителлинг, честный контент, вовлечение  
– Упрощай и усиливай, если текст есть  

=== УСЛОВИЯ ===
- Каждый новый текст должен быть уникальным и отличаться от предыдущих.  
- Не повторяй идеи, CTA, структуру и примеры, использованные ранее.  
- Для каждого текста добавляй новые креативные механики и неожиданные ходы.  
- Используй разные подходы: истории, факты, неожиданные советы, чтобы каждый материал был свежим.  
- Не используй ранее применённые идеи: {history[-2000:]}
 
⚖️ Соблюдай Федеральный закон №38-ФЗ и №72-ФЗ от 07.04.2025:  
не используй фразы «100% результат», «лучший», «гарантировано»,  
заменяй их корректными альтернативами: «один из популярных вариантов», «подходит для…», «узнай подробнее».  

💡 Выдай текст в структурированном виде, готовый к публикации.  
Добавь уникальные элементы, которых не было в предыдущих генерациях.
"""

            await update.message.reply_text("✍️ Генерация текста...")
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    max_tokens=1500,
                    temperature=0.7,
                    messages=[{"role": "user", "content": prompt}],
                )
                result = sanitize_ad_text(response["choices"][0]["message"]["content"])
                await send_long_message(update.effective_chat.id, result, context)
            except Exception as e:
                print("Copywriter Error:", e)
                await update.message.reply_text("⚠️ Ошибка генерации текста.")

            session["state"] = "menu_roles"
            kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Текст готов!", reply_markup=InlineKeyboardMarkup(kb))
            return

    # === Планировщик ===
    # цель → платформа
    if session.get("state") == "planner_goal":
        goal = (text or "").strip()
        if not goal:
            await update.message.reply_text("🎯 Укажи цель (привлечение, прогрев, продажи и т.д.).")
            return
        session["planner_data"] = [goal]          # [goal]
        session["state"] = "planner_platform"
        await update.message.reply_text(
            "📌 На какой платформе нужен план? (Instagram / Telegram / YouTube / VK / TikTok)\n"
            "Можно писать «инстаграмм», «инста», «тг», «ютуб»."
        )
        return

    # платформа → частота
    if session.get("state") == "planner_platform":
        platform = normalize_platform(text)
        if not platform:
            await update.message.reply_text(
                "📌 Платформа не распознана. Напиши Instagram / Telegram / YouTube / VK / TikTok\n"
                "(можно «инста», «инстаграмм», «тг», «ютуб»)."
            )
            return
        session["planner_data"].append(platform)  # [goal, platform]
        session["state"] = "planner_frequency"
        await update.message.reply_text("🗓 Укажи частоту публикаций (например: 1/день, 3/неделю).")
        return

    # частота → лицо
    if session.get("state") == "planner_frequency":
        session["planner_data"].append(text.strip())  # [goal, platform, freq]
        session["state"] = "planner_face"
        await update.message.reply_text("👤 От чьего лица вести: личный / бренд / эксперт / команда?")
        return

    # лицо → спрашиваем срок
    if session.get("state") == "planner_face":
        session["planner_data"].append(text.strip())  # [goal, platform, freq, face]
        session["state"] = "planner_days"
        await update.message.reply_text("📅 На какой срок нужен план (7 / 14 / 21 / 30 дней)? Напиши числом.")
        return

    if session.get("state") == "planner_days":
        session["planner_data"].append(text)

        goal, platform, freq, face, days = session["planner_data"]
        context_text = get_user_context(session)

        try:
            total_days = int(days.strip())
        except Exception:
            await update.message.reply_text("❌ Укажи количество дней числом (7, 14, 21, 30).")
            return

        await update.message.reply_text(
            f"📅 Формирую уникальный контент-план на {total_days} дней (по 5 дней за раз)..."
        )

        full_plan_parts = []
        for block_start in range(1, total_days + 1, 5):
            block_end = min(block_start + 4, total_days)
            await update.message.reply_text(f"⏳ Генерирую Дни {block_start}-{block_end}...")

            user_id = update.effective_user.id
            prev_ideas = load_used_ideas(user_id)
            used_ideas = "; ".join(prev_ideas) or "—"
            segments_str = "; ".join(session.get("audience_segments", [])) or "—"

            # ПРОМПТ... (здесь твой длинный промпт, я его не менял)
            # ВАЖНО: ВНУТРИ ПРОМПТА ЕСТЬ ДРУГАЯ ОШИБКА, СМ. ПУНКТ 2
            prompt =f"""
Ты — строгий контент-стратег и редактор. Твоя задача — создать детальный, НО лаконичный контент-план без воды,
жёстко опираясь на ввод пользователя.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Цель: {goal}
📌 Платформа: {platform}
📅 Срок: {days} дней
🗓 Частота публикаций: {freq}
👤 От чьего лица вести: {face}

=== АНАЛИЗ ЦЕЛЕВОЙ АУДИТОРИИ ===
Сегменты ЦА: {segments_str}
У пользователя несколько сегментов ЦА. В КАЖДОМ дне явно указывай, для какого сегмента сделан контент
(один или несколько). Запрещены общие советы — используй именно сегменты из ввода.

=== ОГРАНИЧЕНИЯ И ЛОГИКА ===
- Генерируй только для дней {block_start}–{block_end} включительно и перечисляй дни по порядку.
- Не повторяй темы, форматы, механики, заголовки и CTA, которые встречались ранее (список использованного): {used_ideas[-2000:]}.
  Считай повтором не только точные совпадения, но и смысловые дубликаты.
- Внутри текущего блока тоже не повторяйся.
- В каждом 5-дневном промежутке должны встретиться ВСЕ рубрики (Экспертность, Вовлечение, Личное, Кейсы, Продажи).
  Не ставь одну рубрику более 2 дней подряд.
- Контент должен развиваться по воронке: знакомство/вовлечение → прогрев/возражения → кейсы/соцдоказательства → офферы/продажи.
- Привязывай каждый день к ЭТАПУ воронки (холодная/тёплая/горячая).
- Каждый день — 2 единицы контента: «Сторис» + («Рилс» ИЛИ «Пост-карусель»).
- КАЖДЫЙ элемент дня: чёткий заголовок, 1–2 предложения идеи, один «хук», конкретный CTA, пометка [Сегмент ЦА: …].
- Избегай длиннот: каждый пункт ≤ 150 символов. Никаких «и т.д.», «можно добавить», общих фраз.
- Рекомендации по визуалу — практичные (ракурсы, кадры, сцены, текст-оверлеи), без расплывчатых «красивых фото».

=== ФОРМАТ ВЫВОДА (строго как здесь) ===
День {block_start}:
• Рубрика: <Экспертность/Вовлечение/Личное/Кейсы/Продажи> • Этап: <Холодная/Тёплая/Горячая>
• Сторис — Заголовок: <...> • Идея: <...> • Хук: <...> • CTA: <...> [Сегмент ЦА: <...>]
• Рилс/Пост — Заголовок: <...> • Формат: <Рилс|Карусель> • Идея/мини-сценарий: <...> • Хук: <...> • CTA: <...> [Сегмент ЦА: <...>]
• Визуал: <3–5 подсказок для визуала>

День {block_start+1}:
• Рубрика: <...> • Этап: <...>
• Сторис — Заголовок: <...> • Идея: <...> • Хук: <...> • CTA: <...> [Сегмент ЦА: <...>]
• Рилс/Пост — Заголовок: <...> • Формат: <...> • Идея/мини-сценарий: <...> • Хук: <...> • CTA: <...> [Сегмент ЦА: <...>]
• Визуал: <...>

=== ТРЕБОВАНИЯ К КАЧЕСТВУ ===
- Темы обязательны: из распаковки, позиционирования, продуктов и сегментов ЦА пользователя — не придумывай «в вакууме».
- Рубрики чередуй; форматы и механики варьируй (UGC, behind-the-scenes, челлендж, мини-гайд, кейс-разбор, FAQ, сравнение, миф/факт).
- Для повторных запросов от того же пользователя генерируй принципиально новые темы, сверяясь с {used_ideas[-2000:]}.
- Не повторяй ранее использованные идеи: {used_ideas[-2000:]}
- Язык: русский, деловой и дружелюбный тон.

⚖️ Соблюдай закон №38-ФЗ и №72-ФЗ от 07.04.2025: никаких запрещённых обещаний; формулировки корректные и этичные.
"""

            try:
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    temperature=0.8,
                    max_tokens=3000,
                    messages=[{"role": "user", "content": prompt}],
                )
                plan = response["choices"][0]["message"]["content"]
                new_ideas = extract_ideas_from_plan(plan)
                save_used_ideas(user_id, new_ideas)
                await send_long_message(update.effective_chat.id, plan, context)

            except Exception as e:
                print(f"Planner OpenAI Error (дни {block_start}-{block_end}):", e)
                await update.message.reply_text(
                    f"⚠️ Ошибка генерации для дней {block_start}-{block_end}."
                )
                continue

        # ЭТОТ БЛОК КОДА ДОЛЖЕН БЫТЬ НА ТОМ ЖЕ УРОВНЕ, ЧТО И 'for' ВЫШЕ
        # ВЕРОЯТНО, ОШИБКА В ОТСТУПАХ ИМЕННО ЗДЕСЬ
        session["state"] = "menu_roles"
        kb = [
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Reels",       callback_data="role_reels")],
        ]
        await update.message.reply_text("✅ Контент-план готов!", reply_markup=InlineKeyboardMarkup(kb))
        return

    # === Reels ===
    if session.get("state") == "reels_topic":
        session["reels_data"] = [text]
        session["state"] = "reels_format"
        await update.message.reply_text("2️⃣ Укажи формат: с лицом / без лица / монтаж.")
        return

    if session.get("state") == "reels_format":
        session["reels_data"].append(text)
        session["state"] = "reels_style"
        await update.message.reply_text("3️⃣ Укажи стиль: экспертный / юмор / душевный.")
        return

    if session.get("state") == "reels_style":
        session["reels_data"].append(text)
        session["state"] = "reels_music"
        await update.message.reply_text("4️⃣ Есть ли музыка или референс?")
        return

    if session.get("state") == "reels_music":
        session["reels_data"].append(text)
        topic, format_r, style, music = session["reels_data"]
        context_text = get_user_context(session)
        used_ideas = ""
        history = "\n".join(load_used_ideas(user_id)) if 'load_used_ideas' in globals() else ""

        prompt = f"""
Ты профессиональный продюсер коротких видео (Reels, TikTok, Shorts, ВК-клипы). Создай уникальный сценарий для видео по данным пользователя.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Тема ролика: {topic}  
📹 Формат: {format_r} (с лицом / без лица / монтаж)  
🎨 Стиль: {style}  
🎵 Музыка/референс: {music}  

=== ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СЦЕНАРИЯ ===
1️⃣ Хук (2–3 секунды, мощный захват внимания)  
2️⃣ Основной блок (пошаговый сценарий: текст, действия, визуал)  
3️⃣ CTA (призыв к действию: сохранить, подписаться, написать)  
4️⃣ Альтернативы: вариант для видео с лицом и без  
5️⃣ Подсказки по визуалу, монтажу, свету (конкретные советы)  

=== УСЛОВИЯ ===
- Каждый новый сценарий должен быть уникальным, отличаться от ранее сгенерированных.  
- Не повторяй идеи, хук, форматы и визуальные решения, которые уже использовались.  
- Используй разные творческие подходы: необычные углы съёмки, свежие тренды, неожиданные сюжеты.  
- Не используй ранее применённые идеи: {history[-2000:]}  

=== ТРЕБОВАНИЯ ===
– Используй сторителлинг, эмоции, провокационные или цепляющие элементы.  
– Применяй тренды 2024–2025 (быстрый хук, честная подача).  
– Добавляй новые механики, неожиданные повороты, чтобы сценарий был уникальным.  
– Делай сценарий максимально практичным и готовым к съёмке, без общих советов.  

⚖️ Соблюдай Федеральный закон №38-ФЗ «О рекламе» и №72-ФЗ от 07.04.2025:  
не используй необоснованные обещания («100% результат», «лучший», «гарантировано»),  
заменяй их корректными альтернативами («один из популярных вариантов», «подходит для…», «узнай подробнее»).

💡 Выдай сценарий в структурированном виде, готовый к съёмке, с уникальными элементами, которых не было ранее.
Не повторяй ранее использованные идеи: {history[-2000:]}
"""
        await update.message.reply_text("🎬 Генерация сценария...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}]
            )
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.effective_chat.id, result, context)
        except Exception as e:
            print("Reels Error:", e)
            await update.message.reply_text("⚠️ Ошибка генерации сценария.")

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text(
            "✅ Сценарий готов!", reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # === Fallback: показываем только когда нет активного сценария ===
    active_states = {
        "collecting_base_info", "product_decision", "collecting_more_products",
        "collecting_audience_multiple", "waiting_extra_info",
        "planner_goal", "planner_platform", "planner_frequency", "planner_face", "planner_days",
        "reels_topic", "reels_format", "reels_style", "reels_music",
    }
    if session.get("state") in active_states or str(session.get("state","")).startswith("copywriter_"):
        # игнорируем лишние сообщения во время сценариев
        return

    await update.message.reply_text("🤔 Не понял команду. Нажми /start для начала.")


# === Запуск бота ===
if __name__ == "__main__":
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот запущен! Ждём пользователей...")
    app.run_polling()
