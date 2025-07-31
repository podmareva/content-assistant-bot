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

print(">>> Бот загружен, файл bot.py исполняется")

# === Настройки ===
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_NAME = "ContentAssistantBot"

# === SQLite для токенов ===
conn = sqlite3.connect("db.sqlite", check_same_thread=False)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS allowed_users(user_id INTEGER, bot_name TEXT)")
cur.execute("CREATE TABLE IF NOT EXISTS tokens(token TEXT, bot_name TEXT, user_id INTEGER)")
conn.commit()

# === Проверка доступа ===
def is_allowed(user_id):
    if user_id == ADMIN_ID:  # ✅ Админ всегда имеет доступ
        return True
    cur.execute("SELECT 1 FROM allowed_users WHERE user_id=? AND bot_name=?", (user_id, BOT_NAME))
    return cur.fetchone() is not None

# === Генерация токена (только для админа) ===
import secrets
async def gentoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Нет прав.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Используй: /gentoken user_id")
        return
    target_id = int(context.args[0])
    token = secrets.token_hex(4)
    cur.execute("INSERT INTO tokens(token, bot_name, user_id) VALUES(?, ?, ?)", (token, BOT_NAME, target_id))
    conn.commit()
    link = f"https://t.me/{BOT_NAME}?start={token}"
    await update.message.reply_text(f"✅ Сгенерирован токен:\n{token}\n🔗 Ссылка: {link}")

# === Сбор контекста пользователя ===
def get_user_context(session):
    info_parts = session.get("data", {}).get("info", [])
    products = session.get("products", [])
    extra_info = session.get("data", {}).get("extra_info", "")

    unpacking = info_parts[0] if len(info_parts) > 0 else ""
    positioning = info_parts[1] if len(info_parts) > 1 else ""
    product_desc = "; ".join(products) if products else (info_parts[2] if len(info_parts) > 2 else "")
    audience = info_parts[3] if len(info_parts) > 3 else ""
    # Стиль берем из распаковки и позиционирования
    style = f"Стиль: основывается на {unpacking} и {positioning}"

    return (
        f"📌 Распаковка личности: {unpacking}\n"
        f"📌 Позиционирование: {positioning}\n"
        f"📌 Продукты/услуги: {product_desc}\n"
        f"📌 Анализ ЦА: {audience}\n"
        f"📌 Доп.информация: {extra_info}"
        f"🎨 Стиль пользователя: {style}\n"
    )

# === Очистка текста от запрещенных фраз ===
def sanitize_ad_text(text):
    banned = ["100% результат", "лучший", "гарантировано"]
    for w in banned:
        text = text.replace(w, "один из популярных вариантов")
    return text

# === Отправка длинных сообщений кусками ===
async def send_long_message(chat, text):
    for i in range(0, len(text), 3800):
        await chat.send_message(text[i:i + 3800])

# === Сессии пользователей ===
sessions = {}

# === Вопросы для сбора информации ===
INFO_QUESTIONS = [
    "✍️ Пришли свою распаковку личности и экспертности.\n💡 Это описание твоих ценностей, опыта и уникальности.",
    "🔥 Отлично! Теперь пришли своё позиционирование.\n💡 Чем ты занимаешься и для кого?",
    "✅ Теперь пришли краткую характеристику продукта/услуги.\n💡 Опиши, что ты предлагаешь, чем это полезно клиенту.",
    "📌 Пришли анализ твоей ЦА.\n💡 Опиши, кто твоя аудитория, их боли, страхи, желания."
]

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    # --- Проверка токена ---
    if args:
        token = args[0]
        cur.execute("SELECT user_id FROM tokens WHERE token=? AND bot_name=?", (token, BOT_NAME))
        row = cur.fetchone()
        if row and row[0] == user_id:
            cur.execute("INSERT INTO allowed_users(user_id, bot_name) VALUES(?, ?)", (user_id, BOT_NAME))
            cur.execute("DELETE FROM tokens WHERE token=?", (token,))
            conn.commit()
            await update.message.reply_text("✅ Доступ активирован! Можешь работать.")
        else:
            await update.message.reply_text("❌ Неверный или использованный токен.")
        return

    # --- Проверка доступа ---
    if not is_allowed(user_id):
        await update.message.reply_text("❌ У вас нет доступа. Купите доступ у администратора.")
        return

    # --- Приветствие ---
    keyboard = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(
        "👋 Привет! Ты в боте «Контент-ассистент».\n\n"
        "Он поможет:\n"
        "• составить контент-план\n"
        "• написать пост или Reels\n"
        "• упаковать продукт\n\n"
        "🔐 Чтобы начать, подтверди согласие с "
        "[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true) и "
        "[Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true).\n\n"
        "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
    )

# === button_handler ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    if not is_allowed(user_id):
        await update.callback_query.answer("❌ У вас нет доступа.")
        return

    query = update.callback_query
    await query.answer()

    session = sessions.setdefault(user_id, {"state": None, "step": 0, "data": {}, "products": []})
    
    sessions[cid] = {
        "stage": "welcome",
        "answers": [],
        "product_answers": [],
        "products": []
    }
    kb = [[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await ctx.bot.send_message(chat_id=cid, text=WELCOME, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    
    # --- Согласие ---
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # --- Пользователь уже имеет основу ---
    elif query.data == "base_yes":
        session["state"] = "collecting_base_info"
        session["step"] = 0
        session["data"] = {"info": [], "products": []}
        await query.edit_message_text(INFO_QUESTIONS[0])
    
    # --- После получения характеристики продукта ---
    elif query.data == "ask_more_products":
        kb = [
            [InlineKeyboardButton("Да ✅", callback_data="add_product")],
            [InlineKeyboardButton("Нет ❌", callback_data="no_more_products")]
        ]
        await query.edit_message_text("🛍️ У тебя есть ещё продукт или услуга?", reply_markup=InlineKeyboardMarkup(kb))

    # --- Пользователь не имеет основу ---
    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")],
            [InlineKeyboardButton("Использовать бота «Распаковка ЦА»", callback_data="use_other_bot")]
        ]
        await query.edit_message_text("❗ Давай соберём её прямо здесь:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 [Ссылка на бота по распаковке] (в разработке).")

    elif query.data == "fill_here":
        session["state"] = "collecting_base_info"
        session["step"] = 0
        await query.edit_message_text(INFO_QUESTIONS[0])

    # --- Добавление продуктов ---
    elif query.data == "add_product":
        session["state"] = "collecting_more_products"
        await query.edit_message_text("✍️ Пришли характеристику следующего продукта/услуги.")

    elif query.data == "no_more_products":
        session["state"] = "collecting_audience_multiple"
        session["audience_segments"] = []
        await query.edit_message_text("📌 Отлично! Теперь пришли первый сегмент анализа твоей ЦА.")

    elif query.data == "add_audience_segment":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("✍️ Пришли следующий сегмент анализа ЦА.")

    elif query.data == "audience_done":
        session["data"]["audience"] = "\n\n".join(session.get("audience_segments", []))
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
             [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
        await query.edit_message_text("✅ Анализ ЦА собран. Хочешь добавить дополнительную информацию?",
                                  reply_markup=InlineKeyboardMarkup(kb))
                                  
    # --- Доп.инфо ---
    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к выбору роли", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Информация собрана. Переходим к ролям:", reply_markup=InlineKeyboardMarkup(kb))

    # --- Меню ролей ---
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("📅 Контент-планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("📌 Выбери, чем я могу помочь:", reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "menu_roles"

    # === Копирайтер ===
    elif query.data == "role_copywriter":
        kb = [
            [InlineKeyboardButton("Пост", callback_data="copy_post")],
            [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
            [InlineKeyboardButton("Оффер", callback_data="copy_offer")],
            [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("Упаковка продукта", callback_data="copy_package")],
            [InlineKeyboardButton("Пост-карусель", callback_data="copy_carousel")]
        ]
        await query.edit_message_text("🖊️ Я копирайтер! Что создаём?", reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "copywriter_menu"

    elif query.data.startswith("copy_"):
        task = query.data.split("_", 1)[1]
        session["state"] = f"copywriter_{task}"
        session["task"] = task
        session["step"] = 0
        session["copy_data"] = []
        await query.edit_message_text(
            "1️⃣ Укажи цель текста (имиджевая, вовлекающая, продающая, образовательная).",
            parse_mode="Markdown"
        )

    # === Продюсер Reels ===
    elif query.data == "role_reels":
        session["state"] = "reels_topic"
        session["reels_data"] = []
        await query.edit_message_text("🎬 Укажи тему и цель ролика.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ У вас нет доступа.")
        return
    
    # 🔹 Всегда обновляем контекст пользователя, включая стиль
    context_text = get_user_context(session)
    text = update.message.text
    session = sessions.setdefault(user_id, {"state": None, "step": 0, "data": {}, "products": []})

    # === Сбор основной информации ===
    if session["state"] == "collecting_base_info":
        step = session["step"]
        session["data"].setdefault("info", []).append(text)
        step += 1
        session["step"] = step

        # После продукта → спросить есть ли еще
        if step == 3:  
            kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
                  [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
            await update.message.reply_text("🔥 Отлично! Хочешь добавить ещё продукт/услугу?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            return

        if step < len(INFO_QUESTIONS):
            await update.message.reply_text(INFO_QUESTIONS[step])
        else:
            # Переход к доп.инфо
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
            await update.message.reply_text("Хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra"

    # === Сбор дополнительных продуктов ===
    elif session["state"] == "collecting_more_products":
        session["products"].append(text)
        kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
              [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
        await update.message.reply_text("✅ Продукт добавлен. Добавить ещё?",
                                        reply_markup=InlineKeyboardMarkup(kb))
    
        # === Сбор нескольких сегментов ЦА ===
    elif session["state"] == "collecting_audience_multiple":
        # Сохраняем очередное сообщение анализа ЦА
        session["data"].setdefault("audience_segments", []).append(text)
        kb = [
            [InlineKeyboardButton("Добавить ещё сегмент", callback_data="add_audience_segment")],
            [InlineKeyboardButton("Закончить", callback_data="audience_done")]
        ]
        await update.message.reply_text(
            "✅ Сегмент добавлен. Хочешь добавить ещё один сегмент ЦА?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # === Доп.инфо ===
    elif session["state"] == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти к ролям", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Доп.информация получена. Переходим к ролям.",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "menu_roles"

    # === Диалог Копирайтера ===
    elif session["state"].startswith("copywriter_"):
        step = session.get("step", 0)
        session["copy_data"].append(text)
        session["step"] = step + 1

        # Шаг 1 → цель
        if step == 0:
            await update.message.reply_text("2️⃣ Укажи тему текста.")
        # Шаг 2 → тема
        elif step == 1:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
        # Шаг 3 → тональность
        elif step == 2:
            await update.message.reply_text("4️⃣ Хочешь развернутый текст или краткий, но ёмкий?")
        # Шаг 4 → запрос в OpenAI
        elif step == 3:
            goal, topic, tone, length = session["copy_data"]
            context_text = get_user_context(session)

            prompt = (
                f"Ты профессиональный копирайтер и упаковщик. Создай {session['task']} для блогера/эксперта/бренда.\n\n"
                f"=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===\n{context_text}\n\n"
                f"🎯 Цель поста: {goal}\n"
                f"📌 Тема: {topic}\n"
                f"🎨 Тональность: {tone}\n"
                f"📝 Формат текста: {length} (развернутый или краткий, но ёмкий)\n\n"

                "=== ЦЕЛИ ПОСТОВ И ЧТО УЧИТЫВАТЬ ===\n"
                "Имиджевая → истории о себе/бренде, ценности, миссия, кейсы\n"
                "Вовлекающая → опросы, челленджи, вопросы, дискуссии\n"
                "Образовательная → инструкции, гайды, разборы, чек-листы, экспертные советы\n"
                "Продающая → офферы, акции, отзывы, демонстрация продукта\n"
                "Прогревающая → истории клиентов, закулисье продукта, полезные факты\n"
                "Вирусная → тренды, мемы, провокационные темы, эмоциональные видео\n"
                "Информационная → анонсы, новости, релизы, события\n"
                "Развлекательная → юмор, подборки, легкие факты, блиц-опросы\n\n"

                "=== ЕСЛИ ФОРМАТ = ПОСТ-КАРУСЕЛЬ ===\n"
                "✅ Используй структуру 10 слайдов:\n"
                "1. Крючок – захват внимания (1-2 секунды)\n"
                "2. Проблема – боль ЦА\n"
                "3. Усиление боли – последствия, упущенные выгоды\n"
                "4. Обещание решения – надежда на результат\n"
                "5–8. Контент – пошаговая инструкция, советы, факты, чек-лист\n"
                "9. Призыв к действию (CTA) – «Сохрани», «Напиши +», «Поделись»\n"
                "10. Оффер/экспертность – автор, упоминание услуги, мягкий оффер\n\n"

                "=== ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ЛЮБОГО ТЕКСТА ===\n"
                "– Заголовок (цепляет, максимум 5–7 слов)\n"
                "– Вступление (подводит, цепляет эмоцией)\n"
                "– Основная часть (логично, структурно, без воды)\n"
                "– Вывод или CTA (побуждение к действию)\n"
                "– Оффер или УТП (если уместно)\n\n"

                "=== СТИЛЬ ПИСЬМА ===\n"
                "– Пиши цепко, по-человечески, без клише\n"
                "– Используй стиль 2024–2025: коротко, просто, с эмоцией\n"
                "– Применяй сторителлинг, честный контент, вовлечение\n"
                "– Упрощай и усиливай, если текст есть\n\n"

                "⚖️ Соблюдай Федеральный закон №38-ФЗ и №72-ФЗ: "
                "не используй фразы «100% результат», «лучший», «гарантировано», "
                "заменяй их корректными альтернативами: «один из популярных вариантов», «подходит для…», «узнай подробнее».\n\n"

    "💡 Выдай текст в структурированном виде, готовый к публикации."
            )

            await update.message.reply_text("✍️ Пишу текст, подожди...")
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = sanitize_ad_text(response["choices"][0]["message"]["content"])
                await send_long_message(update.message.chat, result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка генерации текста.")
                print("OpenAI Error:", e)

            # Сброс
            session["state"] = "menu_roles"
            session["step"] = 0
            kb = [[InlineKeyboardButton("Вернуться к ролям", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Готово!", reply_markup=InlineKeyboardMarkup(kb))

    # === Планировщик ===
    elif session["state"] == "planner_goal":
        session["planner_data"] = [text]
        session["state"] = "planner_platform"
        await update.message.reply_text("2️⃣ Укажи основную соцсеть.")
    elif session["state"] == "planner_platform":
        session["planner_data"].append(text)
        session["state"] = "planner_frequency"
        await update.message.reply_text("3️⃣ Укажи частоту публикаций (пример: сторис ежедневно, рилс 3 раза в неделю).")
    elif session["state"] == "planner_frequency":
        session["planner_data"].append(text)
        session["state"] = "planner_face"
        await update.message.reply_text("4️⃣ От чьего лица вести (1 лицо / бренд)?")
    elif session["state"] == "planner_face":
        session["planner_data"].append(text)
        session["state"] = "planner_days"
        await update.message.reply_text("5️⃣ На какой срок нужен план? (7 / 10 / 30 дней)")
    elif session["state"] == "planner_days":
        session["planner_data"].append(text)
        goal, platform, freq, face, days = session["planner_data"]
        context_text = get_user_context(session)

        prompt = (
            f"Ты контент-планировщик. Твоя задача – создать развернутый, детализированный контент-план.\n\n"
            f"=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===\n{context_text}\n\n"
            f"🎯 Цель: {goal}\n"
            f"📌 Платформа: {platform}\n"
            f"📅 Срок: {days} дней\n"
            f"🗓 Частота публикаций: {freq}\n"
            f"👤 От чьего лица вести: {face}\n\n"

            "=== АНАЛИЗ ЦЕЛЕВОЙ АУДИТОРИИ ===\n"
            "Пользователь прислал несколько сегментов ЦА. "
            "Для каждого дня указывай, для какого сегмента подходит контент (или для нескольких). "
            "Обязательно используй данные сегментов, а не пиши общие советы.\n\n"

            "=== ТРЕБОВАНИЯ К ПЛАНУ ===\n"
            "– Каждый день должен включать: сторис + (или рилс / пост-карусель)\n"
            "– Укажи для каждого дня: тему, формат, цель, CTA, идеи сторис, визуальные подсказки\n"
            "– Раздели контент по рубрикатору: экспертность, вовлечение, личное, кейсы, продажи\n"
            "– Привяжи каждый день к этапу воронки: холодная, тёплая, горячая аудитория\n"
            "– Добавляй пометку [Сегмент ЦА: ...] для каждого элемента контента\n\n"

            "=== ФОРМАТ ВЫВОДА ===\n"
            "День 1:\n• Сторис – тема, идея, CTA [Сегмент ЦА: сегмент1]\n• Рилс/Пост – тема, формат, краткий сценарий, CTA [Сегмент ЦА: сегмент2]\n\n"
            "День 2:\n• … (и так далее для всех дней)\n\n"

            "=== СПЕЦИФИКА ===\n"
            "– План должен быть практичным, а не общими советами\n"
            "– Учитывай возможности автора (если публикаций мало – оптимизируй)\n"
            "– Используй форматы 2024–2025: Reels, сторис, карусели, behind-the-scenes\n"
            "– Добавляй конкретные идеи для визуала, интерактивов, опросов\n\n"

            "⚖️ Соблюдай закон №38-ФЗ и №72-ФЗ, исключи запрещённые обещания, используй корректные формулировки.\n"
            "Выдай план в структурированном виде, по дням, без сокращений «и так далее»."
        )

        await update.message.reply_text("📅 Формирую контент-план, подожди...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.message.chat, result)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка генерации плана.")
            print("Planner Error:", e)

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Вернуться к ролям", callback_data="roles_menu")]]
        await update.message.reply_text("✅ План готов!", reply_markup=InlineKeyboardMarkup(kb))

    # === Продюсер Reels ===
    elif session["state"] == "reels_topic":
        session["reels_data"].append(text)
        session["state"] = "reels_format"
        await update.message.reply_text("2️⃣ Укажи формат: с лицом / без лица / монтаж.")
    elif session["state"] == "reels_format":
        session["reels_data"].append(text)
        session["state"] = "reels_style"
        await update.message.reply_text("3️⃣ Укажи стиль: экспертный / с юмором / душевный.")
    elif session["state"] == "reels_style":
        session["reels_data"].append(text)
        session["state"] = "reels_music"
        await update.message.reply_text("4️⃣ Есть ли музыка или референс?")
    elif session["state"] == "reels_music":
        session["reels_data"].append(text)
        topic, format_r, style, music = session["reels_data"]
        context_text = get_user_context(session)

        prompt = (
            f"Ты профессиональный продюсер коротких видео (Reels, TikTok, Shorts, ВК-клипы). "
            f"Создай сценарий для видео по данным пользователя.\n\n"
            f"=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===\n{context_text}\n\n"
            f"🎯 Тема ролика: {topic}\n"
            f"📹 Формат: {format_r} (с лицом / без лица / монтаж)\n"
            f"🎨 Стиль: {style}\n"
            f"🎵 Музыка/референс: {music}\n\n"

            "=== ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СЦЕНАРИЯ ===\n"
            "1️⃣ Хук (2–3 секунды, мощный захват внимания)\n"
            "2️⃣ Основной блок (пошаговый сценарий: текст, действия, визуал)\n"
            "3️⃣ CTA (призыв к действию: сохранить, подписаться, написать)\n"
            "4️⃣ Альтернативы: вариант для видео с лицом и без\n"
            "5️⃣ Подсказки по визуалу, монтажу, свету (конкретные советы)\n\n"

            "=== ТРЕБОВАНИЯ ===\n"
            "– Используй сторителлинг, эмоции, провокационные или цепляющие элементы\n"
            "– Применяй тренды 2024–2025 (быстрый хук, честная подача)\n"
            "– Встраивай честный оффер, если это уместно\n"
            "– Делай сценарий максимально практичным и готовым к съёмке\n\n"

            "⚖️ Соблюдай Федеральный закон №38-ФЗ «О рекламе» и №72-ФЗ: "
            "не используй необоснованные обещания («100% результат», «лучший», «гарантировано»), "
            "заменяй их корректными альтернативами («один из популярных вариантов», «подходит для…», «узнай подробнее»)."
        )

        await update.message.reply_text("🎬 Генерирую сценарий, подожди...")
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.message.chat, result)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка генерации сценария.")
            print("Reels Error:", e)

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Вернуться к ролям", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Сценарий готов!", reply_markup=InlineKeyboardMarkup(kb))

# === Общий хендлер для всех других сообщений (если что-то не распознано) ===
async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ У вас нет доступа.")
        return
    await update.message.reply_text("🤔 Я не понял команду. Нажми /start, чтобы начать заново.")

# === Запуск бота ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))  # только для админа

    # Callback кнопки
    app.add_handler(CallbackQueryHandler(button_handler))

    # Сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL, any_message))

    print("🚀 Бот запущен! Ждём пользователей...")
    app.run_polling()
