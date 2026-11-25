import os
import asyncio
import secrets
from telegram.error import TelegramError, RetryAfter
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, TypeHandler, ApplicationHandlerStop, ContextTypes, filters

TOKEN = os.getenv("TOKEN")
ADMIN_CHAT_ID = 6887439064
LEADS_GROUP_ID = -1003561971935

# Persistent user storage: never silently fall back to ephemeral Railway disk.
from pathlib import Path

volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
if os.getenv("RAILWAY_PROJECT_ID") and not volume_mount:
    raise RuntimeError("Attach a Railway Volume at /data before deploying this bot.")
DATA_DIR = Path(volume_mount) if volume_mount else Path(os.getenv("LOCAL_DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
if os.getenv("RAILWAY_PROJECT_ID") and not os.path.ismount(DATA_DIR):
    raise RuntimeError("Railway volume is not mounted; refusing to use temporary disk.")
USERS_FILE = str(DATA_DIR / "users.txt")
OPTOUT_FILE = str(DATA_DIR / "users_optout.txt")

TELEGRAM_URL = "https://t.me/tabibim_academy"
INSTAGRAM_URL = "https://www.instagram.com/tabibim_academy/"

# Главное меню
main_keyboard = [
    ["📚 Kurslar", "💰 Narxlar"],
    ["📍 Manzil", "📝 Ro'yxatdan o'tish"],
    ["📢 Telegram kanal", "📸 Instagram"]
]
main_reply_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)

# Меню курсов
courses_keyboard = [
    ["🩺 Hamshiralik", "💆‍♀️ Massaj"],
    ["🩸 Hijoma", "🦴 Vertebrologiya"],
    ["⬅️ Ortga"]
]
courses_reply_markup = ReplyKeyboardMarkup(courses_keyboard, resize_keyboard=True)

# Кнопки внутри карточки курса
course_action_keyboard = [
    ["📝 Ro'yxatdan o'tish"],
    ["⬅️ Ortga"]
]
course_action_reply_markup = ReplyKeyboardMarkup(course_action_keyboard, resize_keyboard=True)

# Кнопка отправки телефона
contact_button = KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)
contact_reply_markup = ReplyKeyboardMarkup(
    [[contact_button], ["⬅️ Ortga"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Состояния
waiting_for_name = set()
waiting_for_age = set()
waiting_for_contact = set()

selected_course = {}
user_name = {}

HAMSHIRALIK_TEXT = """🩺 Hamshiralik kursi

📚 Davomiyligi: 2 oy
📆 Darslar: haftasiga 3 marta, har biri 90 daqiqa

💸 Narxi:
• O‘zbek guruh — 950 000 so‘m / oyiga
• Rus guruh — 1 200 000 so‘m / oyiga

📖 O‘rganiladigan mavzular:
• Birinchi tibbiy yordam ko‘rsatish 🆘
• Bola parvarishi 👶
• Qon bosimini o‘lchash 🩺
• Inyeksiya qilish (7 xil ukol turi) 💉
• Anatomiya, nevrologiya, ginekologiya, pediatriya 🧠

📜 Yakunda diplom beriladi.
"""

MASSAJ_TEXT = """💆‍♀️ Massaj kursi

📚 Davomiyligi: 2 oy
📆 Darslar: haftasiga 3 marta, 90 daqiqa
💸 Narxi: 950 000 so‘m / oyiga
🎁 Bepul sinov darsi mavjud!

📖 O‘rganiladigan yo‘nalishlar:
• Kattalar va bolalar massaji
• Bo‘yin, bel, orqa, oyoq massaji
• Umumiy va tibbiy massaj texnikalari
• Mushak va asab tizimi bilan ishlash

📜 Yakunda diplom beriladi.
"""

HIJOMA_TEXT = """🩸 Hijoma kursi

📚 Davomiyligi: 1 oy
📆 Darslar: haftasiga 3 marta, 120 daqiqa
💸 Narxi: 2 050 000 so‘m / oyiga

📖 Kurs mazmuni:
• Hijoma va qon olish usullari
• Sterillik va xavfsizlik qoidalari
• Amaliy mashg‘ulotlar (real sharoitda)

📜 Yakunda diplom beriladi.
"""

VERTEBROLOGIYA_TEXT = """🦴 Vertebrologiya

⏱ Davomiyligi: 50 daqiqa
💸 Narxi: 300 000 so‘m

📖 Yo‘nalish:
• Muolaja
"""

def reset_user_state(user_id: int):
    waiting_for_name.discard(user_id)
    waiting_for_age.discard(user_id)
    waiting_for_contact.discard(user_id)
    selected_course.pop(user_id, None)
    user_name.pop(user_id, None)

def write_ids(path, ids):
    # Single bot replica; atomic replacement prevents a partially written list.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(f"{uid}\n" for uid in sorted(ids))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_user(chat_id: int):
    if not 0 < chat_id < 2**52:
        return
    existing = read_ids(USERS_FILE)
    if chat_id not in existing:
        write_ids(USERS_FILE, existing | {chat_id})


def get_users_count() -> int:
    return len(read_ids(USERS_FILE))


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    # Count incoming private messages and button presses, not group members.
    if (chat is None or chat.type != "private" or user is None or user.is_bot
            or chat.id != user.id or not (update.message or update.callback_query)):
        return
    try:
        save_user(chat.id)
    except OSError as exc:
        print("Persistent user storage error:", type(exc).__name__, flush=True)
        if update.effective_message:
            await update.effective_message.reply_text("Vaqtinchalik texnik xatolik. Iltimos, keyinroq urinib ko‘ring.")
        raise ApplicationHandlerStop


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    reset_user_state(user_id)
    if is_admin(update):
        context.user_data.pop("broadcast", None)

    await update.message.reply_text(
        "Assalomu alaykum! Tabibim Medical Academy ga xush kelibsiz 🌿\n\n"
        "Kerakli bo'limni tanlang:\n\nYangiliklar xabarlarini o‘chirish: /stopads",
        reply_markup=main_reply_markup
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    users_count = get_users_count()

    await update.message.reply_text(
        f"📊 Statistika\n\n👥 Bot foydalanuvchilari: {users_count} ta\n📢 Reklama oluvchilar: {len(recipients())} ta"
    )

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    user = update.effective_user

    if user_id not in waiting_for_contact:
        await update.message.reply_text(
            "Iltimos, avval ro'yxatdan o'tish jarayonini boshlang.",
            reply_markup=main_reply_markup
        )
        return

    try:
        phone = update.message.contact.phone_number
        course = selected_course.get(user_id, "Ko'rsatilmagan")
        full_name = user_name.get(user_id, user.first_name)
        age = context.user_data.get("age", "Ko'rsatilmagan")
        username = f"@{user.username}" if user.username else "yo‘q"

        admin_message = (
            "📥 Yangi ariza!\n\n"
            f"👤 Ism familiya: {full_name}\n"
            f"🎂 Yoshi: {age}\n"
            f"🆔 Username: {username}\n"
            f"📚 Kurs: {course}\n"
            f"📞 Telefon: {phone}"
        )

        await context.bot.send_message(
            chat_id=LEADS_GROUP_ID,
            text=admin_message
        )

        await update.message.reply_text(
            "Rahmat! Arizangiz qabul qilindi ✅\n"
            "Administrator tez orada siz bilan bog'lanadi.",
            reply_markup=main_reply_markup
        )

    except Exception as e:
        print("HANDLE_CONTACT ERROR:", e)
        await update.message.reply_text(
            "Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.",
            reply_markup=main_reply_markup
        )

    context.user_data.pop("age", None)
    reset_user_state(user_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_chat.id

    if is_admin(update) and context.user_data.get("broadcast"):
        await broadcast_text(update, context)
        return

    if text == "⬅️ Ortga":
        if user_id in waiting_for_name:
            reset_user_state(user_id)
            await update.message.reply_text(
                "Asosiy menyu:",
                reply_markup=main_reply_markup
            )
            return

        elif user_id in waiting_for_age:
            waiting_for_age.discard(user_id)
            waiting_for_name.add(user_id)
            await update.message.reply_text(
                "Ism va familiyangizni qayta yozing:\n\nMasalan: Malika Muslimova",
                reply_markup=ReplyKeyboardMarkup([["⬅️ Ortga"]], resize_keyboard=True)
            )
            return

        elif user_id in waiting_for_contact:
            waiting_for_contact.discard(user_id)
            waiting_for_age.add(user_id)
            await update.message.reply_text(
                "Yoshingizni qayta yozing:\n\nMasalan: 21",
                reply_markup=ReplyKeyboardMarkup([["⬅️ Ortga"]], resize_keyboard=True)
            )
            return

        else:
            reset_user_state(user_id)
            await update.message.reply_text(
                "Asosiy menyu:",
                reply_markup=main_reply_markup
            )
            return

    if text == "📚 Kurslar":
        await update.message.reply_text(
            "Kerakli kursni tanlang:",
            reply_markup=courses_reply_markup
        )

    elif text == "🩺 Hamshiralik":
        selected_course[user_id] = "Hamshiralik"
        await update.message.reply_text(
            HAMSHIRALIK_TEXT,
            reply_markup=course_action_reply_markup
        )

    elif text == "💆‍♀️ Massaj":
        selected_course[user_id] = "Massaj"
        await update.message.reply_text(
            MASSAJ_TEXT,
            reply_markup=course_action_reply_markup
        )

    elif text == "🩸 Hijoma":
        selected_course[user_id] = "Hijoma"
        await update.message.reply_text(
            HIJOMA_TEXT,
            reply_markup=course_action_reply_markup
        )

    elif text == "🦴 Vertebrologiya":
        selected_course[user_id] = "Vertebrologiya"
        await update.message.reply_text(
            VERTEBROLOGIYA_TEXT,
            reply_markup=course_action_reply_markup
        )

    elif text == "📢 Telegram kanal":
        await update.message.reply_text(
            "📢 Rasmiy Telegram kanalimizga obuna bo‘ling!\n\n"
            "Kurslarimiz, yangiliklar va e’lonlar bilan tanishing.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Telegram kanalga o‘tish ↗", url=TELEGRAM_URL)]
            ])
        )

    elif text == "📸 Instagram":
        await update.message.reply_text(
            "📸 Instagram sahifamizga xush kelibsiz!\n\n"
            "Dars jarayonlari, bitiruvchilarimiz va yangiliklarni kuzatib boring.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Instagram sahifasiga o‘tish ↗", url=INSTAGRAM_URL)]
            ])
        )

    elif text == "📝 Ro'yxatdan o'tish":
        if user_id not in selected_course:
            await update.message.reply_text(
                "Avval kursni tanlang.",
                reply_markup=courses_reply_markup
            )
            return

        waiting_for_name.add(user_id)

        await update.message.reply_text(
            "Ism va familiyangizni yozing:\n\nMasalan: Malika Muslimova",
            reply_markup=ReplyKeyboardMarkup([["⬅️ Ortga"]], resize_keyboard=True)
        )

    elif user_id in waiting_for_name:
        cleaned_name = text.strip()

        if len(cleaned_name) < 5 or " " not in cleaned_name:
            await update.message.reply_text(
                "Iltimos, ism va familiyangizni to‘liq yozing.\n\nMasalan: Malika Muslimova"
            )
            return

        user_name[user_id] = cleaned_name
        waiting_for_name.discard(user_id)
        waiting_for_age.add(user_id)

        await update.message.reply_text(
            "Yoshingizni yozing:\n\nMasalan: 21",
            reply_markup=ReplyKeyboardMarkup([["⬅️ Ortga"]], resize_keyboard=True)
        )

    elif user_id in waiting_for_age:
        if not text.isdigit():
            await update.message.reply_text(
                "Iltimos, yoshni faqat raqam bilan yozing.\n\nMasalan: 21"
            )
            return

        age = int(text)

        if age < 10 or age > 80:
            await update.message.reply_text(
                "Iltimos, yoshingizni to‘g‘ri kiriting.\n\nMasalan: 21"
            )
            return

        context.user_data["age"] = age
        waiting_for_age.discard(user_id)
        waiting_for_contact.add(user_id)

        await update.message.reply_text(
            "Telefon raqamingizni yuboring:",
            reply_markup=contact_reply_markup
        )

    elif text == "💰 Narxlar":
        await update.message.reply_text(
            "Narxlar kursga qarab farq qiladi.\n\n"
            "Batafsil ma'lumot olish uchun 📚 Kurslar bo'limidan kerakli kursni tanlang.",
            reply_markup=main_reply_markup
        )

    elif text == "📍 Manzil":
        await update.message.reply_text(
            "📍 Manzilimiz:\n"
            "Toshkent shahar, Shayxontohur tumani\n"
            "Ipakchilik kesishmasi, Qo‘rg‘oncha 62\n\n"
            "📌 Mo‘ljal: Gulzor (дока хлеб)",
            reply_markup=main_reply_markup
        )

        await update.message.reply_location(
            latitude=41.328819,
            longitude=69.1966517
        )

    else:
        await update.message.reply_text(
            "Menyudan kerakli bo'limni tanlang.",
            reply_markup=main_reply_markup
        )

# Рассылка (только личный чат администратора)
def is_admin(update: Update) -> bool:
    return (update.effective_chat is not None and update.effective_chat.type == "private"
            and update.effective_user is not None and update.effective_user.id == ADMIN_CHAT_ID
            and update.effective_chat.id == ADMIN_CHAT_ID)


def read_ids(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {int(line.strip()) for line in f if line.strip().isascii()
                    and line.strip().isdigit() and 0 < int(line.strip()) < 2**52}
    except FileNotFoundError:
        return set()


def recipients():
    return sorted(read_ids(USERS_FILE) - read_ids(OPTOUT_FILE))


async def stopads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    uid = update.effective_chat.id
    ids = read_ids(OPTOUT_FILE)
    if uid not in ids:
        write_ids(OPTOUT_FILE, ids | {uid})
    await update.message.reply_text("Reklama xabarlari o‘chirildi. Qayta yoqish: /startads")


async def startads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    uid = update.effective_chat.id
    ids = read_ids(OPTOUT_FILE) - {uid}
    write_ids(OPTOUT_FILE, ids)
    save_user(uid)
    await update.message.reply_text("Reklama xabarlari yoqildi. Bekor qilish: /stopads")


async def sendall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return
    if context.bot_data.get("broadcast_running"):
        await update.message.reply_text("Рассылка уже выполняется.")
        return
    context.user_data["broadcast"] = {"stage": "photo", "nonce": secrets.token_hex(8)}
    await update.message.reply_text(
        f"📢 Создание рассылки\nПолучателей сейчас: {len(recipients())}\n\n"
        "Отправьте одну фотографию (как фото, не как файл). Затем отправьте текст отдельным сообщением.\n"
        "Для отмены: /cancelbroadcast")


async def cancelbroadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if context.bot_data.get("broadcast_running"):
        await update.message.reply_text("Рассылка уже началась. Отправленные сообщения отменить нельзя.")
        return
    context.user_data.pop("broadcast", None)
    await update.message.reply_text("❌ Черновик рассылки отменён.")


async def broadcast_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    draft = context.user_data.get("broadcast")
    if not draft:
        return
    if draft["stage"] != "photo":
        await update.message.reply_text("Фото уже выбрано. Чтобы начать заново: /sendall")
        return
    if update.message.media_group_id:
        await update.message.reply_text("Отправьте одну фотографию, не альбом.")
        return
    draft["photo"] = update.message.photo[-1].file_id
    draft["stage"] = "text"
    await update.message.reply_text("✅ Фотография получена! Теперь отправьте текст отдельным сообщением.")


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


async def send_with_retry(method, **kwargs):
    # Retry only explicit flood limits, not ambiguous network failures.
    for attempt in range(4):
        try:
            return await method(**kwargs)
        except RetryAfter as exc:
            if attempt == 3:
                raise
            delay = exc.retry_after
            if hasattr(delay, "total_seconds"):
                delay = delay.total_seconds()
            await asyncio.sleep(float(delay) + 1)


ANNOUNCEMENT_COURSES = {
    "ham": ("Hamshiralik", HAMSHIRALIK_TEXT),
    "mas": ("Massaj", MASSAJ_TEXT),
    "hij": ("Hijoma", HIJOMA_TEXT),
    "ver": ("Vertebrologiya", VERTEBROLOGIYA_TEXT),
}


def announcement_markup(course):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Ro‘yxatdan o‘tish", callback_data=f"ad:join:{course}")],
        [InlineKeyboardButton("📚 Kurs haqida batafsil" if course != "all" else "📚 Kurslar",
                              callback_data=f"ad:info:{course}")],
        [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="ad:home:all")],
    ])


async def announcement_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    if chat is None or chat.type != "private" or update.effective_user is None or chat.id != update.effective_user.id:
        await query.answer("Faqat shaxsiy chatda.", show_alert=True)
        return
    if is_admin(update) and context.user_data.get("broadcast"):
        await query.answer("Сначала завершите или отмените черновик рассылки.", show_alert=True)
        return
    _, action, course = query.data.split(":")
    if action != "home" and course != "all" and course not in ANNOUNCEMENT_COURSES:
        await query.answer("Kurs topilmadi.", show_alert=True)
        return
    await query.answer()
    uid = chat.id
    # Navigation intentionally starts a fresh registration instead of mixing two courses.
    reset_user_state(uid)
    context.user_data.pop("age", None)
    if action == "home":
        await context.bot.send_message(uid, "Asosiy menyu:", reply_markup=main_reply_markup)
    elif course == "all":
        await context.bot.send_message(uid, "Kerakli kursni tanlang:", reply_markup=courses_reply_markup)
    else:
        name, description = ANNOUNCEMENT_COURSES[course]
        selected_course[uid] = name
        if action == "join":
            waiting_for_name.add(uid)
            await context.bot.send_message(uid, f"📚 Kurs: {name}\n\nIsm va familiyangizni yozing:\n\nMasalan: Malika Muslimova",
                                           reply_markup=ReplyKeyboardMarkup([["⬅️ Ortga"]], resize_keyboard=True))
        else:
            await context.bot.send_message(uid, description, reply_markup=course_action_reply_markup)


async def send_announcement(bot, chat_id, draft):
    text = draft["text"]
    entities = draft["entities"]
    markup = announcement_markup(draft["course"])
    if utf16_length(text) <= 1024:
        await send_with_retry(bot.send_photo, chat_id=chat_id, photo=draft["photo"],
                              caption=text, caption_entities=entities, reply_markup=markup)
    else:
        await send_with_retry(bot.send_photo, chat_id=chat_id, photo=draft["photo"])
        await asyncio.sleep(1.1)
        await send_with_retry(bot.send_message, chat_id=chat_id, text=text, entities=entities, reply_markup=markup)


async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data["broadcast"]
    if draft["stage"] == "photo":
        await update.message.reply_text("Сначала отправьте фотографию. Отмена: /cancelbroadcast")
        return
    if draft["stage"] == "course":
        await update.message.reply_text("Выберите курс кнопками в предыдущем сообщении. Отмена: /cancelbroadcast")
        return
    if draft["stage"] == "confirm":
        await update.message.reply_text("Подтвердите или отмените рассылку кнопками под просмотром.")
        return
    text = update.message.text
    if not text.strip() or utf16_length(text) > 4096:
        await update.message.reply_text("Введите непустой текст до 4096 символов (эмодзи могут занимать два).")
        return
    draft["text"] = text
    draft["entities"] = tuple(update.message.entities or ())
    draft["stage"] = "course"
    nonce = draft["nonce"]
    await update.message.reply_text("К какому курсу относится объявление?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🩺 Hamshiralik", callback_data=f"bcourse:ham:{nonce}"),
         InlineKeyboardButton("💆‍♀️ Massaj", callback_data=f"bcourse:mas:{nonce}")],
        [InlineKeyboardButton("🩸 Hijoma", callback_data=f"bcourse:hij:{nonce}"),
         InlineKeyboardButton("🦴 Vertebrologiya", callback_data=f"bcourse:ver:{nonce}")],
        [InlineKeyboardButton("📢 Общее объявление", callback_data=f"bcourse:all:{nonce}")],
    ]))


async def broadcast_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update):
        await query.answer("Доступ запрещён", show_alert=True)
        return
    draft = context.user_data.get("broadcast")
    _, course, nonce = query.data.split(":")
    if not draft or draft["stage"] != "course" or draft["nonce"] != nonce:
        await query.answer("Этот черновик уже закрыт.", show_alert=True)
        return
    if course != "all" and course not in ANNOUNCEMENT_COURSES:
        await query.answer("Курс не найден.", show_alert=True)
        return
    draft["course"] = course
    await query.answer()
    # Preview is delivered using exactly the same method as the real announcement.
    await context.bot.send_message(ADMIN_CHAT_ID, "📋 Предварительный просмотр:")
    try:
        await send_announcement(context.bot, ADMIN_CHAT_ID, draft)
    except TelegramError as exc:
        print("Broadcast preview error:", type(exc).__name__)
        await context.bot.send_message(ADMIN_CHAT_ID, "Не удалось показать объявление. Выберите курс повторно или начните заново: /sendall.")
        return
    ids = recipients()
    draft["recipients"] = ids
    draft["stage"] = "confirm"
    nonce = draft["nonce"]
    await context.bot.send_message(ADMIN_CHAT_ID,
        f"Отправить объявление {len(ids)} получателям?\nДо подтверждения рассылка не начнётся.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Отправить", callback_data=f"bc:yes:{nonce}"),
             InlineKeyboardButton("❌ Отменить", callback_data=f"bc:no:{nonce}")],
            [InlineKeyboardButton("🧪 Только тест (мне)", callback_data=f"bc:test:{nonce}")]
        ]))


async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update):
        await query.answer("Доступ запрещён", show_alert=True)
        return
    draft = context.user_data.get("broadcast")
    _, action, nonce = query.data.split(":")
    if not draft or draft["stage"] != "confirm" or draft["nonce"] != nonce:
        await query.answer("Этот черновик уже закрыт.", show_alert=True)
        return
    if context.bot_data.get("broadcast_running"):
        await query.answer("Рассылка уже выполняется.", show_alert=True)
        return
    if action == "test":
        await query.answer("Тест только администратору")
        try:
            await send_announcement(context.bot, ADMIN_CHAT_ID, draft)
        except TelegramError:
            await context.bot.send_message(ADMIN_CHAT_ID, "Ошибка тестовой отправки.")
        return
    if action == "no":
        context.user_data.pop("broadcast", None)
        await query.answer()
        await query.edit_message_text("❌ Рассылка отменена.")
        return
    if not draft["recipients"]:
        await query.answer("База получателей пуста.", show_alert=True)
        return
    # Consume confirmation before any network await: a double click cannot start twice.
    context.user_data.pop("broadcast", None)
    context.bot_data["broadcast_running"] = True
    context.application.create_task(run_broadcast(context.bot, context.bot_data, draft), update=update)
    await query.answer("Рассылка запущена")
    await query.edit_message_text(f"🚀 Рассылка запущена: {len(draft['recipients'])} получателей.")


async def run_broadcast(bot, bot_data, draft):
    success = failed = skipped = 0
    try:
        for uid in draft["recipients"]:
            if uid in read_ids(OPTOUT_FILE):
                skipped += 1
                continue
            try:
                await send_announcement(bot, uid, draft)
                success += 1
            except TelegramError as exc:
                failed += 1
                print("Broadcast delivery error:", type(exc).__name__)
            await asyncio.sleep(0.15)
    finally:
        bot_data["broadcast_running"] = False
        remaining = len(draft["recipients"]) - success - failed - skipped
        await bot.send_message(ADMIN_CHAT_ID,
            f"📊 Отчёт о рассылке\n\n✅ Отправлено полностью: {success}\n"
            f"⚠️ Ошибка / возможна частичная доставка: {failed}\n"
            f"🔕 Отписались: {skipped}\n⏳ Не обработано: {remaining}\n"
            f"Всего в подтверждённом списке: {len(draft['recipients'])}")


async def usersbackup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not os.path.isfile(USERS_FILE):
        await update.message.reply_text("Файл пользователей пока отсутствует.")
        return
    with open(USERS_FILE, "rb") as f:
        await update.message.reply_document(document=f, filename="users.txt")
    if os.path.isfile(OPTOUT_FILE):
        with open(OPTOUT_FILE, "rb") as f:
            await update.message.reply_document(document=f, filename="users_optout.txt")


async def restoreusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    original = update.message.reply_to_message
    doc = original.document if original else None
    if not doc or doc.file_name not in {"users.txt", "users_optout.txt"} or (doc.file_size or 0) > 5_000_000:
        await update.message.reply_text("Ответьте командой /restoreusers на файл users.txt или users_optout.txt (до 5 МБ).")
        return
    try:
        file = await doc.get_file()
        data = (await file.download_as_bytearray()).decode("utf-8-sig")
        lines = [line.strip() for line in data.splitlines() if line.strip()]
        if any(not line.isascii() or not line.isdigit() or not 0 < int(line) < 2**52 for line in lines):
            raise ValueError("Invalid user ID")
        path = OPTOUT_FILE if doc.file_name == "users_optout.txt" else USERS_FILE
        existing = read_ids(path)
        merged = existing | {int(line) for line in lines}
        write_ids(path, merged)
        await update.message.reply_text(f"✅ Добавлено: {len(merged - existing)}. Всего в файле: {len(merged)}.")
    except (ValueError, TelegramError, OSError):
        await update.message.reply_text("Не удалось импортировать файл. Исходный список не заменён, если запись не завершилась.")


for path in (USERS_FILE, OPTOUT_FILE):
    if not os.path.exists(path):
        write_ids(path, set())
    else:
        with open(path, "a", encoding="utf-8"):
            pass

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(TypeHandler(Update, track_user), group=-1)
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("sendall", sendall))
app.add_handler(CommandHandler("cancelbroadcast", cancelbroadcast))
app.add_handler(CommandHandler("usersbackup", usersbackup))
app.add_handler(CommandHandler("restoreusers", restoreusers))
app.add_handler(CommandHandler("stopads", stopads))
app.add_handler(CommandHandler("startads", startads))
app.add_handler(CallbackQueryHandler(broadcast_confirm, pattern=r"^bc:(yes|no|test):[0-9a-f]{16}$"))
app.add_handler(CallbackQueryHandler(broadcast_course, pattern=r"^bcourse:(ham|mas|hij|ver|all):[0-9a-f]{16}$"))
app.add_handler(CallbackQueryHandler(announcement_action, pattern=r"^ad:(join|info|home):(ham|mas|hij|ver|all)$"))
app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, broadcast_photo))
app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot ishlayapti...")
app.run_polling()
