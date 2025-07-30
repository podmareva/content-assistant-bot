```python
import os
import sys
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import openai

print(">>> Бот v2 загружен, файл bot.py исполняется")

# ---------- НАСТРОЙКИ ----------
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Защита от двойного запуска
if "RUNNING_BOT" in os.environ:
    print("❌ Бот уже запущен. Останови другой процесс, чтобы избежать конфликта.")
    sys.exit(1)
os.environ["RUNNING_BOT"] = "1"

# Хранилище сессий пользователей
sessions = {}

# ---------- ПРИВЕТСТВИЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент».
"
    "Он поможет:
"
    "• составить контент-план,
"
    "• написать посты, Reels, карусели,
"
    "• придумать офферы и упаковку продукта.

"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности]"
    "(https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit)"
    " и [Договором‑офертой]"
    "(https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).

"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

# ====== ХЕНДЛЕР /start ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ====== ОБРАБОТКА CALLBACK_QUERY ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    sessions.setdefault(user_id, {"state": None, "data": {}, "step": 0, "products": []})
    session = sessions[user_id]

    # --- Пользователь согласился ---
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text(
            "Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # --- Пользователь нажал ДА → пошаговый сбор ---
    elif query.data == "base_yes":
        session.update({"state": "collecting_base_info", "step": 0, "data": {"info": [], "products": []}})
        await query.edit_message_text("✅ Отлично! Пришли свою распаковку личности и экспертности.")

    # --- Пользователь нажал НЕТ → поясняем и просим заполнить ---
    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")],
            [InlineKeyboardButton("Использовать бота «Твоя распаковка и анализ ЦА»", callback_data="use_other_bot")]
        ]
        await query.edit_message_text(
            "❗ Хорошо! Без основы работать сложнее, но мы можем собрать её прямо здесь.

"
            "📌 *Что нужно подготовить:*
"
            "– Распаковка (кто ты, твои ценности, опыт, экспертность),
"
            "– Позиционирование (чем занимаешься, для кого),
"
            "– Продукты/услуги (опиши каждый),
"
            "– Анализ ЦА (кто твоя аудитория, боли, желания).

"
            "Выбери вариант:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Ссылка на внешний бот по распаковке (в разработке)")

    elif query.data == "fill_here":
        session.update({"state": "collecting_base_info", "step": 0, "data": {"info": [], "products": []}})
        await query.edit_message_text("✍️ Пришли распаковку личности и экспертности.")

    # --- Сбор продуктов ---
    elif query.data == "add_product":
        session["state"] = "collecting_more_products"
        await query.edit_message_text("✍️ Пришли характеристику следующего продукта/услуги.")

    elif query.data == "no_more_products":
        session["state"] = "collecting_audience"
        await query.edit_message_text("📌 Пришли анализ ЦА (боли, страхи, желания).")

    # --- Доп. информация по ЦА ---
    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к выбору роли", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Полная информация получена!", reply_markup=InlineKeyboardMarkup(kb))

    # --- Меню ролей ---
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("Планировщик контента", callback_data="role_planner")],
            [InlineKeyboardButton("Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери роль:", reply_markup=InlineKeyboardMarkup(kb))

    # --- Роли ---
    elif query.data == "role_planner":
        session.update({"state": "planner_platform", "planner": {}})
        await query.edit_message_text("📌 Укажи основную соцсеть (Instagram, Telegram, VK и т.д.).")

    elif query.data == "role_copywriter":
        kb = [
            [InlineKeyboardButton("Написать пост", callback_data="copy_post")],
            [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
            [InlineKeyboardButton("Придумать оффер", callback_data="copy_offer")],
            [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("Упаковка продукта", callback_data="copy_package")],
            [InlineKeyboardButton("Пост-карусель", callback_data="copy_carousel")]
        ]
        session["state"] = "copywriter_mode"
        await query.edit_message_text("🖊️ Я копирайтер! Чем помочь?", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith("copy_"):
        task = query.data.split("_",1)[1]
        session.update({"state": f"copywriter_{task}", "task": task, "step": 0, "copy_data": []})
        await query.edit_message_text(
            f"📌 Отлично! Ты выбрал задачу: {task}.

1️⃣ Укажи цель текста (имиджевая, вовлекающая, продающая, прогревающая, образовательная, вирусная, информационная, развлекательная).",
            parse_mode="Markdown"
        )

    elif query.data == "role_reels":
        session.update({"state": "reels_topic", "reels_data": []})
        await query.edit_message_text("🎬 Укажи тему и цель ролика.")

    else:
        await query.edit_message_text("Нажми /start, чтобы начать заново.")

# ====== ОБРАБОТКА СООБЩЕНИЙ ======
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    session = sessions.get(user_id, {})
    state = session.get("state")
    step = session.get("step", 0)

    # === СБОР БАЗОВОЙ ИНФОРМАЦИИ ===
    if state == "collecting_base_info":
        if step == 0:
            session["data"]["info"].append({"распаковка": text})
            session["step"] = 1
            await update.message.reply_text("🔥 Супер! Благодарю! Теперь пришли своё позиционирование.")
            return
        elif step == 1:
            session["data"]["info"].append({"позиционирование": text})
            session["step"] = 2
            await update.message.reply_text("✅ Отлично! Теперь пришли краткую характеристику продукта/услуги.")
            return
        elif step == 2:
            session["products"].append(text)
            session["state"] = "ask_more_products"
            kb = [[InlineKeyboardButton("Да ✅", callback_data="add_product")],
                  [InlineKeyboardButton("Нет ❌", callback_data="no_more_products")]]
            await update.message.reply_text("Есть ли у тебя ещё продукт или услуга?", reply_markup=InlineKeyboardMarkup(kb))
            return

    # === СОБИРАЕМ ДОПОЛНИТЕЛЬНЫЕ ПРОДУКТЫ ===
    if state == "collecting_more_products":
        session["products"].append(text)
        kb = [[InlineKeyboardButton("Да ✅", callback_data="add_product")],
              [InlineKeyboardButton("Нет ❌", callback_data="no_more_products")]]
        await update.message.reply_text("Есть ли ещё продукт или услуга?", reply_markup=InlineKeyboardMarkup(kb))
        return

    # === ДОП.ИНФОРМАЦИЯ ПО ЦА ===
    if state == "collecting_audience":
        session["data"]["extra_info"] = text
        session["state"] = "waiting_extra_info"
        kb = [[InlineKeyboardButton("Да ✅", callback_data="add_extra_info")],
              [InlineKeyboardButton("Нет ❌", callback_data="no_extra_info")]]
        await update.message.reply_text("Есть ли ещё дополнительная информация по ЦА?", reply_markup=InlineKeyboardMarkup(kb))
        return

    if state == "waiting_extra_info":
        session["data"]["extra_info"] += "\n" + text
        kb = [[InlineKeyboardButton("Да ✅", callback_data="add_extra_info")],
              [InlineKeyboardButton("Нет ❌", callback_data="no_extra_info")]]
        await update.message.reply_text("Есть ли ещё инфо по ЦА?", reply_markup=InlineKeyboardMarkup(kb))
        return

# ====== ДОБАВЛЕНИЕ КНОПОК В button_handler ======
    # --- Пользователь добавляет ещё продукт ---
    elif query.data == "add_product":
        sessions[user_id]["state"] = "collecting_more_products"
        await query.edit_message_text("✍️ Пришли краткую характеристику следующего продукта/услуги.")

    # --- Пользователь завершил ввод продуктов ---
    elif query.data == "no_more_products":
        sessions[user_id]["state"] = "collecting_audience"
        await query.edit_message_text("📌 Отлично! Теперь пришли анализ твоей ЦА (опиши боли, страхи, желания).")

    # --- Переход к дополнительной информации по ЦА ---
    elif query.data == "add_extra_info":
        sessions[user_id]["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    # --- Пользователь закончил ввод ЦА ---
    elif query.data == "no_extra_info":
        sessions[user_id]["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к выбору роли", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Отлично! Полная информация получена. Переходим к ролям!",
                                      reply_markup=InlineKeyboardMarkup(kb))

# ====== ДОБАВЛЕНИЕ В button_handler (роль Планировщик) ======
elif query.data == "role_planner":
    sessions[user_id]["state"] = "planner_platform"
    sessions[user_id]["planner"] = {}
    await query.edit_message_text("📌 Укажи основную соцсеть (Instagram, Telegram, VK и т.д.).")


# ====== ДОБАВЛЕНИЕ В handle_message (логика Планировщика) ======
elif state == "planner_platform":
    session["planner"]["platform"] = text
    session["state"] = "planner_goal"
    await update.message.reply_text("🎯 Укажи цель (набор подписчиков / продажи продукта / личный бренд / прогрев).")

elif state == "planner_goal":
    session["planner"]["goal"] = text
    session["state"] = "planner_formats"
    await update.message.reply_text("📌 Укажи форматы (Reels, посты, сторис, карусели).")

elif state == "planner_formats":
    session["planner"]["formats"] = text
    session["state"] = "planner_frequency"
    await update.message.reply_text("🗓 Укажи частоту публикаций (например: сторис ежедневно, рилс 3 раза в неделю, посты 2 раза в неделю).")

elif state == "planner_frequency":
    session["planner"]["frequency"] = text
    session["state"] = "planner_duration"
    await update.message.reply_text("⏳ На какой срок нужен контент-план? (7, 10 или 30 дней)")

elif state == "planner_duration":
    session["planner"]["duration"] = text
    await update.message.reply_text("🧠 Формирую детализированный контент-план, подожди...")

    # --- Генерация GPT ---
    try:
        products = "; ".join(session.get("products", []))
        user_info = str(session["data"]["info"])
        extra_info = session["data"].get("extra_info", "")

        prompt = (
            "Ты контент-планировщик. Составь подробный контент-план.\n\n"
            f"📌 Соцсеть: {session['planner']['platform']}\n"
            f"🎯 Цель: {session['planner']['goal']}\n"
            f"📂 Форматы: {session['planner']['formats']}\n"
            f"🗓 Частота: {session['planner']['frequency']}\n"
            f"⏳ Срок: {session['planner']['duration']} дней\n\n"
            f"🧩 Инфо пользователя: {user_info}\n"
            f"🛍 Продукты: {products}\n"
            f"👥 ЦА: {extra_info}\n\n"
            "‼️ Учитывай законы №38-ФЗ и №72-ФЗ (не используй необоснованные обещания).\n\n"
            "📌 Структура ответа:\n"
            "1. 📅 План на каждый день (День X: Сторис – тема, Рилс/Пост-Карусель – тема, CTA).\n"
            "2. 📊 Рубрикатор (экспертность, вовлечение, продажи, личное, кейсы).\n"
            "3. 🔥 Привязка к воронке (холодная, теплая, горячая).\n"
            "4. 📝 Примеры заголовков и CTA.\n"
            "⚠️ Если ответ длинный – раздели его на несколько сообщений."
        )

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )

        result = response["choices"][0]["message"]["content"]

        # --- Разделяем длинный ответ на части ---
        for chunk in [result[i:i+3500] for i in range(0, len(result), 3500)]:
            await update.message.reply_text(chunk)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при генерации контент-плана.")
        print("Planner Error:", e)

    session["state"] = "menu_roles"
    kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
    await update.message.reply_text("✅ Контент-план готов! Хочешь еще? Выбери новую задачу:",
                                    reply_markup=InlineKeyboardMarkup(kb))

# ====== ФУНКЦИЯ ФИЛЬТРАЦИИ РЕКЛАМЫ ======
def sanitize_ad_text(text: str) -> str:
    replacements = {
        "100%": "один из популярных вариантов",
        "лучший": "один из лучших",
        "гарантировано": "с высокой вероятностью",
        "без рисков": "с минимальными рисками"
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


# ====== ДОБАВЛЕНИЕ В button_handler (роль Копирайтер) ======
elif query.data == "role_copywriter":
    kb = [
        [InlineKeyboardButton("Написать пост", callback_data="copy_post")],
        [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
        [InlineKeyboardButton("Придумать оффер", callback_data="copy_offer")],
        [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
        [InlineKeyboardButton("Упаковка продукта", callback_data="copy_package")],
        [InlineKeyboardButton("Пост-карусель", callback_data="copy_carousel")]
    ]
    await query.edit_message_text("🖊️ Я копирайтер! Чем помочь?", reply_markup=InlineKeyboardMarkup(kb))
    sessions[user_id]["state"] = "copywriter_mode"

elif query.data.startswith("copy_"):
    task = query.data.split("_", 1)[1]
    sessions[user_id]["state"] = f"copywriter_{task}"
    sessions[user_id]["task"] = task
    sessions[user_id]["step"] = 0
    sessions[user_id]["copy_data"] = []
    await query.edit_message_text(
        f"📌 Отлично! Ты выбрал задачу: {task}.\n\n1️⃣ Укажи цель текста (имиджевая, вовлекающая, продающая, прогревающая, образовательная, вирусная, информационная, развлекательная).",
        parse_mode="Markdown"
    )


# ====== ОБРАБОТКА СООБЩЕНИЙ (копирайтер) ======
elif state.startswith("copywriter_"):
    task = session.get("task", "пост")
    step = session.get("step", 0)
    session["copy_data"].append(text)
    session["step"] = step + 1

    # шаг 1 → тема
    if step == 0:
        await update.message.reply_text("2️⃣ Укажи тему текста (например: продвижение курса, дизайн интерьера).")
        return

    # шаг 2 → тональность
    elif step == 1:
        await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая, уверенная).")
        return

    # шаг 3 → спрашиваем развернутый или краткий пост
    elif step == 2:
        kb = [
            [InlineKeyboardButton("Развернутый", callback_data="post_long")],
            [InlineKeyboardButton("Краткий, но емкий", callback_data="post_short")]
        ]
        await update.message.reply_text("4️⃣ Какой нужен пост? Выбери вариант:",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "copywriter_length"
        return


# ====== ВЫБОР ДЛИНЫ И ГЕНЕРАЦИЯ ПОСТА ======
if state == "copywriter_length":
    length = "развернутый" if "длин" in text.lower() or "развер" in text.lower() else "краткий"
    session["copy_length"] = length
    await update.message.reply_text("✍️ Отлично! Пишу текст, подожди...")

    # --- Генерация GPT ---
    try:
        goal, topic, tone = session["copy_data"][:3]
        products_list = "; ".join(session.get("products", []))
        info = session["data"].get("info", [])
        extra_info = session["data"].get("extra_info", "")

        user_context = (
            f"🧩 Распаковка: {info[0] if info else 'нет данных'}\n"
            f"🎯 Позиционирование: {info[1] if len(info) > 1 else 'нет данных'}\n"
            f"🛍 Продукты: {products_list}\n"
            f"👥 ЦА: {extra_info}"
        )

        # --- Доп.инструкция для карусели ---
        carousel_instruction = ""
        if task == "carousel":
            carousel_instruction = (
                "\n✅ Для поста-карусели используй структуру:\n"
                "1. Крючок\n2. Проблема\n3. Усиление боли\n4. Обещание решения\n"
                "5–8. Основная ценность (пошагово)\n9. CTA\n10. Оффер/Экспертность.\n"
                "Пиши кратко: до 12 слов/слайд."
            )

        prompt = (
            f"Ты профессиональный копирайтер. Напиши {task}.\n"
            f"📌 Данные:\n{user_context}\n\n"
            f"🎯 Цель: {goal}\n📌 Тема: {topic}\n🎨 Тональность: {tone}\n"
            f"Формат: {length}\n{carousel_instruction}\n"
            "‼️ Соблюдай законы №38-ФЗ и №72-ФЗ.\n"
            "🚫 Не используй запрещенные фразы.\n"
            "📌 Структура: заголовок, вступление, основная часть, CTA, оффер (если нужно)."
        )

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )

        result = response["choices"][0]["message"]["content"]
        clean_result = sanitize_ad_text(result)
        await update.message.reply_text(clean_result)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при генерации текста.")
        print("Copywriter Error:", e)

    # сброс состояния
    session["state"] = "menu_roles"
    session["step"] = 0
    session["copy_data"] = []
    kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
    await update.message.reply_text("✅ Готово! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))

# ====== ДОБАВЛЕНИЕ В button_handler (роль Продюсер Reels) ======
elif query.data == "role_reels":
    sessions[user_id]["state"] = "reels_topic"
    sessions[user_id]["reels_data"] = []
    await query.edit_message_text("🎬 Укажи тему и цель ролика.")


# ====== ОБРАБОТКА СООБЩЕНИЙ (Продюсер Reels) ======
elif state == "reels_topic":
    session["reels_data"].append(text)
    session["state"] = "reels_format"
    await update.message.reply_text("📹 Укажи формат: с лицом / без лица / монтаж.")

elif state == "reels_format":
    session["reels_data"].append(text)
    session["state"] = "reels_style"
    await update.message.reply_text("🎨 Укажи стиль: экспертный / с юмором / душевный.")

elif state == "reels_style":
    session["reels_data"].append(text)
    session["state"] = "reels_audio"
    await update.message.reply_text("🎶 Есть ли музыка или референс? Укажи или напиши 'нет'.")

elif state == "reels_audio":
    session["reels_data"].append(text)
    await update.message.reply_text("🎬 Создаю сценарий, подожди...")

    try:
        topic, video_format, style, audio = session["reels_data"][:4]
        products_list = "; ".join(session.get("products", []))
        info = session["data"].get("info", [])
        extra_info = session["data"].get("extra_info", "")

        user_context = (
            f"🧩 Распаковка: {info[0] if info else 'нет данных'}\n"
            f"🎯 Позиционирование: {info[1] if len(info) > 1 else 'нет данных'}\n"
            f"🛍 Продукты: {products_list}\n"
            f"👥 ЦА: {extra_info}"
        )

        prompt = (
            "Ты продюсер Reels. Создай сценарий короткого видео для Instagram/TikTok/Shorts.\n\n"
            f"📌 Данные:\n{user_context}\n\n"
            f"🎬 Тема: {topic}\n📹 Формат: {video_format}\n🎨 Стиль: {style}\n🎶 Музыка/референс: {audio}\n\n"
            "‼️ Соблюдай законы №38-ФЗ и №72-ФЗ (не используй необоснованные обещания).\n"
            "🚫 Не используй запрещенные формулировки.\n"
            "📌 Выдай:\n"
            "– Хук (2–3 секунды)\n"
            "– Основной блок (текст, действия, визуал)\n"
            "– Призыв к действию (CTA)\n"
            "– Альтернатива (с лицом и без)\n"
            "– Подсказки по визуалу, монтажу, свету."
        )

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )

        result = response["choices"][0]["message"]["content"]
        clean_result = sanitize_ad_text(result)

        # Разделяем, если ответ длинный
        for chunk in [clean_result[i:i+3500] for i in range(0, len(clean_result), 3500)]:
            await update.message.reply_text(chunk)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при генерации сценария.")
        print("Reels Error:", e)

    # сброс состояния
    session["state"] = "menu_roles"
    session["step"] = 0
    session["reels_data"] = []
    kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
    await update.message.reply_text("✅ Сценарий готов! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))


# ====== ФИНАЛ: ЗАПУСК БОТА ======
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот v2 запущен и готов к работе!")
    app.run_polling()
