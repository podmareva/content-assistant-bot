import os
import sys
from dotenv import load_dotenv
import openai
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

print(">>> Бот загружен, файл bot.py исполняется")

# ---------- НАСТРОЙКИ ----------
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if "RUNNING_BOT" in os.environ:
    print("❌ Бот уже запущен. Останови другой процесс, чтобы избежать конфликта.")
    sys.exit(1)
os.environ["RUNNING_BOT"] = "1"

sessions = {}

# ---------- ПРИВЕТСТВИЕ ----------
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент».\n"
    "Он поможет:\n"
    "• создать контент-стратегию\n"
    "• написать контент план\n"
    "• написать пост\n"
    "• создать сценарий для Reels или Stories\n\n"
    "🔐 Чтобы начать, подтверди согласие с политикой:\n"
    "[Политика конфиденциальности](https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v)\n"
    "[Договор-оферта](https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL)\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и начнем!"
)

# ---------- ХЕНДЛЕРЫ ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]]
    await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "agree":
        # Показываем выбор "есть ли основа?"
        kb = [
            [InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
            [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]
        ]
        await query.edit_message_text(
            "Отлично! 🙌 Есть ли у тебя уже основа для создания контента (распаковка, позиционирование, анализ ЦА)?",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif query.data == "base_yes":
        await query.edit_message_text("👍 Отлично! Пришли, пожалуйста, свою распаковку личности и экспертности.")

    elif query.data == "base_no":
        await query.edit_message_text(
            "❗ Хорошо! Тогда отправь минимальную информацию: кто ты, чем занимаешься, продукт/услуга и кто твоя ЦА.\n\n"
            "✍️ Напиши, начнем с распаковки личности."
        )

# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 Бот запущен!")
    app.run_polling()
