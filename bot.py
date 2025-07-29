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

sessions = {}

# Вопросы для сбора информации
INFO_QUESTIONS = [
    "Пришли, пожалуйста, свою распаковку личности и экспертности.",
    "Супер! Благодарю! Теперь пришли своё позиционирование.",
    "Отлично! Теперь пришли краткую характеристику продукта/услуги.",
    "Супер! Теперь пришли анализ твоей ЦА."
]

# ---------- ПРИВЕТСТВИЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент». Он поможет:\n"
    "• создать контент-стратегию;\n"
    "• составить контент-план;\n"
    "• написать посты и сценарии для Reels.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit?usp=drive_link) и "
    "[Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit?usp=drive_link).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    sessions.setdefault(user_id, {"state": None, "data": {}, "step": 0})

    # ✅ Пользователь согласился
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text(
            "Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ✅ Если у пользователя НЕТ основы
    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Использовать бота «Твоя распаковка и анализ ЦА»", callback_data="use_other_bot")],
            [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")]
        ]
        await query.edit_message_text(
            "❗ Хорошо! У тебя два варианта:\n"
            "1️⃣ Воспользоваться отдельным ботом для распаковки (пока заглушка)\n"
            "2️⃣ Заполнить данные прямо здесь",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ✅ Заглушка для другого бота
    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 [Ссылка на бота по распаковке] (в разработке).")

    # ✅ Сбор данных (если нет основы)
    elif query.data == "fill_here":
        sessions[user_id]["state"] = "collecting_info"
        sessions[user_id]["step"] = 0
        await query.edit_message_text(INFO_QUESTIONS[0], parse_mode="Markdown")

    # ✅ ЕСЛИ пользователь выбрал «ДА ✅» → пошаговый сбор данных
    elif query.data == "base_yes":
        sessions[user_id]["state"] = "collecting_existing_info"
        sessions[user_id]["step"] = 0
        sessions[user_id]["data"]["info"] = []
        await query.edit_message_text("Отлично! Пришли, пожалуйста, свою распаковку личности и экспертности.")

    # ✅ Доп. информация по ЦА
    elif query.data == "add_extra_info":
        await query.edit_message_text("✍️ Тогда жду дополнительную информацию по ЦА. Отправь её одним сообщением.")
        sessions[user_id]["state"] = "waiting_extra_info"

    elif query.data == "no_extra_info":
        sessions[user_id]["state"] = "roles_menu"
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Отлично! Полная информация получена. Переходим к выбору роли.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # ✅ Меню ролей (обновленный порядок: планировщик → копирайтер → продюсер)
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("📅 Контент-планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем я могу помочь:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "menu_roles"

    # ✅ КОПИРАЙТЕР
    elif query.data == "role_copywriter":
        kb = [
            [InlineKeyboardButton("Написать пост", callback_data="copy_post")],
            [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
            [InlineKeyboardButton("Придумать оффер", callback_data="copy_offer")],
            [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("Упаковка продукта", callback_data="copy_package")]
        ]
        await query.edit_message_text("🖊️ Я копирайтер! Выбери задачу:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "copywriter_menu"

    elif query.data.startswith("copy_"):
        task = query.data.split("_", 1)[1]
        sessions[user_id]["state"] = f"copywriter_{task}"
        sessions[user_id]["task"] = task
        sessions[user_id]["step"] = 0
        await query.edit_message_text(
            f"✍️ Отлично! Ты выбрал задачу: *{task}*.\n\n"
            "1️⃣ Укажи цель текста (продажа, вовлечение, имидж, прогрев).",
            parse_mode="Markdown"
        )

    # ✅ ПЛАНИРОВЩИК
    elif query.data == "role_planner":
        sessions[user_id]["state"] = "planner_platform"
        sessions[user_id]["planner_data"] = {}
        await query.edit_message_text("📌 Укажи основную соцсеть (Instagram, Telegram, ВК и т.д.).")

    # ✅ ПРОДЮСЕР REELS
    elif query.data == "role_reels":
        sessions[user_id]["state"] = "reels_topic"
        sessions[user_id]["reels_data"] = {}
        await query.edit_message_text("🎬 Укажи тему и цель ролика.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    session = sessions.get(user_id, {})

    # ✅ 1. Сбор данных, если у пользователя уже есть основа
    if session.get("state") == "collecting_existing_info":
        step = session.get("step", 0)
        info = session["data"].setdefault("info", [])
        info.append(text)

        step += 1
        session["step"] = step

        if step == 1:
            await update.message.reply_text("🔥 Отлично! Теперь пришли своё позиционирование.")
        elif step == 2:
            await update.message.reply_text("✅ Супер! Теперь пришли краткую характеристику продукта/услуги.")
        elif step == 3:
            await update.message.reply_text("👍 Благодарю! Теперь пришли анализ твоей ЦА.")
        elif step == 4:
            kb = [
                [InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]
            ]
            await update.message.reply_text("📌 Хочешь ли ты отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_question"
        return

    # ✅ 2. Если пользователь отправляет доп.информацию
    if session.get("state") == "waiting_extra_info":
        session["data"]["extra_info"] = text
        await update.message.reply_text("✅ Отлично! Полная информация получена. Теперь выбери роль.")
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("👉 Нажми, чтобы перейти в меню:", reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "roles_menu"
        return

    # ✅ 3. КОПИРАЙТЕР: пошаговый диалог
    if session.get("state", "").startswith("copywriter_"):
        step = session.get("step", 0)
        task = session.get("task")
        copy_data = session.setdefault("copy_data", [])
        copy_data.append(text)
        step += 1
        session["step"] = step

        if step == 1:
            await update.message.reply_text("2️⃣ Укажи тему текста (например: продвижение курса, экспертная статья).")
        elif step == 2:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
        elif step == 3:
            await update.message.reply_text("4️⃣ Нужен ли текст развернутый или краткий, но емкий?")
        elif step == 4:
            # ✅ Все данные собраны → отправляем запрос к OpenAI
            goal, topic, tone, length = copy_data
            await update.message.reply_text("✍️ Пишу текст, подожди...")

            try:
                prompt = (
                    f"Ты профессиональный копирайтер. Напиши {task}.\n"
                    f"🎯 Цель: {goal}\n📌 Тема: {topic}\n🎨 Тональность: {tone}\n"
                    f"📏 Формат: {length}\n\n"
                    "Структура: Заголовок, Вступление, Основная часть, Вывод/CTA, Оффер (если нужно).\n"
                    "Пиши цепко, современно, в стиле 2024–2025. Если нужно, используй формат поста-карусели."
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

            # ✅ сброс состояния
            session["state"] = "roles_menu"
            session["step"] = 0
            session["copy_data"] = []
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Готово! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # ✅ 4. ПЛАНИРОВЩИК: пошаговый диалог
    if session.get("state", "").startswith("planner_"):
        planner = session.setdefault("planner_data", {})
        step = session.get("step", 0)

        if session["state"] == "planner_platform":
            planner["platform"] = text
            session["state"] = "planner_goal"
            await update.message.reply_text("🎯 Укажи цель: набор подписчиков, продажи, личный бренд, прогрев.")
            return

        elif session["state"] == "planner_goal":
            planner["goal"] = text
            session["state"] = "planner_formats"
            await update.message.reply_text("📌 Укажи основные форматы (Reels, сторис, пост-карусель).")
            return

        elif session["state"] == "planner_formats":
            planner["formats"] = text
            session["state"] = "planner_frequency"
            await update.message.reply_text("⏳ Укажи частоту публикаций (например: сторис ежедневно, рилс 3 раза в неделю).")
            return

        elif session["state"] == "planner_frequency":
            planner["frequency"] = text
            session["state"] = "planner_duration"
            await update.message.reply_text("📅 На какой срок нужен план? (7, 10, 30 дней)")
            return

        elif session["state"] == "planner_duration":
            planner["duration"] = text
            await update.message.reply_text("🛠️ Формирую контент-план, подожди...")

            try:
                prompt = (
                    f"Составь детализированный контент-план для {planner['platform']}.\n"
                    f"Цель: {planner['goal']}.\nФорматы: {planner['formats']}.\n"
                    f"Частота публикаций: {planner['frequency']}.\nСрок: {planner['duration']} дней.\n"
                    "Структура ответа: по дням (День 1, День 2...), "
                    "каждый день = сторис + рилс или пост-карусель, с четкими темами и CTA. "
                    "В конце добавь рубрикатор, примеры заголовков и идеи визуалов. "
                    "Если план длинный – отправляй сообщениями по частям, пока не закончишь."
                )
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response["choices"][0]["message"]["content"]
                await update.message.reply_text(result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка при генерации плана.")
                print("Planner Error:", e)

            session["state"] = "roles_menu"
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ План готов! Выбери следующую задачу:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # ✅ 5. ПРОДЮСЕР REELS
    if session.get("state", "").startswith("reels_"):
        reels = session.setdefault("reels_data", {})

        if session["state"] == "reels_topic":
            reels["topic"] = text
            session["state"] = "reels_format"
            await update.message.reply_text("🎥 Укажи формат: с лицом / без лица / монтаж.")
            return

        elif session["state"] == "reels_format":
            reels["format"] = text
            session["state"] = "reels_style"
            await update.message.reply_text("🎨 Укажи стиль: экспертный / с юмором / душевный.")
            return

        elif session["state"] == "reels_style":
            reels["style"] = text
            session["state"] = "reels_audio"
            await update.message.reply_text("🎶 Есть ли музыка или референс? (отправь ссылку или опиши).")
            return

        elif session["state"] == "reels_audio":
            reels["audio"] = text
            await update.message.reply_text("🛠️ Формирую сценарий Reels, подожди...")

            try:
                prompt = (
                    f"Создай сценарий короткого видео (Reels/TikTok) для темы: {reels['topic']}.\n"
                    f"Формат: {reels['format']}. Стиль: {reels['style']}. Музыка/референс: {reels['audio']}.\n"
                    "Структура: Хук (2-3 сек), Основной блок (действия, текст, визуал), CTA, альтернатива (с лицом/без), подсказки по монтажу."
                )
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}]
                )
                result = response["choices"][0]["message"]["content"]
                await update.message.reply_text(result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка при генерации сценария.")
                print("Reels Error:", e)

            session["state"] = "roles_menu"
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Сценарий готов! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # ✅ 6. Если ничего не подошло
    await update.message.reply_text("Нажми /start, чтобы начать заново.")

# === ЗАПУСК БОТА ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ✅ Хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот запущен! Ожидаю сообщения...")
    app.run_polling()
