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
    ("Пришли, пожалуйста, свою распаковку личности и экспертности.\n"
     "💡 *Распаковка* — это описание твоих ценностей, опыта и уникальности."),
    ("Супер! Благодарю! Теперь пришли своё позиционирование.\n"
     "💡 *Позиционирование* — это краткое объяснение, чем ты занимаешься и для кого."),
    ("Отлично! Теперь пришли краткую характеристику продукта/услуги.\n"
     "💡 Опиши, что ты предлагаешь, чем это полезно клиенту."),
    ("Супер! Теперь пришли анализ твоей ЦА.\n"
     "💡 Опиши, кто твоя аудитория, их боли, страхи, желания.")
]

# ---------- ПРИВЕТСТВИЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент». Он поможет:\n"
    "• создать контент-стратегию;\n"
    "• написать контент-план;\n"
    "• написать или отредактировать пост;\n"
    "• создать сценарий для Reels или Stories.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true) и "
    "[Договором‑офертой](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit?usp=drive_link&ouid=104429050326439982568&rtpof=true&sd=true).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

# ==== ХЕНДЛЕРЫ ====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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

    # Если у пользователя НЕТ основы
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
        await query.edit_message_text(INFO_QUESTIONS[0], parse_mode="Markdown")

    # После анализа ЦА → спрашиваем про доп.инфо
    elif query.data == "add_extra_info":
        await query.edit_message_text("✍️ Тогда жду дополнительную информацию по ЦА. Отправь её одним сообщением.")
        sessions[user_id]["state"] = "waiting_extra_info"

    elif query.data == "no_extra_info":
        sessions[user_id]["state"] = "roles_menu"
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Отлично! Полная информация получена. Сейчас подготовлю контент-стратегию.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # Меню ролей
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("📊 Контент-стратег", callback_data="role_strateg")],
            [InlineKeyboardButton("📅 Контент-планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем я могу помочь:", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "menu_roles"

    # Роль копирайтера
    elif query.data == "role_copywriter":
        kb = [
            [InlineKeyboardButton("Написать пост", callback_data="copy_post")],
            [InlineKeyboardButton("Редактировать текст", callback_data="copy_edit")],
            [InlineKeyboardButton("Придумать оффер", callback_data="copy_offer")],
            [InlineKeyboardButton("Лид-магнит", callback_data="copy_lead")],
            [InlineKeyboardButton("Упаковка продукта", callback_data="copy_package")]
        ]
        await query.edit_message_text("🖊️ Я копирайтер! Чем помочь?", reply_markup=InlineKeyboardMarkup(kb))
        sessions[user_id]["state"] = "copywriter_mode"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions.get(user_id, {})

    # === Пошаговый сбор данных ===
    if session.get("state") == "collecting_info":
        step = session.get("step", 0)
        session["data"].setdefault("info", []).append(text)

        # Переход к следующему шагу
        step += 1
        if step < len(INFO_QUESTIONS):
            session["step"] = step
            await update.message.reply_text(f"👍 Отлично! {INFO_QUESTIONS[step]}", parse_mode="Markdown")
        else:
            # После анализа ЦА → спрашиваем про дополнительную информацию
            kb = [
                [InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]
            ]
            await update.message.reply_text("Ты хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra_question"

    elif session.get("state") == "waiting_extra_info":
        session["data"]["extra_info"] = text
        await update.message.reply_text("✅ Отлично! Полная информация получена. Сейчас подготовлю контент-стратегию.")
        kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
        await update.message.reply_text("👉 Нажми, чтобы перейти в меню:", reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "roles_menu"

    # === Если копирайтер ===
    elif session.get("state") == "copywriter_mode":
        await update.message.reply_text("✍️ Пишу текст, подожди...")

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты профессиональный копирайтер. Пиши цепко, современно, без воды."},
                    {"role": "user", "content": text}
                ]
            )
            result = response["choices"][0]["message"]["content"]
            await update.message.reply_text(result)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка при обращении к OpenAI.")
            print("OpenAI Error:", e)

    else:
        await update.message.reply_text("Нажми /start, чтобы начать заново.")

# ==== ЗАПУСК ====
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Бот запущен!")
    app.run_polling()
