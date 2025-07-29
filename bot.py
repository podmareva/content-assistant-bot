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
    "Имиджевая": "Метрика: упоминания, рост подписчиков, вовлеченность. Форматы: истории о себе/бренде, ценности, кейсы.",
    "Вовлекающая": "Метрика: лайки, комментарии, сохранения. Форматы: опросы, викторины, челленджи, вопросы.",
    "Образовательная": "Метрика: сохранения, переходы. Форматы: инструкции, гайды, чек-листы, экспертные советы.",
    "Продающая": "Метрика: лиды, заявки, продажи. Форматы: офферы, акции, отзывы, демонстрация продукта.",
    "Прогревающая": "Метрика: комментарии, заявки. Форматы: истории клиентов, закулисье, полезные факты.",
    "Вирусная": "Метрика: репосты, охват. Форматы: тренды, мемы, провокации, эмоциональные видео.",
    "Информационная": "Метрика: переходы, реакции. Форматы: анонсы, новости, релизы.",
    "Развлекательная": "Метрика: лайки, репосты. Форматы: юмор, игры, легкие факты, блиц-опросы."
}

# === Цели Планировщика ===
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

    elif query.data == "base_no":
        kb = [[InlineKeyboardButton("Использовать бота «Распаковка ЦА»", callback_data="use_other_bot")],
              [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")]]
        await query.edit_message_text("❗ Хорошо! Выбери, как будем собирать данные:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Ссылка на бота по распаковке (в разработке).")

    elif query.data == "fill_here":
        sessions[user_id]["state"] = "collecting_info"
        sessions[user_id]["step"] = 0
        await query.edit_message_text(INFO_QUESTIONS[0], parse_mode="Markdown")

    elif query.data == "add_extra_info":
        sessions[user_id]["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Жду дополнительную информацию по ЦА. Отправь её одним сообщением.")

    elif query.data == "no_extra_info":
        sessions[user_id]["state"] = "roles_menu"
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Отлично! Полная информация получена.", reply_markup=InlineKeyboardMarkup(kb))

    # === Меню ролей ===
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("📊 Контент-стратег", callback_data="role_strateg")],
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем помочь:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "menu_roles"

    # === Контент-Стратег ===
    elif query.data == "role_strateg":
        sessions[user_id]["state"] = "strateg_1"
        sessions[user_id]["strateg_data"] = []
        await query.edit_message_text("📌 Укажи платформу (Instagram, Telegram, ВК и т.д.):")

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

    # === Сбор базовой информации ===
    if session.get("state") == "collecting_info":
        step = session.get("step", 0)
        session["data"].setdefault("info", []).append(text)
        step += 1
        if step < len(INFO_QUESTIONS):
            session["step"] = step
            await update.message.reply_text(f"👍 Отлично! {INFO_QUESTIONS[step]}", parse_mode="Markdown")
        else:
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
            await update.message.reply_text("Ты хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_question"

    # === Доп.инфо по ЦА ===
    elif session.get("state") == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Отлично! Полная информация получена. Переходи в меню:",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "roles_menu"

    # === Контент-Стратег ===
    elif session.get("state", "").startswith("strateg_"):
        step = int(session["state"].split("_")[1])
        session.setdefault("strateg_data", []).append(text)

        if step == 1:
            session["state"] = "strateg_2"
            await update.message.reply_text("🎯 Укажи цель: привлечение / продажи / личный бренд / прогрев.")
        elif step == 2:
            session["state"] = "strateg_3"
            await update.message.reply_text("📌 Укажи форматы: Reels / посты / сторис.")
        elif step == 3:
            session["state"] = "strateg_4"
            await update.message.reply_text("⏳ Укажи частоту публикаций (пример: рилс – ежедневно, пост – раз в неделю).")
        elif step == 4:
            session["state"] = "strateg_5"
            await update.message.reply_text("📅 На какой срок нужен контент-план? (7, 14 или 21 день)")
        elif step == 5:
            platform, goal, formats, frequency, duration = session["strateg_data"]
            await update.message.reply_text("🧠 Формирую контент-стратегию, подожди...")

            try:
                prompt = (
                    f"Ты — эксперт по контент-стратегиям. Составь глубокую стратегию для {platform}.\n"
                    f"🎯 Цель: {goal}\n📌 Форматы: {formats}\n📅 Частота: {frequency}\n⏳ Срок: {duration} дней.\n\n"
                    "❗ Учитывай данные пользователя (распаковка, позиционирование, ЦА).\n"
                    "Выдай:\n- План по дням\n- Рубрикатор\n- Воронку (холодная/тёплая/горячая)\n- Примеры заголовков и CTA."
                )
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                        messages=[{"role": "user", "content": prompt}])
                result = response["choices"][0]["message"]["content"]
                await update.message.reply_text(result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка при генерации стратегии.")
                print("OpenAI Error:", e)

            session["state"] = "roles_menu"
            session["strateg_data"] = []
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Стратегия готова!", reply_markup=InlineKeyboardMarkup(kb))

    # === Планировщик ===
    elif session.get("state", "").startswith("planner_"):
        step = int(session["state"].split("_")[1])
        session.setdefault("planner_data", []).append(text)

        if step == 1:
            session["state"] = "planner_2"
            await update.message.reply_text("📌 Укажи основную соцсеть (Instagram, Telegram, ВК).")
        elif step == 2:
            session["state"] = "planner_3"
            await update.message.reply_text("🔄 Нужна ли адаптация под другие соцсети? (да/нет)")
        elif step == 3:
            session["state"] = "planner_4"
            await update.message.reply_text("⏳ Укажи частоту публикаций (пример: пост – 3 раза в неделю, сторис – ежедневно).")
        elif step == 4:
            session["state"] = "planner_5"
            await update.message.reply_text("👤 От чьего лица вести: 1 лицо / бренд?")
        elif step == 5:
            session["state"] = "planner_6"
            await update.message.reply_text("📅 На какой срок нужен план? (7, 10 или 30 дней)")
        elif step == 6:
            goal, platform, adaptation, frequency, persona, duration = session["planner_data"]
            await update.message.reply_text("🧠 Составляю индивидуальный контент-план, подожди...")

            try:
                prompt = (
                    f"Ты — контент-планировщик. Составь план для {platform}.\n🎯 Цель: {goal}\n"
                    f"🔄 Адаптация: {adaptation}\n⏳ Частота: {frequency}\n👤 От чьего лица: {persona}\n📅 Срок: {duration} дней.\n\n"
                    "Выдай:\n- План по дням\n- Темы, формат, CTA\n- Идеи сторис\n- Визуальные подсказки.\n"
                )
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                        messages=[{"role": "user", "content": prompt}])
                result = response["choices"][0]["message"]["content"]
                await update.message.reply_text(result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка при генерации плана.")
                print("OpenAI Error:", e)

            session["state"] = "roles_menu"
            session["planner_data"] = []
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Контент-план готов!", reply_markup=InlineKeyboardMarkup(kb))

    # === Копирайтер (с поддержкой пост-карусели) ===
    elif session.get("state", "").startswith("copywriter_"):
        step = session.get("step", 0)
        task = session.get("task", "пост")
        session.setdefault("copy_data", []).append(text)
        step += 1
        session["step"] = step

        if step == 2:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
        elif step == 3:
            await update.message.reply_text("4️⃣ Укажи формат (пост, Reels-текст, пост-карусель, оффер, лид-магнит).")
        elif step == 4:
            goal, topic, tone, format_text = session["copy_data"]

            # === Инструкция для поста-карусели ===
            if format_text.lower() == "пост-карусель":
                format_instruction = (
                    "Используй структуру поста-карусели (10 слайдов):\n"
                    "1. Крючок\n2. Проблема\n3. Усиление боли\n4. Решение\n5–8. Контент (1 тезис на слайд)\n"
                    "9. CTA\n10. Оффер/экспертность."
                )
            else:
                format_instruction = "Стандартная структура: Заголовок → Вступление → Основная часть → CTA → Оффер."

            await update.message.reply_text("✍️ Пишу текст, подожди...")

            try:
                prompt = (
                    f"Ты — копирайтер. Напиши {task}.\n🎯 Цель: {goal}\n📌 Тема: {topic}\n🎨 Тональность: {tone}\nФормат: {format_text}\n\n"
                    f"{format_instruction}\nПиши цепко, по-человечески, без клише. Учитывай правила рекламы РФ."
                )
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                        messages=[{"role": "user", "content": prompt}])
                result = response["choices"][0]["message"]["content"]
                await update.message.reply_text(result)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка при генерации текста.")
                print("OpenAI Error:", e)

            session["state"] = "roles_menu"
            session["copy_data"] = []
            session["step"] = 0
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Текст готов!", reply_markup=InlineKeyboardMarkup(kb))

    # === Продюсер Reels ===
    elif session.get("state", "").startswith("reels_"):
        step = int(session["state"].split("_")[1])
        session.setdefault("reels_data", []).append(text)

        if step == 1:
            session["state"] = "reels_2"
            await update.message.reply_text("📌 Укажи формат ролика: с лицом / без лица / монтаж.")
        elif step == 2:
            session["state"] = "reels_3"
            await update.message.reply_text("🎨 Укажи стиль: экспертный / с юмором / душевный.")
        elif step == 3:
            session["state"] = "reels_4"
            await update.message.reply_text("🎵 Есть ли музыка, звук или референс? (пришли ссылку или напиши 'нет')")
        elif step == 4:
            topic, format_video, style, music = session["reels_data"]
            await update.message.reply_text("🎬 Создаю сценарий Reels, подожди...")

            try:
                prompt = (
                    f"Ты — продюсер Reels. Создай сценарий для Instagram/TikTok.\n🎯 Тема: {topic}\nФормат: {format_video}\n"
                    f"Стиль: {style}\nМузыка/референс: {music}\n\nВыдай:\n- Хук (2–3 сек)\n- Основной блок (действия, текст, визуал)\n"
                    "- CTA\n- Альтернатива: с лицом и без\n- Подсказки по монтажу, свету.\nУчитывай тренды 2024–2025."
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

    # === Если нет состояния ===
    else:
        await update.message.reply_text("Нажми /start, чтобы начать заново.")

# === ЗАПУСК БОТА ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # === Обработчики ===
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Бот запущен и ожидает сообщений!")
    app.run_polling()
