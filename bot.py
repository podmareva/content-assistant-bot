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

# ---------- ПРИВЕТСТВИЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент».\n\n"
    "Он поможет:\n"
    "• создать контент-стратегию\n"
    "• написать контент-план\n"
    "• написать пост\n"
    "• создать сценарий для Reels или Stories\n\n"
    "🔐 Подтверди согласие с политикой и начнем!"
)

# ==== ХЕНДЛЕРЫ ====

# /start → приветствие
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(keyboard))

# Обработка нажатий кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    sessions.setdefault(user_id, {"state": None, "data": {}})

    # Согласие → спрашиваем про основу
    if query.data == "agree":
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text(
            "Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif query.data in ["base_yes", "base_no"]:
        sessions[user_id]["state"] = "collecting_base"
        await query.edit_message_text("Отлично! Пришли информацию о себе (распаковка личности).")

    # Меню ролей
    elif query.data == "roles_menu":
        kb = [
            [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
            [InlineKeyboardButton("📊 Контент-стратег", callback_data="role_strateg")],
            [InlineKeyboardButton("📅 Контент-планировщик", callback_data="role_planner")],
            [InlineKeyboardButton("🎬 Продюсер Reels", callback_data="role_reels")]
        ]
        await query.edit_message_text("Выбери, чем я могу помочь:", reply_markup=InlineKeyboardMarkup(kb))

    # Выбор роли → копирайтер
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

# Обработка текстов → сбор данных или генерация
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    session = sessions.get(user_id, {})

    # Если пользователь заполняет основу
    if session.get("state") == "collecting_base":
        session["data"].setdefault("base_info", []).append(text)

        # После нескольких сообщений → показываем меню ролей
        if len(session["data"]["base_info"]) >= 3:
            session["state"] = "menu_roles"
            kb = [[InlineKeyboardButton("Перейти в меню ролей", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Спасибо! Базовая информация собрана.", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text("Отлично! Пришли ещё немного информации...")

    # Если копирайтер → генерируем текст
    elif session.get("state") == "copywriter_mode":
        await update.message.reply_text("✍️ Пишу текст, подожди...")

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Ты профессиональный копирайтер."},
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
