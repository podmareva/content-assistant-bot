import os
import sys
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import openai

print(">>> Бот загружен, файл bot.py исполняется")

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

# ---------- ВОПРОСЫ ДЛЯ СБОРА ОСНОВЫ ----------
BASE_QUESTIONS = [
    "👍 Отлично! Пришли, пожалуйста, свою **распаковку личности и экспертности**.",
    "🔥 Супер, благодарю! Теперь отправь **своё позиционирование**.",
    "👌 Отлично! Теперь пришли **краткую характеристику продукта/услуги**.",
    "✅ Супер! Теперь отправь **анализ своей ЦА** (можно в 1-2 сообщениях)."
]

# ---------- ПРИВЕТСТВИЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент». Он поможет:\n"
    "• создать контент-план;\n"
    "• написать или отредактировать пост;\n"
    "• создать сценарий для Reels или Stories.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit?usp=drive_link) "
    "и [Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit?usp=drive_link).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

# ---------- СТАРТ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- ОБРАБОТКА КНОПОК ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    sessions.setdefault(user_id, {"state": None, "data": {}, "step": 0})

    # Пользователь согласился
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # Пользователь нажал ДА → начинаем пошаговый сбор
    elif query.data == "base_yes":
        sessions[user_id]["state"] = "base_collect"
        sessions[user_id]["step"] = 0
        await query.edit_message_text(BASE_QUESTIONS[0], parse_mode="Markdown")

    # Пользователь нажал НЕТ → предлагаем заполнить или использовать бота для распаковки
    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Использовать бота «Твоя распаковка и анализ ЦА»", callback_data="use_other_bot")],
            [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")]
        ]
        await query.edit_message_text("❗ Хорошо! У тебя два варианта:\n"
                                      "1️⃣ Воспользоваться отдельным ботом для распаковки (пока заглушка)\n"
                                      "2️⃣ Заполнить данные прямо здесь",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 [Ссылка на бота по распаковке] (в разработке).")

    elif query.data == "fill_here":
        sessions[user_id]["state"] = "collecting_info"
        sessions[user_id]["step"] = 0
        await query.edit_message_text("Пришли, пожалуйста, свою распаковку личности и экспертности.", parse_mode="Markdown")

    # Переход в меню ролей
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("📊 Контент-планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем я могу помочь:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "menu_roles"

    # Переход к копирайтеру
    elif query.data == "role_copywriter":
        kb = [
            [InlineKeyboardButton("Написать пост", callback_data="copy_post")],
            [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
            [InlineKeyboardButton("Придумать оффер", callback_data="copy_offer")],
            [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("Пост-карусель", callback_data="copy_carousel")]
        ]
        await query.edit_message_text("🖊️ Я копирайтер! Чем помочь?", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "copywriter_mode"

    # Переход к планировщику
    elif query.data == "role_planner":
        sessions[user_id]["state"] = "planner_ask_goal"
        await query.edit_message_text("📌 Укажи основную цель контент-плана (например: набор подписчиков, продажи, прогрев).")

    # Переход к продюсеру
    elif query.data == "role_reels":
        sessions[user_id]["state"] = "reels_ask_topic"
        await query.edit_message_text("🎬 Укажи тему и цель ролика.")

# ================= КОПИРАЙТЕР =================

# Вопросы для сбора данных у копирайтера
COPYWRITER_QUESTIONS = [
    "🎯 Укажи цель текста (имиджевая, вовлекающая, образовательная, продающая, прогревающая, вирусная, информационная, развлекательная).",
    "📌 Укажи тему текста (например: продвижение курса, экспертная статья, кейс клиента).",
    "🎨 Укажи тональность текста (экспертная, дружелюбная, дерзкая).",
    "✍️ Нужен текст **развернутый** или **краткий, но емкий**?"
]

# Справочник целей поста
POST_GOALS = {
    "Имиджевая": "Истории о бренде, ценности, миссия, кейсы",
    "Вовлекающая": "Опросы, викторины, челленджи, дискуссии",
    "Образовательная": "Инструкции, гайды, чек-листы, экспертные советы",
    "Продающая": "Офферы, акции, кейсы, демонстрация продукта",
    "Прогревающая": "Истории клиентов, закулисье, полезные факты",
    "Вирусная": "Тренды, мемы, провокации, эмоциональные видео",
    "Информационная": "Анонсы, новости, релизы, события",
    "Развлекательная": "Юмор, подборки, игры, легкие факты"
}

# ✅ Алгоритм для поста-карусели
CAROUSEL_GUIDE = (
    "✅ **Структура поста-карусели (10 слайдов – оптимум)**\n"
    "1️⃣ **Крючок** – цепляющий заголовок, 1 мысль\n"
    "2️⃣ **Проблема** – боль ЦА\n"
    "3️⃣ **Усиление боли** – последствия\n"
    "4️⃣ **Обещание решения** – надежда\n"
    "5–8️⃣ **Контент** – пошаговое решение, советы\n"
    "9️⃣ **CTA** – «Сохрани», «Напиши +»\n"
    "🔟 **Оффер/экспертность** – закрепить доверие\n\n"
    "✅ Пиши коротко, по 10–12 слов/слайд. Используй живой язык."
)

# ================= ОБРАБОТКА ДИАЛОГА С КОПИРАЙТЕРОМ =================
async def handle_copywriter_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions[user_id]

    # Инициализация шагов
    step = session.get("step", 0)
    session.setdefault("copy_data", [])

    # Сохраняем ответ
    session["copy_data"].append(text)
    step += 1
    session["step"] = step

    # Если еще не собраны все ответы → задаем следующий вопрос
    if step < len(COPYWRITER_QUESTIONS):
        await update.message.reply_text(COPYWRITER_QUESTIONS[step])
        return

    # Все ответы собраны → генерируем текст
    goal, topic, tone, length = session["copy_data"]
    task = session.get("task", "пост")

    # Определяем специфику
    goal_info = POST_GOALS.get(goal.capitalize(), "Используй сильные цепляющие элементы.")
    length_style = "Развернутый текст с деталями" if "развернут" in length.lower() else "Краткий, но емкий текст"

    # Дополнительное руководство для каруселей
    if task == "carousel":
        extra_instruction = f"\n\n{CAROUSEL_GUIDE}"
    else:
        extra_instruction = ""

    await update.message.reply_text("✍️ Пишу текст, подожди...")

    try:
        # Запрос к OpenAI
        prompt = (
            f"Ты профессиональный копирайтер. Напиши {task}.\n"
            f"🎯 Цель: {goal} ({goal_info})\n"
            f"📌 Тема: {topic}\n"
            f"🎨 Тональность: {tone}\n"
            f"Формат: {length_style}\n"
            "📌 Структура:\n– Заголовок\n– Вступление\n– Основная часть\n– Вывод/CTA\n– Оффер (если нужно)\n"
            "Пиши цепко, в стиле 2024–2025, без клише." + extra_instruction
        )
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response["choices"][0]["message"]["content"]
        await update.message.reply_text(result)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при генерации текста.")
        print("OpenAI Error:", e)

    # Сброс состояния → возврат в меню
    session["state"] = "roles_menu"
    session["step"] = 0
    session["copy_data"] = []
    kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
    await update.message.reply_text("✅ Готово! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))

# ================= ПЛАНИРОВЩИК =================

# Вопросы для сбора данных у планировщика
PLANNER_QUESTIONS = [
    "🎯 Укажи главную цель контент-плана (набор подписчиков, продажа продукта, личный бренд, прогрев).",
    "📱 Укажи основную соцсеть (Instagram, Telegram, VK) и нужна ли адаптация для других?",
    "📌 Укажи частоту публикаций (например: сторис ежедневно, рилс 3 раза в неделю, пост 2 раза в неделю).",
    "👤 От чьего лица вести: 1 лицо / бренд?",
    "⏳ На какой срок нужен контент-план (7, 10, 14, 21 или 30 дней)?"
]

# ================= ОБРАБОТКА ДИАЛОГА С ПЛАНИРОВЩИКОМ =================
async def handle_planner_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions[user_id]

    step = session.get("step", 0)
    session.setdefault("planner_data", [])

    # Сохраняем ответ
    session["planner_data"].append(text)
    step += 1
    session["step"] = step

    # Если не собраны все ответы → задаем следующий вопрос
    if step < len(PLANNER_QUESTIONS):
        await update.message.reply_text(PLANNER_QUESTIONS[step])
        return

    # Все ответы собраны → генерируем контент-план
    goal, platform, frequency, persona, days = session["planner_data"]

    await update.message.reply_text("🗂 Формирую контент-план, подожди...")

    try:
        # Запрос к OpenAI с учетом всех вводных
        prompt = (
            "Ты профессиональный контент-планировщик. Составь индивидуальный план контента.\n\n"
            f"📌 Цель: {goal}\n"
            f"📱 Платформа: {platform}\n"
            f"🗓 Частота публикаций: {frequency}\n"
            f"👤 От чьего лица: {persona}\n"
            f"⏳ Срок: {days} дней\n\n"
            "‼️ ВАЖНО: План должен быть **по дням** (каждый день расписан отдельно),\n"
            "в формате: 1 день = сторис + рилс ИЛИ сторис + пост/карусель.\n"
            "Не повторяй одну и ту же тему. Учитывай разнообразие форматов и цели.\n"
            "📌 Выдай:\n– Темы постов/каруселей/рилс/сторис\n– Формат\n– Цель\n– CTA\n"
            "После плана добавь: рубрикатор, привязку к воронке (холодная/теплая/горячая), идеи сторис и визуальные подсказки.\n"
            "Отправляй несколько сообщений, если не помещается в одно!"
        )

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response["choices"][0]["message"]["content"]

        # Разбиваем длинный ответ на части (чтобы Telegram не обрезал)
        chunks = [result[i:i+3500] for i in range(0, len(result), 3500)]
        for chunk in chunks:
            await update.message.reply_text(chunk)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при генерации контент-плана.")
        print("OpenAI Error:", e)

    # Сброс состояния → возврат в меню
    session["state"] = "roles_menu"
    session["step"] = 0
    session["planner_data"] = []
    kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
    await update.message.reply_text("✅ План готов! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))

# ================= ПРОДЮСЕР REELS =================

# Вопросы для сбора данных
REELS_QUESTIONS = [
    "🎬 Укажи тему и цель ролика.",
    "📹 Укажи формат: с лицом / без лица / монтаж.",
    "🎨 Укажи стиль: экспертный / с юмором / душевный.",
    "🎶 Есть ли музыка или референс? (отправь ссылку или опиши)."
]

# ================= ОБРАБОТКА ДИАЛОГА ПРОДЮСЕРА =================
async def handle_reels_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions[user_id]

    step = session.get("step", 0)
    session.setdefault("reels_data", [])

    # Сохраняем ответ
    session["reels_data"].append(text)
    step += 1
    session["step"] = step

    # Если не собраны все ответы → задаем следующий вопрос
    if step < len(REELS_QUESTIONS):
        await update.message.reply_text(REELS_QUESTIONS[step])
        return

    # Все данные собраны → генерируем сценарий
    topic, video_format, style, audio = session["reels_data"]
    await update.message.reply_text("🎥 Генерирую сценарий Reels, подожди...")

    try:
        prompt = (
            "Ты опытный продюсер Reels. Составь сценарий короткого видео.\n\n"
            f"🎬 Тема: {topic}\n"
            f"📹 Формат: {video_format}\n"
            f"🎨 Стиль: {style}\n"
            f"🎶 Музыка/референс: {audio}\n\n"
            "‼️ ВАЖНО: Укажи:\n"
            "– Хук (2–3 секунды)\n– Основной блок (текст, действия, визуал)\n– CTA (призыв к действию)\n"
            "– Альтернативу: вариант с лицом и без\n– Подсказки по монтажу, свету, звуку\n"
            "Учитывай тренды 2024–2025, честную подачу, быстрый хук."
        )

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response["choices"][0]["message"]["content"]

        # Разбиваем длинный ответ на части
        chunks = [result[i:i+3500] for i in range(0, len(result), 3500)]
        for chunk in chunks:
            await update.message.reply_text(chunk)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка при генерации сценария.")
        print("Reels Error:", e)

    # Сброс состояния → возврат в меню
    session["state"] = "roles_menu"
    session["step"] = 0
    session["reels_data"] = []
    kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
    await update.message.reply_text("✅ Сценарий готов! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))


# ================= ОБРАБОТЧИК handle_message =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = sessions.get(user_id, {"state": None})
    state = session.get("state")

    # Обработка последовательного ввода данных для всех ролей
    if state == "base_collect":
        step = session.get("step", 0)
        session["data"].setdefault("info", []).append(update.message.text)
        step += 1
        session["step"] = step

        if step < len(BASE_QUESTIONS):
            await update.message.reply_text(BASE_QUESTIONS[step])
        else:
            kb = [
                [InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                [InlineKeyboardButton("НЕТ ❌", callback_data="roles_menu")]
            ]
            await update.message.reply_text("📌 Хочешь ли ты отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_question"
        return

    # Диалоги копирайтера
    if state and state.startswith("copywriter_"):
        await handle_copywriter_dialog(update, context)
        return

    # Диалоги планировщика
    if state and state.startswith("planner_"):
        await handle_planner_dialog(update, context)
        return

    # Диалоги продюсера Reels
    if state and state.startswith("reels_"):
        await handle_reels_dialog(update, context)
        return

    # Если пользователь не в сценарии
    await update.message.reply_text("Нажми /start, чтобы начать заново.")


# ================= ЗАПУСК БОТА =================
if __name__ == "__main__":
    print("🚀 Бот загружен и готов к запуску!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ✅ Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Бот запущен. Ожидаю сообщения...")
    app.run_polling()
