import os
import secrets
import json
import re
from dotenv import load_dotenv

import psycopg
from psycopg.rows import dict_row

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import openai

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

# === Подключение к PostgreSQL (psycopg v3) ===
conn = psycopg.connect(DATABASE_URL, sslmode="require", autocommit=True, row_factory=dict_row)
cur = conn.cursor()

# === Приложение PTB 21 ===
app = Application.builder().token(BOT_TOKEN).build()

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
# --- Храним контекст пользователя (распаковка, позиционирование, продукты, ЦА) ---
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS user_context (
        user_id BIGINT PRIMARY KEY,
        data JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT now()
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

# === Утилиты контента/постобработки ===
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

async def send_long_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    MAX = 4000
    for i in range(0, len(text), MAX):
        await context.bot.send_message(chat_id=chat_id, text=text[i : i + MAX])

# === Хелперы для проверки полноты дней в плане ===
def extract_day_numbers(text: str) -> set[int]:
    # Ищем заголовки вида "День 1:" / "День 12:"
    return set(int(m.group(1)) for m in re.finditer(r"День\s+(\d+)\s*:", text, flags=re.I))

def format_missing_days(missing: list[int]) -> str:
    # "12, 13, 14" → строка для строгого запроса
    return ", ".join(str(x) for x in missing)

# === Утилиты доступа/контекста в БД ===
def save_user_context_pg(user_id: int, session: dict):
    """Сохраняем ключевой контекст пользователя в PostgreSQL."""
    payload = {
        "info": session.get("data", {}).get("info"),
        "products": session.get("products"),
        "audience_segments": session.get("audience_segments"),
        "unpacking": session.get("unpacking"),
        "positioning": session.get("positioning"),
    }
    cur.execute(
        "INSERT INTO user_context(user_id, data, updated_at) VALUES (%s, %s::jsonb, now()) "
        "ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
        (user_id, json.dumps(payload))
    )

def load_user_context_pg(user_id: int) -> dict | None:
    """Читаем контекст из PostgreSQL (или None, если нет записей)."""
    cur.execute("SELECT data FROM user_context WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    return row["data"] if row else None

def is_allowed(user_id: int, bot_name: str) -> bool:
    if user_id == ADMIN_ID:
        return True
    cur.execute(
        "SELECT 1 FROM allowed_users WHERE user_id=%s AND bot_name=%s LIMIT 1",
        (user_id, bot_name),
    )
    return cur.fetchone() is not None

def create_token(user_id: int, bot_name: str) -> str:
    token = secrets.token_urlsafe(8)
    cur.execute(
        "INSERT INTO tokens(token, bot_name, user_id) VALUES(%s, %s, %s) ON CONFLICT DO NOTHING",
        (token, bot_name, user_id),
    )
    return token

def validate_token(token: str, bot_name: str, user_id: int) -> bool:
    cur.execute(
        "SELECT user_id FROM tokens WHERE token=%s AND bot_name=%s",
        (token, bot_name),
    )
    row = cur.fetchone()
    if row and row["user_id"] == user_id:
        # Разрешаем доступ пользователю и удаляем токен (одноразовый)
        cur.execute(
            "INSERT INTO allowed_users(user_id, bot_name) VALUES(%s, %s) ON CONFLICT DO NOTHING",
            (user_id, bot_name),
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
и [Договором-офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).

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
        if validate_token(args[0], BOT_NAME, user_id):
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
    if is_allowed(user_id, BOT_NAME):
        await update.message.reply_text(
            WELCOME,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
            ),
        )
        return

    await update.message.reply_text("Привет! Для доступа нужен токен. Обратись к админу/главному боту.")

# === Генерация токена (для админа) ===
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

    token = create_token(target_id, BOT_NAME)
    await update.message.reply_text(
        f"✅ Токен для {target_id}: {token}\nhttps://t.me/{BOT_NAME}?start={token}"
    )

# === Кнопочные сценарии ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_allowed(user_id, BOT_NAME):
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

    # --- Сбор продуктов (альтерн. поток) ---
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
        # Сохраняем контекст (ЦА завершена)
        save_user_context_pg(user_id, session)

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
        # Сохраняем контекст (если ранее уже была extra_info/сегменты)
        save_user_context_pg(user_id, session)

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

    # === Помощники ===
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

# === ЕДИНЫЙ обработчик текстовых сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id, BOT_NAME):
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
            # сохраняем контекст после добавления продукта
            save_user_context_pg(user_id, session)

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
            # Первый сегмент ЦА -> запускаем цикл сегментов
            session.setdefault("audience_segments", []).append(text)
            kb = [
                [InlineKeyboardButton("Да",  callback_data="add_audience_segment")],
                [InlineKeyboardButton("Нет", callback_data="audience_done")],
            ]
            session["state"] = "collecting_audience_multiple"
            await update.message.reply_text(
                "✅ Сегмент #1 добавлен. Хочешь прислать ещё сегмент ЦА? (Да/Нет)",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return

    # Добавление доп. продуктов (альтернативный поток)
    if session.get("state") == "collecting_more_products":
        session.setdefault("products", []).append(text)
        # сохраняем контекст после добавления продукта
        save_user_context_pg(user_id, session)

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
        session.setdefault("audience_segments", []).append(text)
        kb = [
            [InlineKeyboardButton("Да",  callback_data="add_audience_segment")],
            [InlineKeyboardButton("Нет", callback_data="audience_done")],
        ]
        await update.message.reply_text(
            "✅ Сегмент добавлен. Хочешь прислать ещё сегмент ЦА? (Да/Нет)",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    # Доп.инфа
    if session.get("state") == "waiting_extra_info":
        session.setdefault("data", {})["extra_info"] = text
        # сохраняем контекст после ввода доп.информации
        save_user_context_pg(user_id, session)

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

            used_ideas = ""

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
- Не используй ранее применённые идеи: {used_ideas}  

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
    if session.get("state") == "planner_goal":
        session["planner_data"] = [text]
        session["state"] = "planner_platform"
        await update.message.reply_text("2️⃣ Укажи основную соцсеть.")
        return

    if session.get("state") == "planner_platform":
        session["planner_data"].append(text)
        session["state"] = "planner_frequency"
        await update.message.reply_text("3️⃣ Укажи частоту публикаций.")
        return

    if session.get("state") == "planner_frequency":
        session["planner_data"].append(text)
        session["state"] = "planner_face"
        await update.message.reply_text("4️⃣ От чьего лица вести (личный / бренд)?")
        return

    if session.get("state") == "planner_face":
        session["planner_data"].append(text)
        session["state"] = "planner_days"
        await update.message.reply_text(
            "5️⃣ На какой срок нужен план (7 / 14 / 21 / 30 дней)? Укажи числом."
        )
        return

    if session.get("state") == "planner_days":
        session["planner_data"].append(text)

        goal, platform, freq, face, days = session["planner_data"]
        context_text = get_user_context(session)

        try:
            total_days = int(days.strip())
        except Exception:
            await update.message.reply_text(
                "❌ Укажи количество дней числом (7, 14, 21, 30)."
            )
            return

        # === ВОССТАНОВЛЕНИЕ КОНТЕКСТА, если перезапуск/деплой очистил память ===
        if not session.get("data") or not session.get("audience_segments"):
            restored = load_user_context_pg(update.effective_user.id)
            if restored:
                session.setdefault("data", {})["info"] = restored.get("info") or []
                session["products"] = restored.get("products") or []
                session["audience_segments"] = restored.get("audience_segments") or []
                session["unpacking"] = restored.get("unpacking")
                session["positioning"] = restored.get("positioning")

        await update.message.reply_text(
            f"📅 Формирую уникальный контент-план на {total_days} дней (по 3 дня за раз)..."
        )

        previous_context = ""
        all_results = []

        # Справочная строка по сегментам (если есть)
        segments = session.get("audience_segments", [])
        segments_str = " | ".join(segments) if segments else "—"
        used_ideas = ""

        try:
            BLOCK_SIZE = 3  # меньше блока -> стабильнее влезает в токены
            for block_start in range(1, total_days + 1, BLOCK_SIZE):
                block_end = min(block_start + (BLOCK_SIZE - 1), total_days)

                prompt = f"""
Ты контент-планировщик. Твоя задача – создать развернутый, детализированный, уникальный контент-план.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Цель: {goal}
📌 Платформа: {platform}
📅 Срок: {days} дней
🗓 Частота публикаций: {freq}
👤 От чьего лица вести: {face}
🎯 Сегменты ЦА (суммарно): {segments_str}

=== АНАЛИЗ ЦЕЛЕВОЙ АУДИТОРИИ ===
Сегменты ЦА: {segments_str}
У пользователя несколько сегментов ЦА. В КАЖДОМ дне явно указывай, для какого сегмента сделан контент
(один или несколько). Запрещены общие советы — используй именно сегменты из ввода.

=== ОГРАНИЧЕНИЯ И ЛОГИКА ===
- Генерируй только для дней {block_start}–{block_end} включительно и перечисляй дни по порядку.
- Не повторяй темы, форматы, механики, заголовки и CTA, которые встречались ранее (список использованного): {used_ideas}.
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

...
День {block_end}:
• Рубрика: <...> • Этап: <...>
• Сторис — Заголовок: <...> • Идея: <...> • Хук: <...> • CTA: <...> [Сегмент ЦА: <...>]
• Рилс/Пост — Заголовок: <...> • Формат: <...> • Идея/мини-сценарий: <...> • Хук: <...> • CTA: <...> [Сегмент ЦА: <...>]
• Визуал: <...>

=== ТРЕБОВАНИЯ К КАЧЕСТВУ ===
- Темы обязательны: из распаковки, позиционирования, продуктов и сегментов ЦА пользователя — не придумывай «в вакууме».
- Рубрики чередуй; форматы и механики варьируй (UGC, behind-the-scenes, челлендж, мини-гайд, кейс-разбор, FAQ, сравнение, миф/факт).
- Для повторных запросов от того же пользователя генерируй принципиально новые темы, сверяясь с {used_ideas}.
- Не повторяй ранее использованные идеи: {used_ideas}
- Язык: русский, деловой и дружелюбный тон.

⚖️ Соблюдай закон №38-ФЗ и №72-ФЗ от 07.04.2025: никаких запрещённых обещаний; формулировки корректные и этичные.
"""

                await update.message.reply_text(
                    f"⏳ Генерирую Дни {block_start}-{block_end}..."
                )

                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        temperature=0.8,
                        max_tokens=2000,
                        messages=[{"role": "user", "content": prompt}],
                    )

                    result = sanitize_ad_text(
                        response["choices"][0]["message"]["content"]
                    )

                    # Проверяем, что модель выдала все дни блока
                    covered = extract_day_numbers(result)
                    expected = set(range(block_start, block_end + 1))
                    missing = sorted(expected - covered)

                    if missing:
                        await update.message.reply_text(
                            f"⚠️ В блоке {block_start}-{block_end} не хватило дней: {', '.join(map(str, missing))}. Догенерирую..."
                        )
                        strict_prompt = f"""
Сгенерируй СТРОГО для дней: {format_missing_days(missing)}.
Требования:
- На каждый день обязателен заголовок вида "День N:" (ровно так).
- Не повторяй уже выданные дни.
- Формат и требования те же, что в предыдущем запросе.
"""
                        retry = openai.ChatCompletion.create(
                            model="gpt-3.5-turbo",
                            temperature=0.7,
                            max_tokens=900,
                            messages=[
                                {"role": "user", "content": prompt},
                                {"role": "user", "content": strict_prompt},
                            ],
                        )
                        retry_text = sanitize_ad_text(retry["choices"][0]["message"]["content"])
                        result += "\n\n" + retry_text

                    previous_context += f"\n{result}"
                    all_results.append(result)
                    await send_long_message(update.effective_chat.id, result, context)

                except Exception as e:
                    print(f"Planner OpenAI Error (дни {block_start}-{block_end}):", e)
                    await update.message.reply_text(
                        f"⚠️ Ошибка генерации для дней {block_start}-{block_end}."
                    )

        except Exception as e:
            print("Planner Fatal Error:", e)
            await update.message.reply_text(
                "❌ Ошибка при генерации плана. Попробуй ещё раз."
            )

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]
        await update.message.reply_text(
            "✅ Контент-план готов!", reply_markup=InlineKeyboardMarkup(kb)
        )
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
- Не используй ранее применённые идеи: {used_ideas}  

=== ТРЕБОВАНИЯ ===
– Используй сторителлинг, эмоции, провокационные или цепляющие элементы.  
– Применяй тренды 2024–2025 (быстрый хук, честная подача).  
– Добавляй новые механики, неожиданные повороты, чтобы сценарий был уникальным.  
– Делай сценарий максимально практичным и готовым к съёмке, без общих советов.  

⚖️ Соблюдай Федеральный закон №38-ФЗ «О рекламе» и №72-ФЗ от 07.04.2025:  
не используй необоснованные обещания («100% результат», «лучший», «гарантировано»),  
заменяй их корректными альтернативами («один из популярных вариантов», «подходит для…», «узнай подробнее»).

💡 Выдай сценарий в структурированном виде, готовый к съёмке, с уникальными элементами, которых не было ранее.
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

    # === Fallback ===
    await update.message.reply_text("🤔 Не понял команду. Нажми /start для начала.")

# === Запуск бота ===
if __name__ == "__main__":
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот запущен! Ждём пользователей...")
    app.run_polling()
