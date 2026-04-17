import os
import json
import datetime
import asyncio
import logging
import re
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

# Инициализация глобальных переменных
players: list[dict[str, str | int]] = []
pending_confirmations = set()
pending_add_friend = set()
MAX_PLAYERS = 12
waiting_organizer_response = False
waiting_payment_amount = False
REGISTRATION_OPEN = True


def load_players():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            players[:] = data
            logger.info("✅ Игроки загружены из файла.")
    except FileNotFoundError:
        logger.info("📭 Файл игроков не найден, создаем пустой список")
        players.clear()
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки игроков: {e}")
        players.clear()


def save_players():
    try:
        # Создаем директорию, если не существует
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(players, f, ensure_ascii=False)
        logger.info(f"💾 Игроки сохранены. Всего: {len(players)}")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения игроков: {e}")


def load_bot_state():
    """Загружает состояние бота (открыта/закрыта запись)"""
    global REGISTRATION_OPEN
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            REGISTRATION_OPEN = state.get('registration_open', True)
            status = 'открыта' if REGISTRATION_OPEN else 'закрыта'
            logger.info(f"✅ Состояние бота загружено. Запись: {status}")
    except FileNotFoundError:
        REGISTRATION_OPEN = True
        logger.info("📭 Файл состояния не найден, устанавливаем по умолчанию")
        # Сохраняем состояние по умолчанию
        save_bot_state()
    except Exception as e:
        REGISTRATION_OPEN = True
        error_msg = (
            f"❌ Ошибка загрузки состояния: {e}, "
            f"устанавливаем по умолчанию"
        )
        logger.error(error_msg)
        save_bot_state()


def save_bot_state():
    """Сохраняет состояние бота"""
    try:
        # Создаем директорию, если не существует
        directory = os.path.dirname(STATE_FILE)
        os.makedirs(directory, exist_ok=True)

        state = {
            'registration_open': REGISTRATION_OPEN,
            'last_updated': datetime.datetime.now().isoformat()
        }

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        status = 'открыта' if REGISTRATION_OPEN else 'закрыта'
        logger.info(f"💾 Состояние бота сохранено. Запись: {status}")

        # Проверяем, что файл действительно создался
        if os.path.exists(STATE_FILE):
            file_size = os.path.getsize(STATE_FILE)
            success_msg = (
                f"✅ Файл состояния создан успешно. "
                f"Размер: {file_size} байт"
            )
            logger.info(success_msg)
        else:
            logger.error("❌ Файл состояния не создан!")

    except Exception as e:
        logger.error(f"❌ Ошибка сохранения состояния: {e}")
        logger.error(f"❌ Тип ошибки: {type(e).__name__}")


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("🏃‍♂️‍➡️ Записаться"), KeyboardButton("🙅 Отписаться")],
        [KeyboardButton("👥 Записать друга"), KeyboardButton("🗑 Удалить друга")],
        [KeyboardButton("🫂 Список игроков")]
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


async def handle_friend_deletion(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Обработка нажатия inline-кнопки удаления друга"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("del_friend:"):
        return

    friend_id = data[len("del_friend:"):]
    user = query.from_user

    friend = next(
        (p for p in players
         if p.get('friend_id') == friend_id
         and p.get('added_by') == user.id),
        None
    )

    if not friend:
        await query.edit_message_text(
            "⚠️ Друг не найден или вы не можете его удалить."
        )
        return

    friend_name = friend['first_name']
    players[:] = [p for p in players if p.get('friend_id') != friend_id]
    save_players()

    await query.edit_message_text(
        f"✅ Друг {friend_name} удалён из списка."
    )
    await context.bot.send_message(
        chat_id=VOLLEYBALL_CHAT_ID,
        text=(
            f"⚠️ Игрок {user.first_name} {user.last_name or ''} "
            f"удалил друга {friend_name} из списка."
        )
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_organizer_response, waiting_payment_amount

    user = update.effective_user
    text = update.message.text

    # Обработка ответа от организатора
    if str(user.id) == ORGANIZER_CHAT_ID:
        # Ждем ответ о том, была ли игра
        if waiting_organizer_response:
            if text.lower() in ["да", "yes"]:
                waiting_organizer_response = False
                waiting_payment_amount = True
                await update.message.reply_text(
                    "Сколько должен заплатить каждый игрок? "
                    "(укажите сумму в рублях)"
                )
            elif text.lower() in ["нет", "no"]:
                waiting_organizer_response = False
                await update.message.reply_text(
                    "✅ Хорошо, игра не состоялась."
                )
            else:
                await update.message.reply_text(
                    "Пожалуйста, ответьте 'Да' или 'Нет'"
                )
            return

        # Ждем ответ о сумме оплаты
        if waiting_payment_amount:
            # Проверяем, что введено число
            amount_match = re.search(r'\d+', text)
            if amount_match:
                amount = amount_match.group()
                payment_text = (
                    f"🤜🤛 Всем спасибо за игру 🔥 Не забудьте перевести "
                    f"{amount} рублей на номер {PAYMENT_INFORMATION} 💰. "
                )
                await context.bot.send_message(
                    chat_id=VOLLEYBALL_CHAT_ID,
                    text=payment_text
                )
                waiting_payment_amount = False
                await update.message.reply_text(
                    f"✅ Сообщение об оплате {amount} рублей отправлено в чат!"
                )
            else:
                await update.message.reply_text(
                    "Пожалуйста, укажите сумму цифрами (например: 500)"
                )
            return

    if not user.first_name:
        await update.message.reply_text(
            "⚠️ У вас не указано имя в Telegram. "
            "Пожалуйста, укажите его в настройках."
        )
        return

    # Обработка ввода имени друга
    if user.id in pending_add_friend:
        pending_add_friend.discard(user.id)
        friend_name = text.strip()
        if not friend_name:
            await update.message.reply_text(
                "⚠️ Имя не может быть пустым.",
                reply_markup=main_keyboard
            )
            return
        if not REGISTRATION_OPEN:
            await update.message.reply_text(
                "⛔️ Запись уже закрыта.",
                reply_markup=main_keyboard
            )
            return
        if len(players) >= MAX_PLAYERS:
            await update.message.reply_text(
                "⛔️ Все места заняты! Максимум 12 человек.",
                reply_markup=main_keyboard
            )
            return
        import uuid
        friend_id = str(uuid.uuid4())
        players.append({
            'user_id': f"friend_{friend_id}",
            'friend_id': friend_id,
            'first_name': friend_name,
            'last_name': '',
            'username': '',
            'is_friend': True,
            'added_by': user.id
        })
        save_players()
        await update.message.reply_text(
            f"✅ Друг {friend_name} записан на волейбол в {GAME_DAY}!",
            reply_markup=main_keyboard
        )
        await context.bot.send_message(
            chat_id=VOLLEYBALL_CHAT_ID,
            text=(
                f"👥 Игрок {user.first_name} {user.last_name or ''} "
                f"записал друга {friend_name} на волейбол."
            )
        )
        return

    if text == "🏃‍♂️‍➡️ Записаться":
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

    elif text == "� Записать друга":
        if not REGISTRATION_OPEN:
            await update.message.reply_text("⛔️ Запись уже закрыта.")
            return
        if len(players) >= MAX_PLAYERS:
            await update.message.reply_text(
                "⛔️ Все места заняты! Максимум 12 человек."
            )
            return
        pending_add_friend.add(user.id)
        await update.message.reply_text(
            "Введите имя друга, которого хотите записать:"
        )

    elif text == "🗑 Удалить друга":
        my_friends = [
            p for p in players
            if p.get('is_friend') and p.get('added_by') == user.id
        ]
        if not my_friends:
            await update.message.reply_text(
                "У вас нет записанных друзей.",
                reply_markup=main_keyboard
            )
            return
        buttons = [
            [InlineKeyboardButton(
                f"❌ {p['first_name']}",
                callback_data=f"del_friend:{p['friend_id']}"
            )]
            for p in my_friends
        ]
        await update.message.reply_text(
            "Выберите друга, которого хотите удалить:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif text == "�🙅 Отписаться":
        if is_registered(user.id):
            players[:] = [p for p in players if p['user_id'] != user.id]
            save_players()
            await update.message.reply_text("Вы отписались от волейбола.")
            await context.bot.send_message(
                chat_id=VOLLEYBALL_CHAT_ID,
                text=(
                    f"⚠️ Игрок {user.first_name} "
                    f"{user.last_name or ''} отписался с игры"
                )
            )
        else:
            await update.message.reply_text("Вы не были записаны.")

    elif text == "🫂 Список игроков":
        if players:
            player_list = "\n".join(
                [
                    f"{i+1}. {p['first_name']} {p['last_name']} "
                    f"(@{p.get('username', '')})".strip()
                    for i, p in enumerate(players)
                ]
            )
            # Определяем статус в зависимости от условий
            if not REGISTRATION_OPEN:
                status_text = "🔒 Закрыта"
            elif len(players) >= MAX_PLAYERS:
                status_text = "🚫 Места заняты"
            else:
                status_text = "✅ Открыта"
            status_info = f"Запись: {status_text}\n"
            player_count = f"({len(players)}/{MAX_PLAYERS})"
            await update.message.reply_text(
                f"{status_info}🫂 Список игроков {player_count}:\n{player_list}"
            )
        else:
            # Если список пуст, показываем только статус открыта/закрыта
            if not REGISTRATION_OPEN:
                status_text = "🔒 Закрыта"
            else:
                status_text = "✅ Открыта"
            status_info = f"Запись: {status_text}\n"
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
                if user.id == 303452412:
                    action = 'приварился 👨‍🏭💥'
                else:
                    action = 'записался'
                await context.bot.send_message(
                    chat_id=VOLLEYBALL_CHAT_ID,
                    text=(
                        f"🏃‍♂️‍➡️ Игрок {user.first_name} "
                        f"{user.last_name or ''} "
                        f"{action} на волейбол."
                    )
                )
        else:
            await update.message.reply_text(
                "Сначала выберите '🏃‍♂️‍➡️ Записаться' с клавиатуры.",
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


async def reminder_job(app):
    global REGISTRATION_OPEN, waiting_organizer_response

    while True:
        now = datetime.datetime.now()
        logger.info(f"⏰ Проверка времени: {now}")

        # Воскресенье 18:00 - вопрос организатору
        if now.weekday() == 6 and now.hour == 15 and now.minute == 0:
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
            logger.info("❓ Задан вопрос организатору о проведении игры")
            await asyncio.sleep(60)

        # Воскресенье 22:00 - очистка списка и открытие записи
        if now.weekday() == 6 and now.hour == 19 and now.minute == 0:
            logger.info("🧹 Очищаем список игроков и открываем запись.")
            # Очищаем список
            players.clear()
            save_players()
            # Открываем запись
            if not REGISTRATION_OPEN:
                REGISTRATION_OPEN = True
                save_bot_state()
            # Отправляем сообщение в чат
            cleanup_text = (
                "Волейбол завершён. Список игроков очищен. "
                "Запись на следующее воскресенье открыта 🧦"
            )
            await app.bot.send_message(
                chat_id=VOLLEYBALL_CHAT_ID,
                text=cleanup_text
            )
            logger.info("✅ Список очищен и запись открыта")
            await asyncio.sleep(60)

        # Пятница 11:00 - закрытие записи
        if now.weekday() == 4 and now.hour == 8 and now.minute == 0:
            if REGISTRATION_OPEN:
                REGISTRATION_OPEN = False
                save_bot_state()
                logger.info("🔒 Закрыта запись.")
                close_text = (
                    f"🔒 Запись закрыта.\n"
                    f"Записалось игроков: {len(players)}/{MAX_PLAYERS}"
                )
                await app.bot.send_message(
                    chat_id=VOLLEYBALL_CHAT_ID,
                    text=close_text
                )
                logger.info("📢 Отправлено уведомление о закрытии записи в чат")
            await asyncio.sleep(60)

        await asyncio.sleep(30)


async def main():
    # Сначала загружаем данные, потом проверяем состояние
    load_players()
    load_bot_state()

    # Только для отладки - проверяем, что состояние загрузилось правильно
    logger.info("🔍 Проверяем загруженное состояние...")
    status = 'открыта' if REGISTRATION_OPEN else 'закрыта'
    logger.info(f"📝 Текущее состояние записи: {status}")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_handler(CallbackQueryHandler(handle_friend_deletion))
    app.create_task(reminder_job(app))

    logger.info("🤖 Бот запущен!")
    await app.run_polling()


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
