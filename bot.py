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

# === Обработка кнопок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    sessions.setdefault(user_id, {"state": None, "data": {}, "step": 0})

    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "base_no":
        kb = [
            [InlineKeyboardButton("Использовать бота «Распаковка ЦА»", callback_data="use_other_bot")],
            [InlineKeyboardButton("Заполнить данные здесь", callback_data="fill_here")]
        ]
        await query.edit_message_text("❗ Хорошо! Выбери, как будем собирать данные:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Ссылка на бота по распаковке (пока в разработке).")

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
        await query.edit_message_text("✅ Отлично! Полная информация получена. Сейчас подготовлю контент-стратегию.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("📊 Контент-стратег", callback_data="role_strateg")],
            [InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем помочь:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "menu_roles"

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
        await query.edit_message_text(
            f"✍️ Отлично! Задача: *{task}*.\n\n1️⃣ Укажи цель текста (продажа, вовлечение, лид-магнит).",
            parse_mode="Markdown"
        )

# === Обработка сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions.get(user_id, {})

    # --- Пошаговый сбор базовой информации ---
    if session.get("state") == "collecting_info":
        step = session.get("step", 0)
        session["data"].setdefault("info", []).append(text)
        step += 1
        if step < len(INFO_QUESTIONS):
            session["step"] = step
            await update.message.reply_text(f"👍 Отлично! {INFO_QUESTIONS[step]}", parse_mode="Markdown")
        else:
            kb = [
                [InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]
            ]
            await update.message.reply_text("Ты хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_question"

    elif session.get("state") == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Информация дополнена. Переходи в меню:", reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "roles_menu"

    # --- ✅ Новый диалог для копирайтера ---
    elif session.get("state", "").startswith("copywriter_"):
        step = session.get("step", 0)
        task = session.get("task", "пост")
        session.setdefault("copy_data", [])
        session["copy_data"].append(text)
        step += 1
        session["step"] = step

        if step == 1:
            await update.message.reply_text("2️⃣ Укажи тему текста (например: продвижение курса, экспертная статья).")
        elif step == 2:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
        elif step == 3:
            goal, topic, tone = session["copy_data"]
            await update.message.reply_text("✍️ Пишу текст, подожди...")

            try:
                prompt = (
                    f"Ты профессиональный копирайтер. Напиши {task}.\n"
                    f"🎯 Цель: {goal}\n📌 Тема: {topic}\n🎨 Тональность: {tone}\n"
                    "Пиши цепко, без воды, современным языком 2024."
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

            # сброс состояния
            session["state"] = "roles_menu"
            session["step"] = 0
            session["copy_data"] = []
            kb = [[InlineKeyboardButton("Вернуться в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Готово! Выбери новую задачу:", reply_markup=InlineKeyboardMarkup(kb))

    else:
        await update.message.reply_text("Нажми /start, чтобы начать заново.")

# === ЗАПУСК ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Бот запущен!")
    app.run_polling()
