import os
import sys
import sqlite3
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import openai
import secrets

print(">>> Бот загружен, файл bot.py исполняется")

# === Настройки ===
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BOT_NAME = "content_helper_assist_bot"

# === SQLite ===
conn = sqlite3.connect("db.sqlite", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS allowed_users (user_id INTEGER, bot_name TEXT, UNIQUE(user_id, bot_name))")
cur.execute("CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, bot_name TEXT, user_id INTEGER)")
conn.commit()
cur.execute("INSERT OR IGNORE INTO allowed_users(user_id, bot_name) VALUES(?, ?)", (ADMIN_ID, BOT_NAME))
conn.commit()

# === Сессии ===
sessions = {}

# === Утилиты ===
def get_user_context(session):
    return "\n".join([f"{k}: {v}" for k, v in session.get("data", {}).items()]) if session else "Нет данных"

def sanitize_ad_text(text):
    return text.replace("100%", "почти наверняка").replace("лучший", "один из лучших")

async def send_long_message(chat_id, text, context):
    MAX = 4000
    for i in range(0, len(text), MAX):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+MAX])

def is_allowed(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    cur.execute("SELECT 1 FROM allowed_users WHERE user_id=? AND bot_name=?", (user_id, BOT_NAME))
    return cur.fetchone() is not None

# === Генерация токена ===
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
    token = secrets.token_hex(4)
    cur.execute("INSERT INTO tokens(token, bot_name, user_id) VALUES(?, ?, ?)", (token, BOT_NAME, target_id))
    conn.commit()
    await update.message.reply_text(f"✅ Токен для {target_id}: {token}\nhttps://t.me/{BOT_NAME}?start={token}")

def validate_token(token: str, user_id: int) -> bool:
    cur.execute("SELECT user_id FROM tokens WHERE token=? AND bot_name=?", (token, BOT_NAME))
    row = cur.fetchone()
    if row and row[0] == user_id:
        cur.execute("INSERT OR IGNORE INTO allowed_users(user_id, bot_name) VALUES(?, ?)", (user_id, BOT_NAME))
        cur.execute("DELETE FROM tokens WHERE token=?", (token,))
        conn.commit()
        return True
    return False

# === Приветствие ===
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент».\n\n"
    "Он поможет:\n• составить контент-план,\n• написать пост или Reels,\n• упаковать продукт.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit) "
    "и [Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

INFO_QUESTIONS = [
    "✍️ Пришли свою распаковку личности и экспертности.",
    "🔥 Отлично! Теперь пришли своё позиционирование.",
    "✅ Теперь пришли характеристику продукта/услуги.",
    "📌 Пришли анализ твоей ЦА."
]

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if user_id == ADMIN_ID:
        await update.message.reply_text("👑 Привет, админ! Полный доступ.")
    if args:
        if validate_token(args[0], user_id):
            await update.message.reply_text("✅ Доступ активирован! Добро пожаловать!")
            # 👉 сразу отправляем приветствие и кнопку
            await update.message.reply_text(
                WELCOME,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
                )
            )
        else:
            await update.message.reply_text("❌ Неверный или использованный токен.")
        return

# === Callback кнопки ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_allowed(user_id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return

    session = sessions.setdefault(user_id, {
        "state": "", "step": 0, "data": {}, "products": [], "audience_segments": [], "planner_data": [], "reels_data": [], "copy_data": []
    })

    # --- Согласие ---
    if query.data == "agree":
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "base_yes":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    elif query.data == "base_no":
        kb = [[InlineKeyboardButton("Заполнить здесь", callback_data="fill_here")],
              [InlineKeyboardButton("Использовать другой бот", callback_data="use_other_bot")]]
        await query.edit_message_text("Давай соберём основу прямо здесь:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "fill_here":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Бот по распаковке в разработке.")

    # --- Сбор продуктов ---
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
        session["data"]["extra_info"] = "\n\n".join(session.get("audience_segments", []))
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
        await query.edit_message_text("✅ Анализ ЦА собран. Добавить дополнительную информацию?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Информация получена! Переходим к выбору помощников.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "roles_menu":
        session["state"] = "menu_roles"
        kb = [
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("🤖 *Твои помощники*: выбери, кто тебе нужен👇",
                                      parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    # === Помощники ===
    elif query.data == "role_planner":
        session["state"] = "planner_menu"
        kb = [[InlineKeyboardButton("🗓 Начать сбор данных", callback_data="planner_start")],
              [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]
        await query.edit_message_text("📅 Я — Планировщик. Готов составить стратегию!", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "planner_start":
        session["state"] = "planner_goal"
        session["planner_data"] = []
        await query.edit_message_text("🎯 Укажи главную цель контент-плана (привлечение, прогрев, продажи и т.д.).")

    elif query.data == "role_copywriter":
        session["state"] = "copywriter_menu"
        kb = [
            [InlineKeyboardButton("📝 Пост", callback_data="copy_post")],
            [InlineKeyboardButton("📊 Карусель", callback_data="copy_carousel")],
            [InlineKeyboardButton("🎁 Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("📦 Упаковка продукта", callback_data="copy_package")],
            [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]
        ]
        await query.edit_message_text("✍️ Я — Копирайтер. Что создаём?", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith("copy_"):
        task = query.data.split("_", 1)[1]
        session["state"] = f"copywriter_{task}"
        session["task"] = task
        session["step"] = 0
        session["copy_data"] = []
        await query.edit_message_text("1️⃣ Укажи цель текста (имиджевая, вовлекающая, продающая, образовательная).")

    elif query.data == "role_reels":
        session["state"] = "reels_menu"
        kb = [[InlineKeyboardButton("🎬 Начать сценарий Reels", callback_data="reels_start")],
              [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]
        await query.edit_message_text("🎥 Я — Продюсер Reels. Что будем снимать?", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "reels_start":
        session["state"] = "reels_topic"
        session["reels_data"] = []
        await query.edit_message_text("🎬 Укажи тему и цель ролика.")

# === Обработка сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ У вас нет доступа.")
        return

    session = sessions.setdefault(user_id, {"state": "", "step": 0, "data": {}, "products": []})
    text = update.message.text

    # === Сбор основной информации ===
    if session.get("state") == "collecting_base_info":
        step = session["step"]
        session["data"].setdefault("info", []).append(text)
        session["step"] += 1

        if session["step"] == 3:
            kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
                  [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
            await update.message.reply_text("🔥 Отлично! Хочешь добавить ещё продукт?", reply_markup=InlineKeyboardMarkup(kb))
            return

        if session["step"] < len(INFO_QUESTIONS):
            await update.message.reply_text(INFO_QUESTIONS[session["step"]])
        else:
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
            await update.message.reply_text("Хочешь отправить дополнительную информацию по ЦА?", reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra"

    elif session.get("state") == "collecting_more_products":
        session["products"].append(text)
        kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
              [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
        await update.message.reply_text("✅ Продукт добавлен. Добавить ещё?", reply_markup=InlineKeyboardMarkup(kb))

    elif session.get("state") == "collecting_audience_multiple":
        session["data"].setdefault("audience_segments", []).append(text)
        kb = [[InlineKeyboardButton("Добавить ещё сегмент", callback_data="add_audience_segment")],
              [InlineKeyboardButton("Закончить", callback_data="audience_done")]]
        await update.message.reply_text("✅ Сегмент добавлен. Добавить ещё?", reply_markup=InlineKeyboardMarkup(kb))

    elif session.get("state") == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Доп.информация получена. Переходим к помощникам.", reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "menu_roles"

    # === Копирайтер ===
    elif session.get("state", "").startswith("copywriter_"):
        step = session.get("step", 0)
        session["copy_data"].append(text)
        session["step"] = step + 1

        if step == 0:
            await update.message.reply_text("2️⃣ Укажи тему текста.")
        elif step == 1:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
        elif step == 2:
            await update.message.reply_text("4️⃣ Хочешь развернутый текст или краткий, но ёмкий?")
        elif step == 3:
            goal, topic, tone, length = session["copy_data"]
            context_text = get_user_context(session)

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
                   max_tokens=4000,  # 🟢 увеличен лимит
                   temperature=0.7,
                   messages=[{"role": "user", "content": prompt + "\n\n⚠️ ВАЖНО: Не используй слова «и так далее». Выдай все {days} дней полностью, даже если ответ получится длинным. Разбей вывод на все дни по структуре."}]
)
                result = sanitize_ad_text(response["choices"][0]["message"]["content"])
                await send_long_message(update.effective_chat.id, result, context)
            except Exception as e:
                print("Copywriter Error:", e)
                await update.message.reply_text("⚠️ Ошибка генерации текста.")

            session["state"] = "menu_roles"
            kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Текст готов!", reply_markup=InlineKeyboardMarkup(kb))

    # === Планировщик ===
    elif session.get("state") == "planner_goal":
        # ✅ сбрасываем старые данные, чтобы не было ошибки распаковки
        session["planner_data"] = [text]
        session["state"] = "planner_platform"
        await update.message.reply_text("2️⃣ Укажи основную соцсеть.")

    elif session.get("state") == "planner_platform":
        session["planner_data"].append(text)
        session["state"] = "planner_frequency"
        await update.message.reply_text("3️⃣ Укажи частоту публикаций.")

    elif session.get("state") == "planner_frequency":
        session["planner_data"].append(text)
        session["state"] = "planner_face"
        await update.message.reply_text("4️⃣ От чьего лица вести (личный / бренд)?")

    elif session.get("state") == "planner_face":
        session["planner_data"].append(text)
        session["state"] = "planner_days"
        await update.message.reply_text("5️⃣ На какой срок нужен план (7 / 14 / 21 / 30 дней)? Укажи числом.")

    elif session.get("state") == "planner_days":
        session["planner_data"].append(text)

        # ✅ теперь тут гарантированно 5 элементов
        goal, platform, freq, face, days = session["planner_data"]
        context_text = get_user_context(session)

        try:
            total_days = int(days.strip())
        except:
            await update.message.reply_text("❌ Укажи количество дней числом (7, 14, 21, 30).")
            return

        await update.message.reply_text(f"📅 Формирую уникальный контент-план на {total_days} дней (по 5 дней за раз)...")

        previous_context = ""   # хранит ранее сгенерированные идеи
        all_results = []        # список для всех блоков

        try:  # 🔹 ВНЕШНИЙ try — ловит общие ошибки всего процесса
            for block_start in range(1, total_days + 1, 5):
                block_end = min(block_start + 4, total_days)

                prompt = f"""
Ты контент-планировщик. Твоя задача – создать развернутый, детализированный, уникальный контент-план.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Цель: {goal}
📌 Платформа: {platform}
📅 Срок: {days} дней
🗓 Частота публикаций: {freq}
👤 От чьего лица вести: {face}

=== АНАЛИЗ ЦЕЛЕВОЙ АУДИТОРИИ ===
Пользователь прислал несколько сегментов ЦА. Для каждого дня указывай, для какого сегмента подходит контент (или для нескольких). Обязательно используй данные сегментов, а не пиши общие советы.

=== УСЛОВИЯ ===
- Генерируй только для Дней {block_start}–{block_end}.
- НЕ повторяй темы, идеи, CTA и сегменты ЦА, которые уже были в предыдущих блоках.
- Каждый новый блок должен быть полностью уникальным, добавлять новые форматы, рубрики, механики.
- Контент должен развиваться: первые блоки – знакомство, вовлечение, экспертность; следующие – прогрев, кейсы, продажи.

=== ТРЕБОВАНИЯ К ПЛАНУ ===
- Выдай контент полностью для этих дней, без сокращений и "и так далее"
- НЕ повторяй темы, форматы и идеи, которые уже использовались ранее
- Каждый день обязан быть уникальным и отличаться от предыдущих
– Каждый день должен включать: сторис + (или рилс / рилс + пост-карусель)
– Укажи для каждого дня: тему, формат, цель, CTA, идеи сторис, визуальные подсказки
– Раздели контент по рубрикатору: экспертность, вовлечение, личное, кейсы, продажи
– Привяжи каждый день к этапу воронки: холодная, тёплая, горячая аудитория
– Добавляй пометку [Сегмент ЦА: ...] для каждого элемента контента
– Убедись, что дни идут строго по порядку: {block_start}, {block_start+1}, {block_start+2} ... {block_end}.

=== ФОРМАТ ВЫВОДА ===
День {block_start}:
• Сторис – тема, идея, CTA [Сегмент ЦА: сегмент1]
• Рилс/Пост – тема, формат, краткий сценарий, CTA [Сегмент ЦА: сегмент2]

День {block_start+1}:
• …

=== СПЕЦИФИКА ===
– План должен быть практичным, а не общими советами
– Используй тренды 2024–2025: Reels, сторис, интерактивные карусели, behind-the-scenes, UGC
– Добавляй новые идеи для визуала, вовлечения и механик
– В каждом блоке добавляй НОВЫЕ рубрики и форматы, которых не было в предыдущих блоках

⚖️ Соблюдай закон №38-ФЗ и №72-ФЗ от 07.04.2025, исключи запрещённые обещания, используй корректные формулировки.

⚠️ ВАЖНО: 
– Не повторяй темы, CTA, форматы и идеи, которые уже использовались ранее.  
– Каждый новый блок обязан быть уникальным, добавлять новые рубрики, примеры, сюжеты и механики.  
– Делай постепенное развитие контента: от знакомства и вовлечения – к прогреву и продажам.  
– Используй разные сегменты ЦА для каждого дня, чтобы избежать повторов.  
– Привязывай каждый новый день к предыдущему (контент должен развиваться, а не быть случайным).  

Ранее использованные идеи: {used_ideas}
"""
                
try:  # Внешний try – оборачивает весь процесс генерации плана
    await update.message.reply_text(f"⏳ Генерирую Дни {block_start}-{block_end}...")

    for block_start in range(1, int(days) + 1, 5):
        block_end = min(block_start + 4, int(days))

        try:  # Внутренний try – только для OpenAI запроса
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=0.8,
                max_tokens=3500,
                messages=[{"role": "user", "content": prompt}]
            )

            result = sanitize_ad_text(response["choices"][0]["message"]["content"])

            # ✅ сохраняем, чтобы избежать повторов в следующих блоках
            previous_context += f"\n{result}"
            all_results.append(result)

            # ✅ отправляем пользователю сразу кусками
            await send_long_message(update.effective_chat.id, result, context)

        except Exception as e:  # Ошибка только в одном блоке
            print(f"Planner OpenAI Error (дни {block_start}-{block_end}):", e)
            await update.message.reply_text(f"⚠️ Ошибка генерации для дней {block_start}–{block_end}.")

except Exception as e:  # Общая ошибка всего процесса
    print("Planner Fatal Error:", e)
    await update.message.reply_text("❌ Ошибка при генерации плана. Попробуй ещё раз.")

# ✅ После генерации всех блоков – возвращаем пользователя к меню ролей
session["state"] = "menu_roles"
kb = [[InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]
await update.message.reply_text("✅ Контент-план готов!", reply_markup=InlineKeyboardMarkup(kb))

    # === Reels ===
    elif session.get("state") == "reels_topic":
        session["reels_data"] = [text]
        session["state"] = "reels_format"
        await update.message.reply_text("2️⃣ Укажи формат: с лицом / без лица / монтаж.")

    elif session.get("state") == "reels_format":
        session["reels_data"].append(text)
        session["state"] = "reels_style"
        await update.message.reply_text("3️⃣ Укажи стиль: экспертный / юмор / душевный.")

    elif session.get("state") == "reels_style":
        session["reels_data"].append(text)
        session["state"] = "reels_music"
        await update.message.reply_text("4️⃣ Есть ли музыка или референс?")

    elif session.get("state") == "reels_music":
        session["reels_data"].append(text)
        topic, format_r, style, music = session["reels_data"]
        context_text = get_user_context(session)

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
            response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}])
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.effective_chat.id, result, context)
        except Exception as e:
            print("Reels Error:", e)
            await update.message.reply_text("⚠️ Ошибка генерации сценария.")

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Сценарий готов!", reply_markup=InlineKeyboardMarkup(kb))

# === Общий хендлер для неизвестных сообщений ===
async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ У вас нет доступа.")
        return
    await update.message.reply_text("🤔 Не понял команду. Нажми /start для начала.")

# === Запуск бота ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL, any_message))

    print("🚀 Бот запущен! Ждём пользователей...")
    app.run_polling()
