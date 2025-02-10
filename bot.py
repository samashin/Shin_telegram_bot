import os
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from io import BytesIO
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# █████████████████████ تنظیمات █████████████████████
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_DRIVE_CREDS = "service-account.json"
DRIVE_FOLDERS = {
    'pending': 'FOLDER_ID_PENDING',
    'general': 'FOLDER_ID_GENERAL',
    'nsfw': 'FOLDER_ID_NSFW',
    'edits': 'FOLDER_ID_EDITS',
    'premium': 'FOLDER_ID_PREMIUM',
    'blocked': 'FOLDER_ID_BLOCKED',
    'music': 'FOLDER_ID_MUSIC'
}
ADMIN_ID = 123456789
MUSIC_COOLDOWN = 120  # 2 دقیقه
POINT_COSTS = {'image': 1, 'video': 2}

# █████████████████████ دیتابیس █████████████████████
conn = sqlite3.connect('bot_db.sqlite')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS Users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    score INTEGER DEFAULT 0,
    nsfw_allowed BOOLEAN DEFAULT 0,
    is_blocked BOOLEAN DEFAULT 0,
    last_music TIMESTAMP
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS Media (
    file_id TEXT PRIMARY KEY,
    file_type TEXT CHECK(file_type IN ('image', 'video')),
    category TEXT CHECK(category IN ('general', 'nsfw', 'edits', 'premium', 'music')),
    uploaded_by INTEGER,
    status TEXT CHECK(status IN ('pending', 'approved', 'rejected')),
    points_awarded INTEGER,
    FOREIGN KEY(uploaded_by) REFERENCES Users(user_id)
)
''')
conn.commit()

# █████████████████████ سیستم اصلی █████████████████████
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.is_blocked:
        return
    
    # تشخیص نوع فایل
    media_type = 'image' if update.message.photo else 'video'
    
    # آپلود به پوشه pending
    file = await context.bot.get_file(update.message.effective_attachment[-1].file_id)
    file_stream = BytesIO()
    await file.download_to_memory(out=file_stream)
    file_stream.seek(0)
    
    drive_service = build('drive', 'v3', credentials=creds)
    file_metadata = {
        'name': f'{media_type}_{user.id}',
        'parents': [DRIVE_FOLDERS['pending']]
    }
    drive_file = drive_service.files().create(
        body=file_metadata,
        media_body=MediaIoBaseUpload(file_stream, mimetype='application/octet-stream'),
        fields='id'
    ).execute()
    
    # ذخیره در دیتابیس
    cursor.execute('''
    INSERT INTO Media (file_id, file_type, category, uploaded_by, status)
    VALUES (?, ?, 'pending', ?, 'pending')
    ''', (drive_file['id'], media_type, user.id))
    conn.commit()
    
    # ارسال به ادمین برای بررسی
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید عادی", callback_data=f'approve_{drive_file['id']}_general_1'),
            InlineKeyboardButton("🔞 تایید NSFW", callback_data=f'approve_{drive_file['id']}_nsfw_2')
        ],
        [
            InlineKeyboardButton("🎬 تایید ادیت", callback_data=f'approve_{drive_file['id']}_edits_3'),
            InlineKeyboardButton("💎 تایید پریمیوم", callback_data=f'approve_{drive_file['id']}_premium_{1 if media_type == "image" else 2}')
        ],
        [InlineKeyboardButton("⛔ بلاک کاربر", callback_data=f'block_{user.id}')]
    ]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📥 محتوای جدید از @{user.username}\nنوع: {media_type}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# █████████████████████ سیستم پریمیوم █████████████████████
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        await update.message.reply_text("🔒 فقط در چت خصوصی!")
        return
    
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🖼 تصویر (1 امتیاز)", callback_data='premium_image')],
        [InlineKeyboardButton("🎥 ویدیو (2 امتیاز)", callback_data='premium_video')]
    ]
    
    await update.message.reply_text(
        f"💎 فروشگاه پریمیوم\n🏆 امتیاز شما: {get_score(user.id)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# █████████████████████ زمان‌بندی █████████████████████
from random import choice
from apscheduler.triggers.interval import IntervalTrigger

# لیست بازه‌های زمانی مجاز (هر 15 دقیقه بین 2 تا 4 ساعت)
TIME_OPTIONS = [7200 + (i * 900) for i in range(0, 13)]  # 7200 ثانیه = 2 ساعت, 14400 = 4 ساعت

def get_next_interval():
    """انتخاب تصادفی یکی از بازه‌های 15 دقیقه‌ای"""
    return choice(TIME_OPTIONS)

async def send_scheduled_content():
    # کد ارسال محتوا
    
    # زمانبندی مجدد با بازه جدید
    schedule_next_send()

def start_scheduler():
    """شروع زمانبندی با اولین بازه تصادفی"""
    interval = get_next_interval()
    scheduler.add_job(
        send_scheduled_content,
        trigger=IntervalTrigger(seconds=interval),
        id='content_job'
    )

# در قسمت اجرای اصلی:
if __name__ == '__main__':
    scheduler = AsyncIOScheduler()
    start_scheduler()
    scheduler.start()
# █████████████████████ راه‌اندازی █████████████████████
if __name__ == '__main__':
    creds = service_account.Credentials.from_service_account_file(GOOGLE_DRIVE_CREDS)
    drive_service = build('drive', 'v3', credentials=creds)
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CallbackQueryHandler(admin_handler))
    
    scheduler.start()
    app.run_polling()