import asyncio
import logging
import sqlite3
import os
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("GEMINI_API_KEY")

bot = Bot(token=TOKEN)
dp = Dispatcher()

ai_client = genai.Client(api_key=API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("audit.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

user_cooldowns = {}
COOLDOWN_TIME = 2.0

def init_db():
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            result TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            threat TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trusted TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            reason TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

SCAM_WORDS = [
    "безопасный счет", "код из смс", "срочно переведите", 
    "служба безопасности", "ваш аккаунт заблокирован", "переведите деньги",
    "каспи", "halyk", "перевод", "карта", "винлайн", "1xbet"
]

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    logging.info(f"User {message.from_user.id} started the bot.")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика системы", callback_data="btn_stats")],
        [InlineKeyboardButton(text="📋 Аудит безопасности", callback_data="btn_audit")],
        [InlineKeyboardButton(text="📁 Экспорт отчета (CSV)", callback_data="btn_export")]
    ])
    
    await message.answer(
        "🛡 **Добро пожаловать в CyberShield Enterprise**\n"
        "Интеллектуальная система защиты с ИИ-анализом, OCR, защитой от флуда и авто-модерацией.\n\n"
        "Выберите действие ниже или просто отправьте подозрительный текст/скриншот:",
        reply_markup=keyboard
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM checks")
    total_checks = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM checks WHERE result = 'ОПАСНО'")
    total_danger = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM blacklist")
    total_black = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM whitelist")
    total_white = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM banned_users")
    total_banned = cursor.fetchone()[0]
    conn.close()
    
    logging.info(f"Admin {message.from_user.id} requested system statistics.")
    await message.answer(
        "📊 **Расширенная статистика CyberShield:**\n"
        f"• Всего проверок: {total_checks}\n"
        f"• Выявлено угроз: {total_danger}\n"
        f"• Объектов в черном списке: {total_black}\n"
        f"• Объектов в белом списке: {total_white}\n"
        f"• Заблокировано нарушителей: {total_banned}"
    )

@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    try:
        conn = sqlite3.connect("cybershield.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, text, result, timestamp FROM checks")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await message.answer("⚠️ База данных проверок пуста, нечего выгружать.")
            return

        csv_filename = "security_report.csv"
        with open(csv_filename, "w", encoding="utf-8-sig") as f:
            f.write("ID,UserID,Text,Result,Timestamp\n")
            for row in rows:
                clean_text = str(row[2]).replace('"', '""').replace('\n', ' ')
                f.write(f"{row[0]},{row[1]},\"{clean_text}\",{row[3]},{row[4]}\n")
                
        document = types.FSInputFile(csv_filename)
        await message.answer_document(
            document, 
            caption="📁 **Официальный отчет системы безопасности (CSV)**"
        )
        logging.info(f"Admin {message.from_user.id} exported security report.")
    except Exception as e:
        await message.answer(f"❌ Ошибка экспорта: {e}")

@dp.message(Command("audit"))
async def cmd_audit(message: types.Message):
    try:
        if not os.path.exists("audit.log"):
            await message.answer("⚠️ Файл аудита пока пуст.")
            return
            
        with open("audit.log", "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        last_lines = "".join(lines[-10:]) if lines else "Логи пусты."
        logging.info(f"Admin {message.from_user.id} requested audit logs.")
        
        await message.answer(
            "📋 **Последние события безопасности (Audit Log):**\n"
            f"```text\n{last_lines}\n```"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения логов: {e}")

@dp.message(Command("add_black"))
async def add_to_blacklist(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажи объект. Пример: `/add_black scam-site.kz`")
        return
    
    threat = args[1].strip().lower()
    try:
        conn = sqlite3.connect("cybershield.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO blacklist (threat) VALUES (?)", (threat,))
        conn.commit()
        conn.close()
        logging.warning(f"SECURITY ALERT: Object added to blacklist by admin {message.from_user.id}: {threat}")
        await message.answer(f"✅ Объект `{threat}` добавлен в ЧЕРНЫЙ список.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("del_black"))
async def del_from_blacklist(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажи объект. Пример: `/del_black scam-site.kz`")
        return
    
    threat = args[1].strip().lower()
    try:
        conn = sqlite3.connect("cybershield.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM blacklist WHERE threat = ?", (threat,))
        conn.commit()
        conn.close()
        logging.info(f"Object removed from blacklist by admin {message.from_user.id}: {threat}")
        await message.answer(f"🗑 Объект `{threat}` удален из ЧЕРНОГО списка.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("add_white"))
async def add_to_whitelist(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажи ресурс. Пример: `/add_white kaspi.kz`")
        return
    
    trusted = args[1].strip().lower()
    try:
        conn = sqlite3.connect("cybershield.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO whitelist (trusted) VALUES (?)", (trusted,))
        conn.commit()
        conn.close()
        logging.info(f"Object added to whitelist by admin {message.from_user.id}: {trusted}")
        await message.answer(f"✅ Объект `{trusted}` добавлен в БЕЛЫЙ список (доверенный).")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("del_white"))
async def del_from_whitelist(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажи ресурс. Пример: `/del_white kaspi.kz`")
        return
    
    trusted = args[1].strip().lower()
    try:
        conn = sqlite3.connect("cybershield.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM whitelist WHERE trusted = ?", (trusted,))
        conn.commit()
        conn.close()
        logging.info(f"Object removed from whitelist by admin {message.from_user.id}: {trusted}")
        await message.answer(f"🗑 Объект `{trusted}` удален из БЕЛОГО списка.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data.startswith("btn_"))
async def callback_menu(callback: types.CallbackQuery):
    action = callback.data
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    
    if action == "btn_stats":
        cursor.execute("SELECT COUNT(*) FROM checks")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM checks WHERE result = 'ОПАСНО'")
        danger = cursor.fetchone()[0]
        conn.close()
        await callback.message.answer(f"📊 Статистика через меню:\n• Всего проверок: {total}\n• Угроз: {danger}")
    elif action == "btn_audit":
        conn.close()
        if os.path.exists("audit.log"):
            with open("audit.log", "r", encoding="utf-8") as f:
                lines = f.readlines()
            last_lines = "".join(lines[-5:]) if lines else "Пусто"
            await callback.message.answer(f"📋 Последние логи:\n```text\n{last_lines}\n```")
        else:
            await callback.message.answer("⚠️ Логи пока пусты.")
    elif action == "btn_export":
        conn.close()
        await cmd_export(callback.message)
    
    await callback.answer()

@dp.message(lambda message: message.photo is not None)
async def check_photo(message: types.Message):
    user_id = message.from_user.id
    
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
    if cursor.fetchone():
        conn.close()
        await message.answer("❌ Ваш аккаунт заблокирован в системе CyberShield за нарушение правил безопасности.")
        return
    conn.close()

    current_time = time.time()
    if user_id in user_cooldowns and current_time - user_cooldowns[user_id] < COOLDOWN_TIME:
        await message.answer("⏳ Слишком частые запросы. Пожалуйста, подождите пару секунд.")
        return
    user_cooldowns[user_id] = current_time

    await message.answer("🔍 Анализирую изображение с помощью ИИ...")
    
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        image_bytes = file_bytes.read()
        
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                genai_types.Part.from_bytes(
                    data=image_bytes,
                    mime_type='image/jpeg',
                ),
                "Проанализируй этот скриншот или чек на предмет мошенничества, подделки перевода или фишинга. Ответь строго в формате: [ОПАСНО или БЕЗОПАСНО] и короткая причина."
            ]
        )
        
        ai_answer = response.text
        
        if "ОПАСНО" in ai_answer.upper():
            result = "ОПАСНО"
            response_text = f"🚨 Вердикт ИИ по изображению:\n{ai_answer}"
            logging.warning(f"SECURITY INCIDENT: High-risk image detected for user {user_id}")
        else:
            result = "БЕЗОПАСНО"
            response_text = f"✅ ИИ-анализ изображения: Угрозы не выявлено.\n{ai_answer}"
            
    except Exception as e:
        result = "БЕЗОПАСНО"
        response_text = f"⚠️ Ошибка обработки: {str(e)}"

    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO checks (user_id, text, result) VALUES (?, ?, ?)", (user_id, "[Скриншот/Фото]", result))
    conn.commit()
    conn.close()
    
    await message.answer(response_text)

@dp.message()
async def check_message(message: types.Message):
    user_id = message.from_user.id
    
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
    if cursor.fetchone():
        conn.close()
        await message.answer("❌ Ваш аккаунт заблокирован в системе CyberShield за нарушение правил безопасности.")
        return
    
    current_time = time.time()
    if user_id in user_cooldowns and current_time - user_cooldowns[user_id] < COOLDOWN_TIME:
        await message.answer("⏳ Слишком частые запросы. Пожалуйста, подождите пару секунд.")
        conn.close()
        return
    user_cooldowns[user_id] = current_time

    text = message.text or message.caption or ""
    text_lower = text.lower()
    
    cursor.execute("SELECT threat FROM blacklist")
    blacklisted_items = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("SELECT trusted FROM whitelist")
    whitelisted_items = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    is_whitelisted = any(item in text_lower for item in whitelisted_items)
    is_blacklisted = any(item in text_lower for item in blacklisted_items)
    
    found_triggers = [word for word in SCAM_WORDS if word in text_lower]
    has_link = "http" in text_lower or "www." in text_lower or "t.me" in text_lower
    
    result = ""
    response_text = ""

    if is_whitelisted:
        result = "БЕЗОПАСНО"
        response_text = "✅ Этот ресурс находится в официальном БЕЛОМ СПИСКЕ (доверенный)."
    elif is_blacklisted:
        result = "ОПАСНО"
        response_text = "🚨 ВНИМАНИЕ! Этот объект находится в официальном ЧЕРНОМ СПИСКЕ угроз!"
        logging.warning(f"SECURITY INCIDENT: Blacklisted match found for user {user_id}")
    elif found_triggers or has_link:
        result = "ОПАСНО"
        response_text = (
            "🚨 ВНИМАНИЕ! Обнаружены признаки мошенничества!\n"
            f"• Триггеры: {', '.join(found_triggers) if found_triggers else 'нет'}\n"
            "Рекомендация: Ни в коем случае не передавайте данные и не переводите деньги."
        )
        logging.warning(f"SECURITY INCIDENT: Scam triggers/links detected for user {user_id}")
    else:
        try:
            prompt = f"Проанализируй текст на предмет интернет-мошенничества или фишинга. Ответь строго в формате: [ОПАСНО или БЕЗОПАСНО] и короткая причина. Текст: {text}"
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            ai_answer = response.text
            
            if "ОПАСНО" in ai_answer.upper():
                result = "ОПАСНО"
                response_text = f"🤖 Вердикт ИИ-аналитика:\n{ai_answer}"
                logging.warning(f"SECURITY INCIDENT: AI flagged message as dangerous from user {user_id}")
            else:
                result = "БЕЗОПАСНО"
                response_text = f"✅ ИИ-анализ: Угрозы не выявлено.\n{ai_answer}"
        except Exception as e:
            result = "БЕЗОПАСНО"
            response_text = f"✅ Угрозы не обнаружены (ошибка ИИ: {e})."

    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO checks (user_id, text, result) VALUES (?, ?, ?)", (user_id, text, result))
    conn.commit()
    conn.close()
    
    logging.info(f"Text check processed for user {user_id}: {result}")

    await message.answer(response_text)

async def main():
    logging.info("CyberShield Enterprise security system started successfully.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())