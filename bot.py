import asyncio
import logging
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
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

def init_db():
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            result TEXT
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
    await message.answer(
        "Здравствуй! Я — система CyberShield с ИИ, OCR и модулем баз данных.\n"
        "Отправь мне текст, ссылку или скриншот/чек для анализа на мошенничество."
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
    conn.close()
    
    await message.answer(
        "📊 **Статистика системы CyberShield:**\n"
        f"• Всего проверок: {total_checks}\n"
        f"• Выявлено угроз: {total_danger}\n"
        f"• Объектов в черном списке: {total_black}\n"
        f"• Объектов в белом списке: {total_white}"
    )

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
        logging.info(f"Added to blacklist: {threat}")
        await message.answer(f"✅ Объект `{threat}` добавлен в ЧЕРНЫЙ список.")
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
        logging.info(f"Added to whitelist: {trusted}")
        await message.answer(f"✅ Объект `{trusted}` добавлен в БЕЛЫЙ список (доверенный).")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(lambda message: message.photo is not None)
async def check_photo(message: types.Message):
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
        else:
            result = "БЕЗОПАСНО"
            response_text = f"✅ ИИ-анализ изображения: Угрозы не выявлено.\n{ai_answer}"
            
    except Exception as e:
        result = "БЕЗОПАСНО"
        response_text = f"⚠️ Ошибка обработки: {str(e)}"

    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO checks (user_id, text, result) VALUES (?, ?, ?)", (message.from_user.id, "[Скриншот/Фото]", result))
    conn.commit()
    conn.close()
    logging.info(f"Photo check for user {message.from_user.id}: {result}")

    await message.answer(response_text)

@dp.message()
async def check_message(message: types.Message):
    text = message.text or message.caption or ""
    text_lower = text.lower()
    
    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    
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
    elif found_triggers or has_link:
        result = "ОПАСНО"
        response_text = (
            "🚨 ВНИМАНИЕ! Обнаружены признаки мошенничества!\n"
            f"• Триггеры: {', '.join(found_triggers) if found_triggers else 'нет'}\n"
            "Рекомендация: Ни в коем случае не передавайте данные и не переводите деньги."
        )
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
            else:
                result = "БЕЗОПАСНО"
                response_text = f"✅ ИИ-анализ: Угрозы не выявлено.\n{ai_answer}"
        except Exception as e:
            result = "БЕЗОПАСНО"
            response_text = "✅ Угрозы не обнаружены (базовый режим)."

    conn = sqlite3.connect("cybershield.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO checks (user_id, text, result) VALUES (?, ?, ?)", (message.from_user.id, text, result))
    conn.commit()
    conn.close()
    
    logging.info(f"Text check for user {message.from_user.id}: {result}")

    await message.answer(response_text)

async def main():
    logging.info("CyberShield bot started successfully.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())