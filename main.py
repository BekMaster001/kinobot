import firebase_admin
from firebase_admin import credentials, db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import logging
import re
import asyncio
import json
import platform  # Qo'shildi
from telegram.error import InvalidToken, TelegramError

# Logging sozlamalari
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Firebase sozlamalari
def initialize_firebase():
    try:
        cred = credentials.Certificate('kodli-kino-yaratuvchi-firebase-adminsdk-fbsvc-2bb890271e.json')
        firebase_admin.initialize_app(cred, {
            'databaseURL': 'https://kodli-kino-yaratuvchi-default-rtdb.firebaseio.com/'
        })
        return db.reference('/')
    except Exception as e:
        logger.error(f"Firebase ulanishda xatolik: {str(e)}. Qayta urinish...")
        return None

ref = initialize_firebase()
if ref is None:
    raise Exception("Firebase ulanishi muvaffaqiyatsiz bo'ldi.")

# Bot tokeni va sozlamalar
TOKEN = "7776681400:AAEvpxmU8SyRrEHxwIt3B0anFAro4vsHO8M"
ADMIN_ID = 253046132
DEFAULT_MANDATORY_CHANNEL = "@kinolar001_rasmiy"
BOT_USERNAME = "Markaziykinochi_bot"
sub_bot_applications = {}

def get_menu_button(user_id: int, is_admin: bool = False, is_sub_bot: bool = False) -> InlineKeyboardMarkup:
    """Menyu tugmasini qaytarish"""
    if is_sub_bot:
        return InlineKeyboardMarkup([[InlineKeyboardButton("📽 O‘z kino bo‘tingizni bepul yarating", url=f"https://t.me/{BOT_USERNAME}")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("☰ Menyu", callback_data="show_menu")]])

def get_main_menu_buttons(user_id: int, is_admin: bool = False) -> InlineKeyboardMarkup:
    """Asosiy menyu tugmalarini qaytarish"""
    buttons = [
        [InlineKeyboardButton("📽 Kodli kino bot yaratish", callback_data="create_sub_bot")],
        [InlineKeyboardButton("🔄 Bot tokenini o'zgartirish", callback_data="change_sub_bot_token")],
        [InlineKeyboardButton("🎥 Kodli kino joylash", callback_data="add_movie")],
        [InlineKeyboardButton("✏️ Kinolarni tahrirlash", callback_data="edit_movies")],
        [InlineKeyboardButton("📊 Statistika", callback_data="stats")],
        [InlineKeyboardButton("📢 Majburiy kanallarni sozlash", callback_data="set_mandatory_channels")],
        [InlineKeyboardButton("📋 Majburiy kanallar ro'yxati", callback_data="list_mandatory_channels")],
        [InlineKeyboardButton("🗑 Majburiy kanalni o'chirish", callback_data="delete_mandatory_channel")],
        [InlineKeyboardButton("📤 Kinolar ro'yxatini eksport qilish", callback_data="export_movies")],
        [InlineKeyboardButton("📥 Kinolar ro'yxatini import qilish", callback_data="import_movies")],
        [InlineKeyboardButton("✉️ Barcha obunachilarga xabar", callback_data="broadcast")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🛠 Admin panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

async def check_mandatory_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int, bot_id: str = None) -> tuple[bool, list]:
    """Foydalanuvchi majburiy kanallarda a'zo ekanligini tekshirish va a'zo bo'lmagan kanallarni qaytarish"""
    try:
        not_subscribed_channels = []
        users = ref.child('users').get() or {}
        
        if bot_id:
            for uid, user in users.items():
                if user.get('sub_bot') and user['sub_bot'].get('bot_id') == bot_id:
                    mandatory_channels = user['sub_bot'].get('mandatory_channels', [{'channel': DEFAULT_MANDATORY_CHANNEL, 'type': 'public'}])
                    for channel_data in mandatory_channels:
                        channel = channel_data['channel']
                        try:
                            member = await context.bot.get_chat_member(channel, user_id)
                            if member.status not in ['member', 'administrator', 'creator']:
                                not_subscribed_channels.append(channel_data)
                        except Exception as e:
                            logger.error(f"Kanal a'zoligini tekshirishda xatolik (user {user_id}, channel {channel}): {str(e)}")
                            not_subscribed_channels.append(channel_data)
                    return (len(not_subscribed_channels) == 0, not_subscribed_channels)
        
        member = await context.bot.get_chat_member(DEFAULT_MANDATORY_CHANNEL, user_id)
        if member.status not in ['member', 'administrator', 'creator']:
            not_subscribed_channels.append({'channel': DEFAULT_MANDATORY_CHANNEL, 'type': 'public'})
        return (len(not_subscribed_channels) == 0, not_subscribed_channels)
    except Exception as e:
        logger.error(f"Kanal a'zoligini tekshirishda xatolik (user {user_id}): {str(e)}")
        return (False, [])

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, user_data: dict):
    """Asosiy menyuni ko‘rsatish funksiyasi"""
    is_admin = user_id == ADMIN_ID
    bot_token_message = ""
    if user_data and user_data.get('sub_bot'):
        bot_name = user_data['sub_bot']['name']
        bot_token_message = f"\n\n🔗 Sizning sub-botingiz: {bot_name}\nUshbu bot orqali obunachilar kino kodlarini kiritishi mumkin."
    
    await update.message.reply_text(
        f"Salom! Markaziy Kinochi botga xush kelibsiz. Botdan foydalanishdan avval @MARKAZIY_KINOCHI_QOIDALARI bilan tanishib chiqing.{bot_token_message}",
        reply_markup=get_main_menu_buttons(user_id, is_admin)
    )

async def start_sub_bot(token: str, bot_id: str):
    """Sub-botni ishga tushirish"""
    try:
        app = Application.builder().token(token).build()
        bot_info = await app.bot.get_me()
        logger.info(f"Sub-bot {bot_info.username} (Telegram ID: {bot_info.id}, Saqlangan ID: {bot_id}) muvaffaqiyatli tekshirildi.")
        if str(bot_info.id) != bot_id:
            logger.error(f"Bot ID nomuvofiqligi: Telegram ID {bot_info.id}, Saqlangan ID {bot_id}")
            return False
        
        app.add_handler(CommandHandler("start", sub_bot_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sub_bot_movie_request))
        app.add_handler(CallbackQueryHandler(button_callback))
        app.add_error_handler(error_handler)
        sub_bot_applications[bot_id] = app
        
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info(f"Sub-bot {bot_id} ({bot_info.username}) muvaffaqiyatli ishga tushirildi.")
        return True
    except InvalidToken:
        logger.error(f"Sub-bot tokeni noto‘g‘ri: {token}")
        return False
    except TelegramError as e:
        logger.error(f"Sub-botni ishga tushirishda Telegram xatoligi (ID: {bot_id}): {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Sub-botni ishga tushirishda umumiy xatolik (ID: {bot_id}): {str(e)}")
        return False

async def sub_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sub-botning /start buyrug‘i"""
    user_id = update.effective_user.id
    bot_id = str(context.bot.bot.id)
    logger.info(f"Sub-bot {bot_id} uchun /start buyrug‘i qabul qilindi (user: {user_id})")

    users = ref.child('users').get() or {}
    for uid, user in users.items():
        if user.get('sub_bot') and user['sub_bot'].get('bot_id') == bot_id:
            if user.get('is_blocked', False):
                await update.message.reply_text("Bu bot bloklangan. Iltimos, markaziy bot orqali admin bilan bog‘laning.", reply_markup=get_menu_button(user_id, is_sub_bot=True))
                logger.info(f"Bloklangan sub-bot {bot_id} ga kirish urinilishi (user: {user_id})")
                return

            is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id, bot_id)
            if not is_subscribed:
                buttons = []
                channel_list = []
                for channel_data in not_subscribed_channels:
                    channel = channel_data['channel']
                    if channel_data['type'] == 'public':
                        channel_list.append(channel)
                        buttons.append([InlineKeyboardButton(f"Kanalga a’zo bo‘lish: {channel}", url=f"https://t.me/{channel[1:]}")])
                if buttons:
                    buttons.append([InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")])
                    await update.message.reply_text(
                        f"Iltimos, avval quyidagi kanallarga a’zo bo‘ling:\n" + "\n".join(channel_list),
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                return
            
            await update.message.reply_text(
                f"🎬 Xush kelibsiz, {user['sub_bot']['name']} botiga! Iltimos, kerakli kino kodini yuboring (masalan, MOVIE123):",
                reply_markup=get_menu_button(user_id, is_sub_bot=True)
            )
            ref.child(f'users/{uid}/sub_bot/subscribers/{user_id}').set(True)
            logger.info(f"User {user_id} sub-bot {bot_id} ga muvaffaqiyatli ulandi.")
            return
    
    await update.message.reply_text("Bu bot faol emas yoki noto‘g‘ri sozlangan. Iltimos, markaziy bot orqali tekshiring.", reply_markup=get_menu_button(user_id, is_sub_bot=True))
    logger.error(f"Sub-bot {bot_id} topilmadi yoki noto‘g‘ri sozlangan (user: {user_id})")

async def show_main_menu_for_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, user_data: dict):
    """Callback uchun asosiy menyuni ko‘rsatish"""
    is_admin = user_id == ADMIN_ID
    bot_token_message = ""
    if user_data and user_data.get('sub_bot'):
        bot_name = user_data['sub_bot']['name']
        bot_token_message = f"\n\n🔗 Sizning sub-botingiz: {bot_name}\nUshbu bot orqali obunachilar kino kodlarini kiritishi mumkin."
    
    await update.callback_query.message.reply_text(
        f"Salom! Markaziy Kinochi botga xush kelibsiz. Botdan foydalanishdan avval @MARKAZIY_KINOCHI_QOIDALARI bilan tanishib chiqing.{bot_token_message}",
        reply_markup=get_main_menu_buttons(user_id, is_admin)
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botni boshlash va asosiy menyuni ko‘rsatish"""
    user_id = update.effective_user.id

    is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id)
    if not is_subscribed:
        await update.message.reply_text(
            f"Iltimos, avval {DEFAULT_MANDATORY_CHANNEL} kanaliga a’zo bo‘ling!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Kanalga a’zo bo‘lish", url=f"https://t.me/{DEFAULT_MANDATORY_CHANNEL[1:]}")],
                [InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")]
            ])
        )
        return

    user_ref = ref.child(f'users/{user_id}')
    user_data = user_ref.get()
    await show_main_menu(update, context, user_id, user_data)

async def export_movies(user_id: int, user_data: dict) -> dict:
    """Foydalanuvchi kinolarini JSON formatida eksport qilish"""
    movies = user_data.get('sub_bot', {}).get('movies', {})
    export_data = {
        'user_id': user_id,
        'movies': movies
    }
    return export_data

async def import_movies(user_id: int, user_ref, movies_data: dict):
    """Kinolar ro'yxatini import qilish"""
    try:
        user_ref.child('sub_bot/movies').set(movies_data)
        return True
    except Exception as e:
        logger.error(f"Kinolar ro'yxatini import qilishda xatolik (user: {user_id}): {str(e)}")
        return False

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tugma bosilganda ishlaydigan funksiya"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "show_menu":
        user_ref = ref.child(f'users/{user_id}')
        user_data = user_ref.get()
        await show_main_menu_for_callback(update, context, user_id, user_data)
        return

    if data == "check_subscription":
        bot_id = str(context.bot.bot.id)
        if bot_id in sub_bot_applications:
            is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id, bot_id)
            users = ref.child('users').get() or {}
            for uid, user in users.items():
                if user.get('sub_bot') and user['sub_bot'].get('bot_id') == bot_id:
                    if not is_subscribed:
                        if any(c['type'] == 'public' for c in not_subscribed_channels):
                            buttons = []
                            channel_list = [c['channel'] for c in not_subscribed_channels if c['type'] == 'public']
                            for channel in channel_list:
                                buttons.append([InlineKeyboardButton(f"Kanalga a’zo bo‘lish: {channel}", url=f"https://t.me/{channel[1:]}")])
                            buttons.append([InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")])
                            await query.message.reply_text(
                                f"Siz hali quyidagi kanallarga a’zo bo‘lmagansiz:\n" + "\n".join(channel_list),
                                reply_markup=InlineKeyboardMarkup(buttons)
                            )
                        return
                    await query.message.reply_text(
                        f"🎬 Xush kelibsiz, {user['sub_bot']['name']} botiga! Iltimos, kerakli kino kodini yuboring (masalan, MOVIE123):",
                        reply_markup=get_menu_button(user_id, is_sub_bot=True)
                    )
                    ref.child(f'users/{uid}/sub_bot/subscribers/{user_id}').set(True)
                    logger.info(f"User {user_id} sub-bot {bot_id} ga muvaffaqiyatli ulandi.")
                    return
        else:
            is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id)
            if not is_subscribed:
                await query.message.reply_text(
                    f"Siz hali {DEFAULT_MANDATORY_CHANNEL} kanaliga a’zo bo‘lmagansiz! Iltimos, a’zo bo‘lib, qayta urinib ko‘ring.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Kanalga a’zo bo‘lish", url=f"https://t.me/{DEFAULT_MANDATORY_CHANNEL[1:]}")],
                        [InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")]
                    ])
                )
                return

            user_ref = ref.child(f'users/{user_id}')
            user_data = user_ref.get()
            await show_main_menu_for_callback(update, context, user_id, user_data)
            return

    is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id)
    if not is_subscribed:
        await query.message.reply_text(
            f"Iltimos, avval {DEFAULT_MANDATORY_CHANNEL} kanaliga a’zo bo‘ling!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Kanalga a’zo bo‘lish", url=f"https://t.me/{DEFAULT_MANDATORY_CHANNEL[1:]}")],
                [InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")]
            ])
        )
        return

    user_ref = ref.child(f'users/{user_id}')
    user_data = user_ref.get()

    if data == "create_sub_bot":
        if user_data and user_data.get('sub_bot') and not user_data.get('allow_additional_sub_bot', False):
            await query.message.reply_text("Siz allaqachon sub-bot yaratgansiz! Qo‘shimcha bot yaratish uchun admin bilan bog‘laning.", reply_markup=get_menu_button(user_id))
            return
        context.user_data['state'] = 'CREATE_SUB_BOT_TOKEN'
        await query.message.reply_text("Sub-bot uchun Telegram bot tokenini kiriting (masalan, 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11):", reply_markup=get_menu_button(user_id))
    elif data == "change_sub_bot_token":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        context.user_data['state'] = 'CHANGE_SUB_BOT_TOKEN'
        await query.message.reply_text("Yangi Telegram bot tokenini kiriting (masalan, 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11):", reply_markup=get_menu_button(user_id))
    elif data == "add_movie":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        context.user_data['state'] = 'ADD_MOVIE_CODE'
        await query.message.reply_text("Kino uchun noyob kod kiriting (masalan, 66):", reply_markup=get_menu_button(user_id))
    elif data == "edit_movies":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        movies = user_data.get('sub_bot', {}).get('movies', {})
        if not movies:
            await query.message.reply_text("Hozircha kinolar yo‘q.", reply_markup=get_menu_button(user_id))
            return
        buttons = [[InlineKeyboardButton(f"{code}", callback_data=f"edit_movie_{code}")] for code in movies]
        await query.message.reply_text("Tahrirlamoqchi bo‘lgan kino kodini tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "stats":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        subscribers = len(user_data.get('sub_bot', {}).get('subscribers', {}))
        movies = len(user_data.get('sub_bot', {}).get('movies', {}))
        await query.message.reply_text(f"📊 Statistikangiz:\nObunachilar: {subscribers}\nKontentlar: {movies}", reply_markup=get_menu_button(user_id))
    elif data == "set_mandatory_channels":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        context.user_data['state'] = 'SET_MANDATORY_CHANNEL_TYPE'
        await query.message.reply_text("Kanal turini tanlang (faqat ochiq/public):", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Ochiq (public)", callback_data="set_channel_public")]
        ]))
    elif data == "list_mandatory_channels":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        mandatory_channels = user_data.get('sub_bot', {}).get('mandatory_channels', [])
        if not mandatory_channels:
            await query.message.reply_text("Hozircha majburiy kanallar yo‘q.", reply_markup=get_menu_button(user_id))
            return
        text = "📋 Majburiy kanallar ro‘yxati:\n" + "\n".join([f"{c['channel']} ({c['type']})" for c in mandatory_channels])
        await query.message.reply_text(text, reply_markup=get_menu_button(user_id))
    elif data == "delete_mandatory_channel":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        mandatory_channels = user_data.get('sub_bot', {}).get('mandatory_channels', [])
        if not mandatory_channels:
            await query.message.reply_text("Hozircha majburiy kanallar yo‘q.", reply_markup=get_menu_button(user_id))
            return
        buttons = [[InlineKeyboardButton(c['channel'], callback_data=f"delete_channel_{c['channel']}")] for c in mandatory_channels]
        await query.message.reply_text("O‘chirmoqchi bo‘lgan majburiy kanalni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith("delete_channel_"):
        channel = data[len("delete_channel_"):]
        mandatory_channels = user_data.get('sub_bot', {}).get('mandatory_channels', [])
        if any(c['channel'] == channel for c in mandatory_channels):
            user_ref.child('sub_bot/mandatory_channels').set([c for c in mandatory_channels if c['channel'] != channel])
            await query.message.reply_text(f"Kanal {channel} majburiy kanallar ro‘yxatidan o‘chirildi!", reply_markup=get_menu_button(user_id))
        else:
            await query.message.reply_text(f"Kanal {channel} topilmadi.", reply_markup=get_menu_button(user_id))
    elif data == "set_channel_public":
        context.user_data['state'] = 'SET_MANDATORY_CHANNEL_PUBLIC'
        await query.message.reply_text("Ochiq kanal ID’sini kiriting (masalan, @MyChannel):", reply_markup=get_menu_button(user_id))
    elif data == "broadcast":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        context.user_data['state'] = 'BROADCAST_MESSAGE'
        await query.message.reply_text("Barcha obunachilarga yuboriladigan xabarni kiriting:", reply_markup=get_menu_button(user_id))
    elif data == "export_movies":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        movies = user_data.get('sub_bot', {}).get('movies', {})
        if not movies:
            await query.message.reply_text("Hozircha kinolar yo‘q.", reply_markup=get_menu_button(user_id))
            return
        export_data = await export_movies(user_id, user_data)
        export_json = json.dumps(export_data, indent=2, ensure_ascii=False)
        with open(f'movies_{user_id}.json', 'w', encoding='utf-8') as f:
            f.write(export_json)
        await context.bot.send_document(
            chat_id=user_id,
            document=open(f'movies_{user_id}.json', 'rb'),
            caption="Sizning kinolar ro'yxatingiz eksport qilindi!",
            reply_markup=get_menu_button(user_id)
        )
    elif data == "import_movies":
        if not user_data or not user_data.get('sub_bot'):
            await query.message.reply_text("Avval sub-bot yarating!", reply_markup=get_menu_button(user_id))
            return
        context.user_data['state'] = 'IMPORT_MOVIES'
        await query.message.reply_text("Kinolar ro'yxatini import qilish uchun JSON faylini yuboring:", reply_markup=get_menu_button(user_id))
    elif data == "admin_panel" and user_id == ADMIN_ID:
        buttons = [
            [InlineKeyboardButton("📋 Sub-botlar ro‘yxati", callback_data="list_sub_bots")],
            [InlineKeyboardButton("🚫 Sub-botni bloklash", callback_data="block_sub_bot")],
            [InlineKeyboardButton("📊 Umumiy statistika", callback_data="global_stats")],
            [InlineKeyboardButton("✉️ Barchaga xabar yuborish", callback_data="admin_broadcast")],
            [InlineKeyboardButton("➕ Qo‘shimcha sub-bot ruxsati", callback_data="allow_additional_sub_bot")]
        ]
        await query.message.reply_text("🛠 Admin panel:", reply_markup=InlineKeyboardMarkup(buttons))
    elif data == "list_sub_bots" and user_id == ADMIN_ID:
        users = ref.child('users').get()
        if not users:
            await query.message.reply_text("Hozircha sub-botlar yo‘q.", reply_markup=get_menu_button(user_id))
            return
        text = "📋 Sub-botlar ro‘yxati:\n"
        for uid, user in users.items():
            if user.get('sub_bot'):
                status = "Bloklangan" if user.get('is_blocked', False) else "Faol"
                text += f"ID: {uid}, Bot: {user['sub_bot']['name']}, Token: {user['sub_bot']['token']}, Status: {status}, Admin: {user.get('username', 'Noma’lum')}\n"
        await query.message.reply_text(text, reply_markup=get_menu_button(user_id))
    elif data == "block_sub_bot" and user_id == ADMIN_ID:
        context.user_data['state'] = 'BLOCK_SUB_BOT'
        await query.message.reply_text("Bloklamoqchi bo‘lgan foydalanuvchi ID’sini kiriting:", reply_markup=get_menu_button(user_id))
    elif data == "global_stats" and user_id == ADMIN_ID:
        stats = ref.child('global_stats').get() or {'total_sub_bots': 0, 'total_subscribers': 0}
        await query.message.reply_text(
            f"📊 Umumiy statistika:\nJami sub-botlar: {stats.get('total_sub_bots', 0)}\nJami obunachilar: {stats.get('total_subscribers', 0)}",
            reply_markup=get_menu_button(user_id)
        )
    elif data == "admin_broadcast" and user_id == ADMIN_ID:
        context.user_data['state'] = 'ADMIN_BROADCAST'
        await query.message.reply_text("Barcha sub-bot obunachilariga yuboriladigan xabarni kiriting:", reply_markup=get_menu_button(user_id))
    elif data == "allow_additional_sub_bot" and user_id == ADMIN_ID:
        context.user_data['state'] = 'ADD_ADDITIONAL_SUB_BOT'
        await query.message.reply_text("Qo‘shimcha sub-bot yaratishga ruxsat beriladigan foydalanuvchi ID’sini kiriting:", reply_markup=get_menu_button(user_id))
    elif data == "save_content":
        if not context.user_data.get('content'):
            await query.message.reply_text("Hozircha hech qanday kontent yuborilmadi!", reply_markup=get_menu_button(user_id))
            return
        movie_code = context.user_data.get('movie_code')
        content = context.user_data.get('content')
        user_ref.child(f'sub_bot/movies/{movie_code}').set({
            'content_type': content['type'],
            'channel_id': content['channel_id'],
            'message_id': content['message_id'],
            'caption': content.get('caption', 'Tavsif yo‘q')
        })
        context.user_data['state'] = None
        context.user_data['content'] = None
        await query.message.reply_text("Kontent muvaffaqiyatli saqlandi!", reply_markup=get_menu_button(user_id))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi xabarlarini qayta ishlash"""
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get('state')

    is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id)
    if not is_subscribed:
        await update.message.reply_text(
            f"Iltimos, avval {DEFAULT_MANDATORY_CHANNEL} kanaliga a’zo bo‘ling!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Kanalga a’zo bo‘lish", url=f"https://t.me/{DEFAULT_MANDATORY_CHANNEL[1:]}")],
                [InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")]
            ])
        )
        return

    user_ref = ref.child(f'users/{user_id}')
    user_data = user_ref.get()

    if state == 'CREATE_SUB_BOT_TOKEN':
        if not re.match(r'^\d+:[A-Za-z0-9_-]+$', text):
            await update.message.reply_text("Iltimos, to‘g‘ri Telegram bot tokenini kiriting (masalan, 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11):", reply_markup=get_menu_button(user_id))
            return
        try:
            bot_app = Application.builder().token(text).build()
            bot_info = await bot_app.bot.get_me()
            bot_name = f"@{bot_info.username}"
            bot_id = str(bot_info.id)
            logger.info(f"Token muvaffaqiyatli tekshirildi: {bot_name} (Telegram ID: {bot_id})")
        except InvalidToken:
            await update.message.reply_text("Kiritilgan token noto‘g‘ri. Iltimos, BotFather orqali to‘g‘ri token kiriting.", reply_markup=get_menu_button(user_id))
            return
        except TelegramError as e:
            await update.message.reply_text(f"Tokenni tekshirishda xatolik: {str(e)}. Iltimos, qayta urining.", reply_markup=get_menu_button(user_id))
            return
        except Exception as e:
            await update.message.reply_text(f"Ichki xatolik yuz berdi: {str(e)}. Iltimos, qayta urining.", reply_markup=get_menu_button(user_id))
            return

        user_ref.update({
            'username': update.effective_user.username or 'Noma’lum',
            'sub_bot': {
                'bot_id': bot_id,
                'name': bot_name,
                'token': text,
                'channel_id': '',
                'movies': {},
                'subscribers': {},
                'mandatory_channels': [{'channel': DEFAULT_MANDATORY_CHANNEL, 'type': 'public'}]
            }
        })
        global_stats = ref.child('global_stats')
        current_bots = global_stats.child('total_sub_bots').get() or 0
        global_stats.update({'total_sub_bots': current_bots + 1})
        context.user_data['state'] = None
        await update.message.reply_text(f"Sub-bot muvaffaqiyatli yaratildi: {bot_name}!", reply_markup=get_menu_button(user_id))
        success = await start_sub_bot(text, bot_id)
        if not success:
            await update.message.reply_text("Sub-botni ishga tushirishda xatolik yuz berdi. Iltimos, tokenni qayta tekshiring.", reply_markup=get_menu_button(user_id))
            user_ref.child('sub_bot').delete()
    elif state == 'CHANGE_SUB_BOT_TOKEN':
        if not re.match(r'^\d+:[A-Za-z0-9_-]+$', text):
            await update.message.reply_text("Iltimos, to‘g‘ri Telegram bot tokenini kiriting (masalan, 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11):", reply_markup=get_menu_button(user_id))
            return
        try:
            bot_app = Application.builder().token(text).build()
            bot_info = await bot_app.bot.get_me()
            new_bot_name = f"@{bot_info.username}"
            new_bot_id = str(bot_info.id)
            logger.info(f"Yangi token muvaffaqiyatli tekshirildi: {new_bot_name} (Telegram ID: {new_bot_id})")
        except InvalidToken:
            await update.message.reply_text("Kiritilgan token noto‘g‘ri. Iltimos, BotFather orqali to‘g‘ri token kiriting.", reply_markup=get_menu_button(user_id))
            return
        except TelegramError as e:
            await update.message.reply_text(f"Tokenni tekshirishda xatolik: {str(e)}. Iltimos, qayta urining.", reply_markup=get_menu_button(user_id))
            return
        except Exception as e:
            await update.message.reply_text(f"Ichki xatolik yuz berdi: {str(e)}. Iltimos, qayta urining.", reply_markup=get_menu_button(user_id))
            return

        old_bot_id = user_data['sub_bot']['bot_id']
        if old_bot_id in sub_bot_applications:
            await sub_bot_applications[old_bot_id].stop()
            del sub_bot_applications[old_bot_id]
            logger.info(f"Eski sub-bot {old_bot_id} to‘xtatildi.")

        user_ref.child('sub_bot').update({
            'bot_id': new_bot_id,
            'name': new_bot_name,
            'token': text
        })
        context.user_data['state'] = None
        await update.message.reply_text(f"Sub-bot tokeni muvaffaqiyatli o'zgartirildi: {new_bot_name}!", reply_markup=get_menu_button(user_id))
        success = await start_sub_bot(text, new_bot_id)
        if not success:
            await update.message.reply_text("Sub-botni ishga tushirishda xatolik yuz berdi. Iltimos, tokenni qayta tekshiring.", reply_markup=get_menu_button(user_id))
    elif state == 'SET_MANDATORY_CHANNEL_PUBLIC':
        if not text.startswith('@'):
            await update.message.reply_text("Iltimos, kanal ID’sini @ bilan boshlang (masalan, @MyChannel):", reply_markup=get_menu_button(user_id))
            return
        mandatory_channels = user_data.get('sub_bot', {}).get('mandatory_channels', [{'channel': DEFAULT_MANDATORY_CHANNEL, 'type': 'public'}])
        if len(mandatory_channels) >= 7:
            await update.message.reply_text("Maksimal 7 ta majburiy kanal qo‘shish mumkin!", reply_markup=get_menu_button(user_id))
            return
        if any(c['channel'] == text for c in mandatory_channels):
            await update.message.reply_text("Bu kanal allaqachon qo‘shilgan!", reply_markup=get_menu_button(user_id))
            return
        mandatory_channels.append({'channel': text, 'type': 'public'})
        user_ref.child('sub_bot/mandatory_channels').set(mandatory_channels)
        context.user_data['state'] = None
        await update.message.reply_text("Majburiy kanal muvaffaqiyatli qo‘shildi!", reply_markup=get_menu_button(user_id))
    elif state == 'ADD_MOVIE_CODE':
        context.user_data['movie_code'] = text
        context.user_data['state'] = 'ADD_MOVIE_POST'
        context.user_data['content'] = None
        await update.message.reply_text("Kino yuboring (yopiq kanaldagi post havolasini yuboring, masalan, https://t.me/c/2379057584/20):", reply_markup=get_menu_button(user_id))
    elif state == 'ADD_MOVIE_POST':
        post_link_pattern = r'https://t\.me/c/(\d+)/(\d+)'
        match = re.match(post_link_pattern, text)
        if not match:
            await update.message.reply_text("Iltimos, to‘g‘ri post havolasini yuboring (masalan, https://t.me/c/2379057584/20)!", reply_markup=get_menu_button(user_id))
            return

        channel_id = f"-100{match.group(1)}"
        message_id = int(match.group(2))

        try:
            forwarded_message = await context.bot.forward_message(
                chat_id=user_id,
                from_chat_id=channel_id,
                message_id=message_id
            )
        except Exception as e:
            logger.error(f"Postni forward qilishda xatolik: {str(e)}")
            await update.message.reply_text("Postni olishda xatolik yuz berdi. Bot kanalda admin bo‘lishi kerak yoki havola noto‘g‘ri!", reply_markup=get_menu_button(user_id))
            return

        context.user_data['content'] = {
            'type': 'post',
            'channel_id': channel_id,
            'message_id': message_id,
            'caption': forwarded_message.caption or "Tavsif yo‘q"
        }
        context.user_data['state'] = 'CONFIRM_MOVIE_CODE'
        await update.message.reply_text(f"Kino kodi ({context.user_data['movie_code']}) to‘g‘ri ekanligini tasdiqlang yoki yangi kod kiriting:", reply_markup=get_menu_button(user_id))
    elif state == 'CONFIRM_MOVIE_CODE':
        if text != context.user_data['movie_code']:
            context.user_data['movie_code'] = text
        context.user_data['state'] = 'ADD_MOVIE_CONFIRM'
        await update.message.reply_text(
            f"Kontent qabul qilindi! Kod: {context.user_data['movie_code']}. Saqlash uchun tugmani bosing:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Saqlash", callback_data="save_content")]
            ])
        )
    elif state == 'BROADCAST_MESSAGE':
        subscribers = user_data.get('sub_bot', {}).get('subscribers', {})
        bot_id = user_data['sub_bot']['bot_id']
        if bot_id in sub_bot_applications:
            for subscriber_id in subscribers:
                try:
                    await sub_bot_applications[bot_id].bot.send_message(subscriber_id, text, reply_markup=get_menu_button(subscriber_id, is_sub_bot=True))
                except Exception as e:
                    logger.error(f"Xabar yuborishda xatolik (user {subscriber_id}): {str(e)}")
                    continue
        else:
            await update.message.reply_text("Sub-bot faol emas yoki ishga tushirilmagan. Iltimos, qayta tekshiring.", reply_markup=get_menu_button(user_id))
        context.user_data['state'] = None
        await update.message.reply_text("Xabar barcha obunachilarga yuborildi!", reply_markup=get_menu_button(user_id))
    elif state == 'BLOCK_SUB_BOT' and user_id == ADMIN_ID:
        target_user_ref = ref.child(f'users/{text}')
        target_user = target_user_ref.get()
        if target_user and target_user.get('sub_bot'):
            bot_id = target_user['sub_bot']['bot_id']
            if bot_id in sub_bot_applications:
                await sub_bot_applications[bot_id].stop()
                del sub_bot_applications[bot_id]
                logger.info(f"Sub-bot {bot_id} to‘xtatildi.")
            target_user_ref.update({'is_blocked': True})
            await update.message.reply_text(f"Foydalanuvchi {text} bloklandi va bot to‘xtatildi.", reply_markup=get_menu_button(user_id))
        else:
            await update.message.reply_text("Bunday foydalanuvchi yoki bot topilmadi.", reply_markup=get_menu_button(user_id))
        context.user_data['state'] = None
    elif state == 'ADMIN_BROADCAST' and user_id == ADMIN_ID:
        users = ref.child('users').get()
        for uid, user in users.items():
            if user.get('sub_bot') and not user.get('is_blocked', False):
                bot_id = user['sub_bot']['bot_id']
                if bot_id in sub_bot_applications:
                    subscribers = user.get('sub_bot', {}).get('subscribers', {})
                    for subscriber_id in subscribers:
                        try:
                            await sub_bot_applications[bot_id].bot.send_message(subscriber_id, text, reply_markup=get_menu_button(subscriber_id, is_sub_bot=True))
                        except Exception as e:
                            logger.error(f"Admin xabar yuborishda xatolik (user {subscriber_id}): {str(e)}")
                            continue
        context.user_data['state'] = None
        await update.message.reply_text("Xabar barcha sub-bot obunachilariga yuborildi!", reply_markup=get_menu_button(user_id))
    elif state == 'ADD_ADDITIONAL_SUB_BOT' and user_id == ADMIN_ID:
        target_user_ref = ref.child(f'users/{text}')
        if target_user_ref.get():
            target_user_ref.update({'allow_additional_sub_bot': True})
            await update.message.reply_text(f"Foydalanuvchi {text} ga qo‘shimcha sub-bot yaratishga ruxsat berildi.", reply_markup=get_menu_button(user_id))
        else:
            await update.message.reply_text("Bunday foydalanuvchi topilmadi.", reply_markup=get_menu_button(user_id))
        context.user_data['state'] = None
    elif state == 'IMPORT_MOVIES':
        if not update.message.document or not update.message.document.file_name.endswith('.json'):
            await update.message.reply_text("Iltimos, faqat JSON faylini yuboring!", reply_markup=get_menu_button(user_id))
            return
        file = await update.message.document.get_file()
        file_data = await file.download_as_bytearray()
        try:
            movies_data = json.loads(file_data.decode('utf-8'))
            if movies_data.get('user_id') != user_id:
                await update.message.reply_text("Bu fayl sizning foydalanuvchi ID'ingizga mos kelmaydi!", reply_markup=get_menu_button(user_id))
                return
            success = await import_movies(user_id, user_ref, movies_data.get('movies', {}))
            if success:
                await update.message.reply_text("Kinolar ro'yxati muvaffaqiyatli import qilindi!", reply_markup=get_menu_button(user_id))
            else:
                await update.message.reply_text("Kinolar ro'yxatini import qilishda xatolik yuz berdi!", reply_markup=get_menu_button(user_id))
        except json.JSONDecodeError:
            await update.message.reply_text("Yuborilgan fayl noto‘g‘ri JSON formatida!", reply_markup=get_menu_button(user_id))
        except Exception as e:
            await update.message.reply_text(f"Xatolik yuz berdi: {str(e)}", reply_markup=get_menu_button(user_id))
        context.user_data['state'] = None

async def sub_bot_movie_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sub-botda kino kodi yuborilganda javob berish"""
    user_id = update.effective_user.id
    code = update.message.text.strip()
    bot_id = str(context.bot.bot.id)
    logger.info(f"Sub-bot {bot_id} uchun kino kodi qabul qilindi: {code} (user: {user_id})")

    is_subscribed, not_subscribed_channels = await check_mandatory_subscription(context, user_id, bot_id)
    if not is_subscribed:
        users = ref.child('users').get() or {}
        for uid, user in users.items():
            if user.get('sub_bot') and user['sub_bot'].get('bot_id') == bot_id:
                buttons = []
                channel_list = [c['channel'] for c in not_subscribed_channels if c['type'] == 'public']
                for channel in channel_list:
                    buttons.append([InlineKeyboardButton(f"Kanalga a’zo bo‘lish: {channel}", url=f"https://t.me/{channel[1:]}")])
                if buttons:
                    buttons.append([InlineKeyboardButton("✅ A’zo bo‘ldim", callback_data="check_subscription")])
                    await update.message.reply_text(
                        f"Iltimos, avval quyidagi kanallarga a’zo bo‘ling:\n" + "\n".join(channel_list),
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                return

    users = ref.child('users').get() or {}
    for uid, user in users.items():
        if user.get('sub_bot') and user['sub_bot'].get('bot_id') == bot_id:
            if user.get('is_blocked', False):
                await update.message.reply_text("Bu bot bloklangan. Iltimos, markaziy bot orqali admin bilan bog‘laning.", reply_markup=get_menu_button(user_id, is_sub_bot=True))
                return
            if code in user['sub_bot'].get('movies', {}):
                content = user['sub_bot']['movies'][code]
                if content['content_type'] == 'post':
                    try:
                        await context.bot.forward_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=content['channel_id'],
                            message_id=content['message_id']
                        )
                        ref.child(f'users/{uid}/sub_bot/subscribers/{user_id}').set(True)
                        global_stats = ref.child('global_stats')
                        current_subscribers = global_stats.child('total_subscribers').get() or 0
                        global_stats.update({'total_subscribers': current_subscribers + 1})
                        logger.info(f"Post muvaffaqiyatli yuborildi (kod: {code}, user: {user_id})")
                        await update.message.reply_text(
                            "Kino muvaffaqiyatli yuborildi!",
                            reply_markup=get_menu_button(user_id, is_sub_bot=True)
                        )
                        return
                    except Exception as e:
                        logger.error(f"Postni yuborishda xatolik (kod: {code}, user: {user_id}): {str(e)}")
                        await update.message.reply_text("Kontentni yuborishda xatolik yuz berdi. Iltimos, keyinroq urinib ko‘ring!", reply_markup=get_menu_button(user_id, is_sub_bot=True))
                        return
                else:
                    await update.message.reply_text("Bu kod bilan bog‘langan kontent post shaklida emas.", reply_markup=get_menu_button(user_id, is_sub_bot=True))
                    return
    await update.message.reply_text("Bunday kodli kontent topilmadi.", reply_markup=get_menu_button(user_id, is_sub_bot=True))
    logger.info(f"Kontent topilmadi (kod: {code}, user: {user_id})")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xatolarni qayta ishlash"""
    logger.error(f"Xatolik yuz berdi: {context.error}")
    if update and update.message:
        is_sub_bot = str(context.bot.bot.id) in sub_bot_applications
        await update.message.reply_text("Kechirasiz, ichki xatolik yuz berdi. Iltimos, keyinroq urinib ko‘ring!", reply_markup=get_menu_button(update.effective_user.id, is_sub_bot=is_sub_bot))

def main():
    """Botni ishga tushirish"""
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_message))
    application.add_error_handler(error_handler)

    users = ref.child('users').get() or {}
    for uid, user in users.items():
        if user.get('sub_bot') and not user.get('is_blocked', False):
            asyncio.create_task(start_sub_bot(user['sub_bot']['token'], user['sub_bot']['bot_id']))

    if platform.system() == "Emscripten":
        asyncio.ensure_future(application.run_polling(allowed_updates=Update.ALL_TYPES))
    else:
        if __name__ == "__main__":
            application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()