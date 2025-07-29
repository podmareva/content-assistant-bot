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

if "RUNNING_BOT" in os.environ:
    print("❌ Бот уже запущен. Останови другой процесс.")
    sys.exit(1)
os.environ["RUNNING_BOT"] = "1"

sessions = {}

# === Вопросы для сбора информации ===
INFO_QUESTIONS = [
    "Пришли, пожалуйста, свою распаковку личности и экспертности.\n💡 *Распаковка* — описание ценностей и опыта.",
    "Супер! Благодарю! Теперь пришли своё позиционирование.\n💡 *Позиционирование* — чем занимаешься и для кого.",
    "Отлично! Теперь краткая характеристика продукта/услуги.\n💡 Опиши, что предлагаешь и пользу для клиента.",
    "Супер! Теперь анализ твоей ЦА.\n💡 Опиши аудиторию, боли, страхи, желания."
]

# === Цели постов ===
POST_GOALS = {
    "Имиджевая": "Метрика: упоминания, рост подписчиков. Форматы: истории, ценности, миссия, кейсы.",
    "Вовлекающая": "Метрика: лайки, комментарии. Форматы: опросы, челленджи, вопросы.",
    "Образовательная": "Метрика: сохранения, переходы. Форматы: гайды, инструкции, чек-листы.",
    "Продающая": "Метрика: лиды, заявки, продажи. Форматы: офферы, акции, отзывы.",
    "Прогревающая": "Метрика: заявки после серии постов. Форматы: кейсы, закулисье, факты.",
    "Вирусная": "Метрика: репосты, охват. Форматы: тренды, мемы, провокации.",
    "Информационная": "Метрика: переходы, реакции. Форматы: анонсы, новости, релизы.",
    "Развлекательная": "Метрика: удержание, репосты. Форматы: юмор, подборки, игры."
}

# === Цели планировщика ===
PLANNER_GOALS = [
    "Набор подписчиков",
    "Продажа продукта",
    "Повышение узнаваемости бренда",
    "Вовлечение аудитории",
    "Прогрев перед запуском",
    "Удержание клиентов"
]

# === Приветствие ===
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент». Он поможет:\n"
    "• создать контент-стратегию;\n• контент-план;\n• посты и офферы;\n• сценарии для Reels.\n\n"
    "🔐 Подтверди согласие с [Политикой](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit) "
    "и [Офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и начнём!"
)

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# === ОБРАБОТКА КНОПОК ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    sessions.setdefault(user_id, {"state": None, "data": {}, "step": 0})

    # --- Согласие ---
    if query.data == "agree":
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # === Пользователь выбрал "ДА ✅" ===
    elif query.data == "base_yes":
        sessions[user_id]["state"] = "collecting_info_yes"
        sessions[user_id]["step"] = 0
        sessions[user_id]["data"]["info"] = []
        await query.edit_message_text("Отлично! Пришли, пожалуйста, свою распаковку личности и экспертности.")

    # === Пользователь выбрал "НЕТ ❌" ===
    elif query.data == "base_no":
        kb = [[InlineKeyboardButton("Использовать бота «Распаковка ЦА»", callback_data="use_other_bot")],
              [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")]]
        await query.edit_message_text("❗ Хорошо! Выбери, как будем собирать данные:",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Ссылка на бота по распаковке (в разработке).")

    elif query.data == "fill_here":
        sessions[user_id]["state"] = "collecting_info"
        sessions[user_id]["step"] = 0
        await query.edit_message_text(INFO_QUESTIONS[0], parse_mode="Markdown")

    # === Доп.инфо после "ДА" ===
    elif query.data == "add_extra_info_yes":
        sessions[user_id]["state"] = "waiting_extra_info_yes"
        await query.edit_message_text("✍️ Тогда жду дополнительные данные по ЦА. Отправь одним сообщением.")

    elif query.data == "no_extra_info_yes":
        sessions[user_id]["state"] = "roles_menu"
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Отлично! Полная информация получена. Сейчас подготовлю стратегию.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # === Доп.инфо после "НЕТ" ===
    elif query.data == "add_extra_info":
        sessions[user_id]["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Жду дополнительную информацию по ЦА. Отправь её одним сообщением.")

    elif query.data == "no_extra_info":
        sessions[user_id]["state"] = "roles_menu"
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Отлично! Полная информация получена. Сейчас подготовлю стратегию.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # === Меню ролей ===
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем помочь:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "menu_roles"

    # === Планировщик ===
    elif query.data == "role_planner":
        sessions[user_id]["state"] = "planner_1"
        sessions[user_id]["planner_data"] = []
        goals_text = "\n".join([f"– {g}" for g in PLANNER_GOALS])
        await query.edit_message_text(f"🎯 Укажи цель контента:\n{goals_text}")

    # === Копирайтер ===
    elif query.data == "role_copywriter":
        kb = [
            [InlineKeyboardButton("Написать пост", callback_data="copy_post")],
            [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
            [InlineKeyboardButton("Придумать оффер", callback_data="copy_offer")],
            [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("Упаковка продукта", callback_data="copy_package")]
        ]
        await query.edit_message_text("🖊️ Я копирайтер! Что делаем?", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "copywriter_menu"

    # === Подзадачи копирайтера ===
    elif query.data.startswith("copy_"):
        task = query.data.split("_", 1)[1]
        sessions[user_id]["state"] = f"copywriter_{task}"
        sessions[user_id]["task"] = task
        sessions[user_id]["step"] = 0
        sessions[user_id]["copy_data"] = []
        kb = [[InlineKeyboardButton(goal, callback_data=f"goal_{goal}")] for goal in POST_GOALS.keys()]
        await query.edit_message_text("🎯 Выбери цель поста:", reply_markup=InlineKeyboardMarkup(kb))

    # === Выбор цели поста ===
    elif query.data.startswith("goal_"):
        goal = query.data.split("_", 1)[1]
        sessions[user_id]["copy_data"] = [goal]
        sessions[user_id]["step"] = 1
        await query.edit_message_text(f"✅ Цель выбрана: *{goal}*\n\n{POST_GOALS[goal]}\n\n2️⃣ Укажи тему текста:",
                                      parse_mode="Markdown")

    # === Продюсер Reels ===
    elif query.data == "role_reels":
        sessions[user_id]["state"] = "reels_1"
        sessions[user_id]["reels_data"] = []
        await query.edit_message_text("🎬 Укажи тему и цель ролика:")

# === ОБРАБОТКА СООБЩЕНИЙ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions.get(user_id, {})

    # === Сбор данных (если выбрали "НЕТ") ===
    if session.get("state") == "collecting_info":
        step = session.get("step", 0)
        session["data"].setdefault("info", []).append(text)
        step += 1
        session["step"] = step

        if step < len(INFO_QUESTIONS):
            await update.message.reply_text(f"👍 Отлично! {INFO_QUESTIONS[step]}", parse_mode="Markdown")
        else:
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
            await update.message.reply_text("Ты хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_question"

    # === Сбор данных (если выбрали "ДА") ===
    elif session.get("state") == "collecting_info_yes":
        step = session.get("step", 0)
        session["data"]["info"].append(text)
        step += 1
        session["step"] = step

        if step == 1:
            await update.message.reply_text("Супер! Благодарю! Теперь пришли своё позиционирование.")
        elif step == 2:
            await update.message.reply_text("Отлично! Теперь пришли краткую характеристику продукта/услуги.")
        elif step == 3:
            await update.message.reply_text("Супер! Теперь высылай анализ ЦА.")
        elif step == 4:
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info_yes")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info_yes")]]
            await update.message.reply_text("Хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_info_yes"

    # === Доп.инфо по ЦА (после ДА) ===
    elif session.get("state") == "waiting_extra_info_yes":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Отлично! Полная информация получена. Сейчас подготовлю стратегию.",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "roles_menu"

    # === Доп.инфо по ЦА (после НЕТ) ===
    elif session.get("state") == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Отлично! Полная информация получена. Сейчас подготовлю стратегию.",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "roles_menu"

    # === Обработка диалога Планировщика ===
elif session.get("state", "").startswith("planner_"):
    step = session.get("step", 0)
    session.setdefault("planner_data", [])
    session["planner_data"].append(text)
    step += 1
    session["step"] = step

    # Вопросы планировщика
    planner_questions = [
        "📌 Укажи цель (например: набор подписчиков, продажи продукта, прогрев, личный бренд).",
        "📌 Основная соцсеть и нужна ли адаптация (например: Instagram, Telegram, TikTok).",
        "📌 Укажи частоту публикаций (например: сторис ежедневно, рилс 3 раза в неделю, посты 2 раза в неделю).",
        "📌 От чьего лица вести аккаунт? (1 лицо или бренд)",
        "📌 На какой срок нужен план? (7, 10 или 30 дней)"
    ]

    if step < len(planner_questions):
        await update.message.reply_text(planner_questions[step])
    else:
        # Все данные собраны → формируем запрос
        goal, platform, frequency, persona, days = session["planner_data"]
        await update.message.reply_text("🧠 Формирую индивидуальный контент-план, подожди...")

        try:
            prompt = (
                f"Ты контент-планировщик. Построй индивидуальный контент-план строго на {days} дней.\n"
                f"Тематика: {session['planner']['topic']}\n"
                f"Платформа: {session['planner']['platform']}\n"
                f"Цель: {session['planner']['goal']}\n"
                f"Частота публикаций: {session['planner']['frequency']}\n\n"
                "📌 Правила:\n"
                "1. Строго следуй частоте (не пропускай, не меняй местами).\n"
                "2. Каждый день выдай:\n"
                "   – Сторис (тема и CTA)\n"
                "   – Либо Рилс, либо Пост/Карусель (с учетом частоты).\n"
                "3. Если рилс/пост не запланирован на день – пропусти его, оставь только сторис.\n"
                "4. Не используй 'и так далее'. Выдай план полностью.\n"
                "5. Если план длинный – разбей на несколько сообщений, но выдай его весь.\n\n"
                "Формат ответа:\n"
                "День 1:\n– Сторис: ...\n– Рилс: ... (если есть)\n– Пост/Карусель: ... (если есть)\n\n"
                "В конце добавь: Идеи визуалов (отдельным блоком)."
            )

            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            result = response["choices"][0]["message"]["content"]

            # === Разбиваем текст на части по 📅 День ===
            parts = result.split("📅")
            for i, chunk in enumerate(parts):
                if not chunk.strip():
                    continue
                formatted_chunk = ("📅" + chunk) if i > 0 else chunk
                await update.message.reply_text(formatted_chunk.strip())

            # === Отправляем идеи визуалов, если есть ===
            if "Идеи визуалов" in result:
                visuals = result.split("Идеи визуалов", 1)[1]
                await update.message.reply_text("🎨 *Идеи визуалов:*" + visuals, parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка при генерации плана.")
            print("Planner OpenAI Error:", e)

        # Сбрасываем состояние
        session["state"] = "roles_menu"
        session["step"] = 0
        session["planner_data"] = []
        kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("✅ План готов! Можешь запросить новую задачу:", reply_markup=InlineKeyboardMarkup(kb))

    # === Копирайтер (диалог с новым шагом) ===
elif session.get("state", "").startswith("copywriter_"):
    step = session.get("step", 0)
    task = session.get("task")
    session.setdefault("copy_data", [])

    # Сохраняем ответы пользователя
    session["copy_data"].append(text)
    step += 1
    session["step"] = step

    # === Логика шагов ===
    if step == 1:
        await update.message.reply_text("2️⃣ Укажи тему текста (например: продвижение курса, экспертная статья).")

    elif step == 2:
        # 🔥 Новый шаг: спрашиваем формат (развернутый / краткий)
        await update.message.reply_text("📝 Хочешь пост развернутый или краткий, но емкий?")

    elif step == 3:
        session["copy_type"] = text  # Сохраняем выбор формата
        await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")

    elif step == 4:
        await update.message.reply_text("4️⃣ Укажи формат (пост, Reels-текст, пост-карусель, оффер, лид-магнит).")

    elif step == 5:
        await update.message.reply_text("✍️ Пишу текст, подожди...")

        # Извлекаем данные для OpenAI
        goal, topic, copy_type, tone, format_text = session["copy_data"][0], session["copy_data"][1], session.get("copy_type", "краткий"), session["copy_data"][2], session["copy_data"][3]

        # Если формат = пост-карусель, добавляем инструкцию
        format_instruction = ""
        if format_text.lower() == "пост-карусель":
            format_instruction = (
                "📌 Используй структуру поста-карусели (10 слайдов):\n"
                "1. Крючок\n2. Проблема\n3. Усиление боли\n4. Обещание решения\n5-8. Полезный контент\n"
                "9. CTA\n10. Оффер/экспертность\n"
                "Текст до 12 слов/слайд, добавь цепкий CTA и заверши оффером клиента."
            )

        try:
            # === Запрос к OpenAI ===
            prompt = (
                f"Ты профессиональный копирайтер. Напиши {task} для клиента.\n\n"
                f"🎯 Цель: {goal}\n📌 Тема: {topic}\n📝 Формат поста: {copy_type}\n🎨 Тональность: {tone}\n"
                f"Формат публикации: {format_text}\n{format_instruction}\n\n"
                "❗ Пиши от лица клиента, без клише, в стиле 2024–2025. "
                "Если пост краткий — делай его ёмким и цепким. Если развернутый — глубоко раскрывай тему."
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

        # Сбрасываем состояние
        session["state"] = "roles_menu"
        session["step"] = 0
        session["copy_data"] = []
        kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Текст готов! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))

    # === Продюсер Reels ===
    elif session.get("state", "").startswith("reels_"):
        step = int(session["state"].split("_")[1])
        session.setdefault("reels_data", []).append(text)

        if step == 1:
            session["state"] = "reels_2"
            await update.message.reply_text("🎬 Укажи формат: с лицом / без лица / монтаж.")
        elif step == 2:
            session["state"] = "reels_3"
            await update.message.reply_text("🎨 Укажи стиль: экспертный / с юмором / душевный.")
        elif step == 3:
            session["state"] = "reels_4"
            await update.message.reply_text("🎵 Есть ли музыка или референс?")
        elif step == 4:
            topic, format_video, style, music = session["reels_data"]
            await update.message.reply_text("🎥 Генерирую сценарий, подожди...")

            try:
                prompt = (
                    f"Ты — продюсер Reels. Создай сценарий для клиента, используя только его данные.\n\n"
                    f"📌 Клиент:\n- Распаковка: {session['data'].get('info', [''])[0]}\n"
                    f"- Позиционирование: {session['data'].get('info', ['',''])[1]}\n"
                    f"- Продукт: {session['data'].get('info', ['','',''])[2]}\n"
                    f"- ЦА: {session['data'].get('info', ['','','',''])[3]}\n\n"
                    f"🎬 Тема: {topic}\nФормат: {format_video}\nСтиль: {style}\nМузыка/реф: {music}\n\n"
                    "❗ Пиши сценарий от лица клиента, не придумывай нишу. "
                    "Выдай:\n- Хук (2–3 сек)\n- Основной блок (текст, действия, визуал)\n- CTA\n- Альтернатива (с лицом/без)\n- Подсказки по монтажу."
                )
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                        messages=[{"role": "user", "content": prompt}])
                result = response["choices"][0]["message"]["content"]
                await update.message.reply_text(result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка при генерации сценария.")
                print("OpenAI Error:", e)

            session["state"] = "roles_menu"
            session["reels_data"] = []
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Сценарий готов!", reply_markup=InlineKeyboardMarkup(kb))

    else:
        await update.message.reply_text("Нажми /start, чтобы начать заново.")

# === ЗАПУСК БОТА ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Бот запущен!")
    app.run_polling()
