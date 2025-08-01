import os
import sys
import sqlite3
import asyncio
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
BOT_NAME = "ContentAssistantBot"

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

# === Проверка доступа ===
def is_allowed(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    cur.execute("SELECT 1 FROM allowed_users WHERE user_id=? AND bot_name=?", (user_id, BOT_NAME))
    return cur.fetchone() is not None

# === Отключение webhook ===
async def disable_webhook():
    from telegram import Bot
    bot = Bot(BOT_TOKEN)
    await bot.delete_webhook()
    print("✅ Webhook отключен → Polling активен")

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

# === Проверка токена ===
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
    "Он поможет:\n"
    "• составить контент-план,\n"
    "• написать пост или Reels,\n"
    "• упаковать продукт.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности]"
    "(https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit) "
    "и [Договором‑офертой]"
    "(https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).\n\n"
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
            await update.message.reply_text("✅ Доступ активирован!")
        else:
            await update.message.reply_text("❌ Неверный или использованный токен.")
        return
    if not is_allowed(user_id):
        await update.message.reply_text("⛔️ Нет доступа. Купите доступ у администратора.")
        return
    await update.message.reply_text(
        WELCOME,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]])
    )

# === Callback кнопки ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_allowed(user_id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return

    session = sessions.setdefault(user_id, {
        "state": None, "step": 0, "data": {}, "products": [],
        "audience_segments": [], "planner_data": [], "reels_data": [], "copy_data": []
    })

    # --- Согласие ---
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text(
            "Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # --- Пользователь имеет основу ---
    elif query.data == "base_yes":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    # --- Нет основы ---
    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Заполнить здесь", callback_data="fill_here")],
            [InlineKeyboardButton("Использовать другой бот", callback_data="use_other_bot")]
        ]
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

    # --- Сегменты ЦА ---
    elif query.data == "add_audience_segment":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("✍️ Пришли следующий сегмент анализа ЦА.")

    elif query.data == "audience_done":
        data = session.setdefault("data", {})
        data["extra_info"] = "\n\n".join(session.get("audience_segments", []))
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]
        ]
        await query.edit_message_text(
            "✅ Анализ ЦА собран. Добавить дополнительную информацию?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # --- Доп. информация ---
    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Информация получена! Переходим к выбору помощников.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # === Меню помощников ===
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Reels", callback_data="role_reels")]
        ]
        session["state"] = "menu_roles"
        await query.edit_message_text("🤖 *Твои помощники*: выбери, кто тебе нужен👇",
                                      parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    # === Планировщик ===
    elif query.data == "role_planner":
        kb = [
            [InlineKeyboardButton("🗓 Начать сбор данных для контент-плана", callback_data="planner_start")],
            [InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]
        ]
        session["state"] = "planner_menu"
        await query.edit_message_text("📅 Я — Планировщик. Готов составить стратегию!", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "planner_start":
        session["state"] = "planner_goal"
        session["planner_data"] = []
        await query.edit_message_text("🎯 Укажи главную цель контент-плана (привлечение, прогрев, продажи и т.д.).")

# === Обработка сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    session = sessions.setdefault(user_id, {"state": None, "step": 0, "data": {}, "products": []})
    text = update.message.text
    print(f"📩 Сообщение от {user_id}: {text}")

    # === Сбор информации ===
    if session["state"] == "collecting_base_info":
        step = session["step"]
        session["data"].setdefault("info", []).append(text)
        session["step"] += 1

        if step == 2:
            kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
                  [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
            await update.message.reply_text("🔥 Отлично! Хочешь добавить ещё продукт?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            return

        if session["step"] < len(INFO_QUESTIONS):
            await update.message.reply_text(INFO_QUESTIONS[session["step"]])
        else:
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
            await update.message.reply_text("Хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra"

    elif session["state"] == "collecting_more_products":
        session["products"].append(text)
        kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
              [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
        await update.message.reply_text("✅ Продукт добавлен. Добавить ещё?",
                                        reply_markup=InlineKeyboardMarkup(kb))

    elif session["state"] == "collecting_audience_multiple":
        session["data"].setdefault("audience_segments", []).append(text)
        kb = [[InlineKeyboardButton("Добавить ещё сегмент", callback_data="add_audience_segment")],
              [InlineKeyboardButton("Закончить", callback_data="audience_done")]]
        await update.message.reply_text("✅ Сегмент добавлен. Добавить ещё?",
                                        reply_markup=InlineKeyboardMarkup(kb))

    elif session["state"] == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Доп.информация получена. Переходим к помощникам.",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "menu_roles"

    # === Планировщик (ПОЛНЫЙ ПРОМТ) ===
    elif session["state"] == "planner_goal":
        session["planner_data"] = [text]
        session["state"] = "planner_platform"
        await update.message.reply_text("2️⃣ Укажи основную соцсеть.")

    elif session["state"] == "planner_platform":
        session["planner_data"].append(text)
        session["state"] = "planner_frequency"
        await update.message.reply_text("3️⃣ Укажи частоту публикаций.")

    elif session["state"] == "planner_frequency":
        session["planner_data"].append(text)
        session["state"] = "planner_face"
        await update.message.reply_text("4️⃣ От чьего лица вести контент? (личный / бренд)")

    elif session["state"] == "planner_face":
        session["planner_data"].append(text)
        session["state"] = "planner_days"
        await update.message.reply_text("5️⃣ На какой срок нужен план? (7 / 10 / 30 дней)")

    elif session["state"] == "planner_days":
        session["planner_data"].append(text)
        goal, platform, freq, face, days = session["planner_data"]
        context_text = get_user_context(session)

        prompt = f"""
Ты профессиональный контент-стратег. Составь подробный контент-план.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Цель: {goal}
📌 Платформа: {platform}
🗓 Частота публикаций: {freq}
👤 От чьего лица вести: {face}
📅 Срок: {days} дней

=== АНАЛИЗ ЦЕЛЕВОЙ АУДИТОРИИ ===
Пользователь передал сегменты ЦА. Для каждого дня укажи, для кого подходит контент.

=== ТРЕБОВАНИЯ ===
- Каждый день: сторис + пост/рилс/карусель
- Указывай: тему, формат, цель, CTA, идеи для сторис, визуальные подсказки
- Добавляй сегменты ЦА
- Раздели на: экспертность, вовлечение, личное, кейсы, продажи
- Привяжи к этапам воронки: холодная, тёплая, горячая аудитория
- Используй современные форматы 2024–2025
- Соблюдай законы РФ, исключи запрещённые обещания.

Формат ответа:
День 1:
• Сторис – ...
• Пост – ...
[Сегмент ЦА: ...]
"""

        await update.message.reply_text("📅 Формирую контент-план, подожди...")
        try:
            response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}])
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.effective_chat.id, result, context)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка генерации плана.")
            print("Planner Error:", e)

        session["state"] = "menu_roles"
        await update.message.reply_text("✅ План готов!",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]))

    # === Копирайтер (ПОЛНЫЙ ПРОМТ) ===
    elif session["state"].startswith("copywriter_"):
        step = session.get("step", 0)
        session["copy_data"].append(text)
        session["step"] = step + 1

        if step == 0:
            await update.message.reply_text("2️⃣ Укажи тему текста.")
        elif step == 1:
            await update.message.reply_text("3️⃣ Укажи тональность.")
        elif step == 2:
            await update.message.reply_text("4️⃣ Хочешь развернутый или краткий?")
        elif step == 3:
            goal, topic, tone, length = session["copy_data"]
            context_text = get_user_context(session)

            prompt = f"""
Ты профессиональный копирайтер и упаковщик. Создай {session['task']} для блогера/эксперта/бренда.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎯 Цель текста: {goal}
📌 Тема: {topic}
🎨 Тональность: {tone}
📝 Формат: {length}

=== ОБЯЗАТЕЛЬНО УЧИТЫВАЙ ===
- Имиджевые, вовлекающие, образовательные, продающие, прогревающие, вирусные, информационные, развлекательные форматы
- Структура: Заголовок – Вступление – Основная часть – Вывод – CTA
- Если формат = пост-карусель → используй структуру 10 слайдов (крючок, проблема, усиление, решение, 5–8 контент, CTA, оффер)
- Стиль 2024–2025: сторителлинг, вовлечение, простота, честность
- Соблюдай законы №38-ФЗ и №72-ФЗ от 07.04.2025 (без запрещённых обещаний)

Выдай текст, готовый к публикации.
"""

            await update.message.reply_text("✍️ Генерация текста...")
            try:
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}])
                result = sanitize_ad_text(response["choices"][0]["message"]["content"])
                await send_long_message(update.effective_chat.id, result, context)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка генерации текста.")
                print("Copywriter Error:", e)

            session["state"] = "menu_roles"
            await update.message.reply_text("✅ Текст готов!",
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]))

    # === Reels (ПОЛНЫЙ ПРОМТ) ===
    elif session["state"] == "reels_topic":
        session["reels_data"] = [text]
        session["state"] = "reels_format"
        await update.message.reply_text("2️⃣ Укажи формат: с лицом / без лица / монтаж.")

    elif session["state"] == "reels_format":
        session["reels_data"].append(text)
        session["state"] = "reels_style"
        await update.message.reply_text("3️⃣ Укажи стиль: экспертный / юмор / душевный.")

    elif session["state"] == "reels_style":
        session["reels_data"].append(text)
        session["state"] = "reels_music"
        await update.message.reply_text("4️⃣ Есть ли музыка или референс?")

    elif session["state"] == "reels_music":
        session["reels_data"].append(text)
        topic, format_r, style, music = session["reels_data"]
        context_text = get_user_context(session)

        prompt = f"""
Ты профессиональный продюсер коротких видео (Reels, TikTok, Shorts). Создай детализированный сценарий.

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===
{context_text}

🎬 Тема ролика: {topic}
📹 Формат: {format_r}
🎨 Стиль: {style}
🎵 Музыка/референс: {music}

=== СТРУКТУРА СЦЕНАРИЯ ===
1️⃣ Хук (2–3 секунды, сильный захват внимания)
2️⃣ Основной блок (пошагово: действия, визуал, текст)
3️⃣ CTA (призыв: сохранить, подписаться, написать)
4️⃣ Альтернативы: для видео с лицом и без
5️⃣ Подсказки по визуалу, монтажу, свету

=== ТРЕБОВАНИЯ ===
- Используй сторителлинг, эмоции, провокационные элементы
- Применяй тренды 2024–2025 (быстрый хук, честная подача)
- Встраивай мягкий оффер, если уместно
- Соблюдай законы РФ: без фраз «100%», «лучший» — используй корректные альтернативы

Выдай сценарий, готовый к съёмке.
"""

        await update.message.reply_text("🎬 Генерация сценария...")
        try:
            response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}])
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.effective_chat.id, result, context)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка генерации сценария.")
            print("Reels Error:", e)

        session["state"] = "menu_roles"
        await update.message.reply_text("✅ Сценарий готов!",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Выбрать другого помощника", callback_data="roles_menu")]]))

# === Хендлер неизвестных сообщений ===
async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤔 Не понял команду. Нажми /start для начала.")

# === MAIN (Render-friendly) ===
async def main():
    await disable_webhook()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # === Регистрируем все хендлеры ===
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL, any_message))

    print("🚀 Бот запущен! Ждём пользователей...")
    await app.run_polling(close_loop=False)  # 🔥 ключ для Render

# === Запуск ===
if __name__ == "__main__":
    asyncio.run(main())
