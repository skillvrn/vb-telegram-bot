import os
import json
import datetime
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables. Please set it.")

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID not found in environment variables. Please set it.")

# Файл с игроками
DATA_FILE = "/app/data/players.json"
# День игры
GAME_DAY = "воскресенье"
REGISTRATION_OPEN = True
players = set()
pending_confirmations = set()

# ---------------- 📁 Работа с файлом ----------------
def load_players():
    global players
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            players = set(data)
            print("✅ Игроки загружены из файла.")
    except FileNotFoundError:
        players = set()

def save_players():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(list(players), f)

# ---------------- 🤖 Команды бота ----------------
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📥 Записаться"), KeyboardButton("📤 Отписаться")],
        [KeyboardButton("📋 Список игроков")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! Добро пожаловать в волейбольный бот 🏐",
        reply_markup=main_keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global REGISTRATION_OPEN
    user = update.effective_user
    text = update.message.text

    if not user.username:
        await update.message.reply_text("⚠️ У вас нет username в Telegram. Установите его в настройках.")
        return

    if text == "📥 Записаться":
        if not REGISTRATION_OPEN:
            await update.message.reply_text("⛔️ Запись уже закрыта.")
            return
        if user.username in players:
            await update.message.reply_text("Вы уже записаны ✅")
        else:
            pending_confirmations.add(user.id)
            keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton("✅ Да"), KeyboardButton("❌ Нет")]],
                resize_keyboard=True
            )
            await update.message.reply_text(
                f"Волейбол будет в {GAME_DAY}. Хотите записаться?",
                reply_markup=keyboard
            )

    elif text == "📤 Отписаться":
        if user.username in players:
            players.remove(user.username)
            save_players()
            await update.message.reply_text("Вы отписались от волейбола.")
            for chat in players:
                try:
                    await context.bot.send_message(chat_id=f"@{chat}", text=f"⚠️ @{user.username} освободил место на волейбол.")
                except:
                    pass
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📤 @{user.username} отписался от волейбола."
            )
        else:
            await update.message.reply_text("Вы не были записаны.")

    elif text == "📋 Список игроков":
        if players:
            player_list = "\n".join([f"{i+1}. @{p}" for i, p in enumerate(players)])
            await update.message.reply_text(f"📋 Список игроков:\n{player_list}")
        else:
            await update.message.reply_text("Список пуст.")

    elif text == "✅ Да":
        if user.id in pending_confirmations:
            players.add(user.username)
            save_players()
            pending_confirmations.remove(user.id)
            await update.message.reply_text(
                f"Вы записались на волейбол в {GAME_DAY}! ✅",
                reply_markup=main_keyboard
            )
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📥 @{user.username} записался на волейбол."
            )
        else:
            await update.message.reply_text("Сначала выберите '📥 Записаться' с клавиатуры.", reply_markup=main_keyboard)

    elif text == "❌ Нет":
        if user.id in pending_confirmations:
            pending_confirmations.remove(user.id)
            await update.message.reply_text("Запись отменена.", reply_markup=main_keyboard)
        else:
            await update.message.reply_text("Нечего отменять.", reply_markup=main_keyboard)

    else:
        await update.message.reply_text("Пожалуйста, выберите действие с клавиатуры.")

# ---------------- ⏰ Планировщик ----------------
async def reminder_job(app):
    global REGISTRATION_OPEN

    while True:
        now = datetime.datetime.now()

        if now.weekday() == 5 and now.hour == 11 and now.minute == 0:
            REGISTRATION_OPEN = False
            print("🔒 Закрыта запись. Отправляем напоминание.")
            for username in players:
                try:
                    await app.bot.send_message(chat_id=f"@{username}", text="💸 Напоминание: не забудьте оплатить волейбол!")
                except:
                    pass
            await asyncio.sleep(60)

        if now.weekday() == 6 and now.hour == 20 and now.minute == 0:
            print("🧹 Очищаем список игроков.")
            for username in players:
                try:
                    await app.bot.send_message(chat_id=f"@{username}", text="✅ Волейбол завершён. Список игроков очищен.")
                except:
                    pass
            players.clear()
            save_players()
            REGISTRATION_OPEN = True
            await asyncio.sleep(60)

        await asyncio.sleep(30)

# ---------------- 🔧 Запуск ----------------
async def main():
    load_players()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.create_task(reminder_job(app))

    print("🤖 Бот запущен!")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())