import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TOKEN")
ADMIN_CHAT_ID = 6887439064
LEADS_GROUP_ID = -5154745000

USERS_FILE = "users.txt"

# Главное меню
main_keyboard = [
    ["📚 Kurslar", "💰 Narxlar"],
    ["📍 Manzil", "📝 Ro'yxatdan o'tish"]
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

def save_user(chat_id: int):
    existing_users = set()

    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as file:
            existing_users = {line.strip() for line in file if line.strip()}

    if str(chat_id) not in existing_users:
        with open(USERS_FILE, "a", encoding="utf-8") as file:
            file.write(f"{chat_id}\n")

def get_users_count() -> int:
    if not os.path.exists(USERS_FILE):
        return 0

    with open(USERS_FILE, "r", encoding="utf-8") as file:
        users = {line.strip() for line in file if line.strip()}
    return len(users)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    reset_user_state(user_id)
    save_user(user_id)

    await update.message.reply_text(
        "Assalomu alaykum! Tabibim Medical Academy ga xush kelibsiz 🌿\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_reply_markup
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Bu buyruq faqat admin uchun.")
        return

    users_count = get_users_count()

    await update.message.reply_text(
        f"📊 Statistika\n\n👥 Bot foydalanuvchilari: {users_count} ta"
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

    context.user_data.pop("age", None)
    reset_user_state(user_id)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_chat.id

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

    elif text == "📝 Ro'yxatdan o'tish":
        if user_id not in selected_course:
            await update.message.reply_text(
                "Avval kursni tanlang.",
                reply_markup=courses_reply_markup
            )
            return

        waiting_for_name.add(user_id)

        await update.message.reply_text(
            "Ism va familiyangizni yozing:\n\nMasalan: Vali Karimov",
            reply_markup=ReplyKeyboardMarkup([["⬅️ Ortga"]], resize_keyboard=True)
        )

    elif user_id in waiting_for_name:
        cleaned_name = text.strip()

        if len(cleaned_name) < 5 or " " not in cleaned_name:
            await update.message.reply_text(
                "Iltimos, ism va familiyangizni to‘liq yozing.\n\nMasalan: Vali Karimov"
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

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot ishlayapti...")
app.run_polling()
