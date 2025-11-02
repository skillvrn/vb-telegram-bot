import os
import json
import datetime
import asyncio
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN not found in environment variables. Please set it."
    )

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
if not ADMIN_CHAT_ID:
    raise ValueError(
        "ADMIN_CHAT_ID not found in environment variables. Please set it."
    )

VOLLEYBALL_CHAT_ID = os.getenv("VOLLEYBALL_CHAT_ID")
if not VOLLEYBALL_CHAT_ID:
    raise ValueError(
        "VOLLEYBALL_CHAT_ID not found in environment variables. Please set it."
    )

ORGANIZER_CHAT_ID = os.getenv("ORGANIZER_CHAT_ID")
if not ORGANIZER_CHAT_ID:
    raise ValueError(
        "ORGANIZER_CHAT_ID not found in environment variables. Please set it."
    )

PAYMENT_INFORMATION = os.getenv("PAYMENT_INFORMATION")
if not PAYMENT_INFORMATION:
    raise ValueError(
        "PAYMENT_INFORMATION not found in environment variables. "
        "Please set it."
    )

DATA_FILE = "/app/data/players.json"
STATE_FILE = "/app/data/bot_state.json"
GAME_DAY = "воскресенье"

# Список игроков, каждый — словарь с user_id, first_name, last_name, username
players: list[dict[str, str | int]] = []
pending_confirmations = set()
MAX_PLAYERS = 12

# Переменная для отслеживания состояния ожидания ответа от организатора
waiting_organizer_response = False

# ---------------- 📁 Работа с файлами ----------------

def load_players():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            players[:] = data
            print("✅ Игроки загружены из файла.")
    except FileNotFoundError:
        players.clear()

def save_players():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False)

def load_bot_state():
    """Загружает состояние бота (открыта/закрыта запись)"""
    global REGISTRATION_OPEN
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            REGISTRATION_OPEN = state.get('registration_open', True)
            print(f"✅ Состояние бота загружено. Запись: {'открыта' if REGISTRATION_OPEN else 'закрыта'}")
    except FileNotFoundError:
        REGISTRATION_OPEN = True
        print("✅ Файл состояния не найден, установлено значение по умолчанию: запись открыта")
    except Exception as e:
        REGISTRATION_OPEN = True
        print(f"⚠️ Ошибка загрузки состояния: {e}, установлено значение по умолчанию")

def save_bot_state():
    """Сохраняет состояние бота"""
    try:
        state = {
            'registration_open': REGISTRATION_OPEN,
            'last_updated': datetime.datetime.now().isoformat()
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"💾 Состояние бота сохранено. Запись: {'открыта' if REGISTRATION_OPEN else 'закрыта'}")
    except Exception as e:
        print(f"❌ Ошибка сохранения состояния: {e}")

# Загружаем состояние при старте
load_bot_state()

# ---------------- 🤖 Команды бота ----------------

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📥 Записаться"), KeyboardButton("📤 Отписаться")],
        [KeyboardButton("📋 Список игроков")]
    ],
    resize_keyboard=True
)

def is_registered(user_id):
    return any(p['user_id'] == user_id for p in players)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! "
        "Добро пожаловать в волейбольный бот 🏐",
        reply_markup=main_keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_organizer_response, REGISTRATION_OPEN

    user = update.effective_user
    text = update.message.text

    # Обработка ответа от организатора
    if str(user.id) == ORGANIZER_CHAT_ID and waiting_organizer_response:
        if text.lower() in ["да", "yes"]:
            # Отправляем сообщение об оплате в чат волейбола
            payment_text = (
                f"Всем спасибо за игру! Не забудьте перевести деньги "
                f"на номер {PAYMENT_INFORMATION}."
            )
            await context.bot.send_message(
                chat_id=VOLLEYBALL_CHAT_ID,
                text=payment_text
            )
            waiting_organizer_response = False
            await update.message.reply_text(
                "✅ Сообщение об оплате отправлено в чат!"
            )
        elif text.lower() in ["нет", "no"]:
            waiting_organizer_response = False
            await update.message.reply_text("✅ Хорошо, игра не состоялась.")
        else:
            await update.message.reply_text(
                "Пожалуйста, ответьте 'Да' или 'Нет'"
            )
        return

    # Теперь достаточно только имени
    if not user.first_name:
        await update.message.reply_text(
            "⚠️ У вас не указано имя в Telegram. "
            "Пожалуйста, укажите его в настройках."
        )
        return

    if text == "📥 Записаться":
        if not REGISTRATION_OPEN:
            await update.message.reply_text("⛔️ Запись уже закрыта.")
            return
        if is_registered(user.id):
            await update.message.reply_text("Вы уже записаны ✅")
        elif len(players) >= MAX_PLAYERS:
            await update.message.reply_text(
                "⛔️ Все места заняты! Максимум 12 человек."
            )
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
        if is_registered(user.id):
            players[:] = [p for p in players if p['user_id'] != user.id]
            save_players()
            await update.message.reply_text("Вы отписались от волейбола.")
            await context.bot.send_message(
                chat_id=VOLLEYBALL_CHAT_ID,
                text=(
                    f"⚠️ {user.first_name} "
                    f"{user.last_name or ''} освободил место на "
                    "волейбол."
                )
            )
        else:
            await update.message.reply_text("Вы не были записаны.")

    elif text == "📋 Список игроков":
        if players:
            player_list = "\n".join(
                [
                    f"{i+1}. {p['first_name']} {p['last_name']} "
                    f"(@{p.get('username', '')})".strip()
                    for i, p in enumerate(players)
                ]
            )
            status_info = f"Запись: {'✅ ОТКРЫТА' if REGISTRATION_OPEN else '❌ ЗАКРЫТА'}\n"
            await update.message.reply_text(
                f"{status_info}📋 Список игроков ({len(players)}/{MAX_PLAYERS}):\n{player_list}"
            )
        else:
            status_info = f"Запись: {'✅ ОТКРЫТА' if REGISTRATION_OPEN else '❌ ЗАКРЫТА'}\n"
            await update.message.reply_text(f"{status_info}Список пуст.")

    elif text == "✅ Да":
        if user.id in pending_confirmations:
            if len(players) >= MAX_PLAYERS:
                await update.message.reply_text(
                    "⛔️ Все места заняты! Максимум 12 человек.",
                    reply_markup=main_keyboard
                )
            elif is_registered(user.id):
                await update.message.reply_text(
                    "Вы уже записаны ✅",
                    reply_markup=main_keyboard
                )
            else:
                players.append({
                    'user_id': user.id,
                    'first_name': user.first_name,
                    'last_name': user.last_name or "",
                    'username': user.username or ""
                })
                save_players()
                pending_confirmations.remove(user.id)
                await update.message.reply_text(
                    f"Вы записались на волейбол в {GAME_DAY}! ✅",
                    reply_markup=main_keyboard
                )
                await context.bot.send_message(
                    chat_id=VOLLEYBALL_CHAT_ID,
                    text=(
                        f"📥 {user.first_name} "
                        f"{user.last_name or ''} записался на волейбол."
                    )
                )
        else:
            await update.message.reply_text(
                "Сначала выберите '📥 Записаться' с клавиатуры.",
                reply_markup=main_keyboard
            )

    elif text == "❌ Нет":
        if user.id in pending_confirmations:
            pending_confirmations.remove(user.id)
            await update.message.reply_text(
                "Запись отменена.",
                reply_markup=main_keyboard
            )
        else:
            await update.message.reply_text(
                "Нечего отменять.",
                reply_markup=main_keyboard
            )

    else:
        await update.message.reply_text(
            "Пожалуйста, выберите действие с клавиатуры."
        )


# ---------------- ⏰ Планировщик ----------------

async def reminder_job(app):
    global REGISTRATION_OPEN, waiting_organizer_response

    while True:
        now = datetime.datetime.now()
        print(f"⏰ Проверка времени: {now}")

        # Воскресенье 20:00 - вопрос организатору
        if now.weekday() == 6 and now.hour == 17 and now.minute == 0:
            waiting_organizer_response = True
            keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton("Да"), KeyboardButton("Нет")]],
                resize_keyboard=True
            )
            await app.bot.send_message(
                chat_id=ORGANIZER_CHAT_ID,
                text="Была ли игра сегодня?",
                reply_markup=keyboard
            )
            print("❓ Задан вопрос организатору о проведении игры")
            await asyncio.sleep(60)

        # Понедельник 12:00 - открытие записи
        if now.weekday() == 0 and now.hour == 9 and now.minute == 0:
            if not REGISTRATION_OPEN:  # Открываем только если была закрыта
                REGISTRATION_OPEN = True
                save_bot_state()  # Сохраняем состояние
                registration_text = (
                    "Запись на следующее воскресенье открыта, можно записываться!"
                )
                await app.bot.send_message(
                    chat_id=VOLLEYBALL_CHAT_ID,
                    text=registration_text
                )
                print("📝 Отправлено сообщение об открытии записи")
            await asyncio.sleep(60)

        # Суббота 11:00 - закрытие записи
        if now.weekday() == 5 and now.hour == 8 and now.minute == 0:
            if REGISTRATION_OPEN:  # Закрываем только если была открыта
                REGISTRATION_OPEN = False
                save_bot_state()  # Сохраняем состояние
                print("🔒 Закрыта запись.")
                # Только уведомление в волейбольный чат о закрытии записи
                close_text = (
                    f"Запись на завтрашний волейбол закрыта.\n"
                    f"Записалось игроков: {len(players)}/{MAX_PLAYERS}"
                )
                await app.bot.send_message(
                    chat_id=VOLLEYBALL_CHAT_ID,
                    text=close_text
                )
                print("📢 Отправлено уведомление о закрытии записи в чат")
            await asyncio.sleep(60)

        # Воскресенье 20:00 - очистка списка игроков
        if now.weekday() == 6 and now.hour == 20 and now.minute == 0:
            print("🧹 Очищаем список игроков.")
            for player in players:
                try:
                    await app.bot.send_message(
                        chat_id=player['user_id'],
                        text="✅ Волейбол завершён. Список игроков очищен."
                    )
                except Exception:
                    pass
            players.clear()
            save_players()
            # Не меняем REGISTRATION_OPEN здесь, она откроется в понедельник
            await asyncio.sleep(60)

        await asyncio.sleep(30)


# ---------------- 🔧 Запуск ----------------

async def main():
    load_players()
    load_bot_state()  # Загружаем состояние бота

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.create_task(reminder_job(app))

    print("🤖 Бот запущен!")
    print(f"📝 Текущее состояние записи: {'ОТКРЫТА' if REGISTRATION_OPEN else 'ЗАКРЫТА'}")
    await app.run_polling()


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
