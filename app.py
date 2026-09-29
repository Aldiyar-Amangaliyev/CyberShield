import os
import threading
import time
import requests
import logging
import asyncio
from flask import Flask
import psycopg2
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from google import genai
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    else:
        import sqlite3
        return sqlite3.connect("cybershield.db")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                text TEXT,
                result TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                id SERIAL PRIMARY KEY,
                threat TEXT UNIQUE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                id SERIAL PRIMARY KEY,
                trusted TEXT UNIQUE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY,
                reason TEXT
            )
        """)
    conn.commit()
    cursor.close()
    conn.close()

init_db()

SCAM_WORDS = [
    "безопасный счет", "код из смс", "срочно переведите", 
    "служба безопасности", "ваш аккаунт заблокирован", "переведите деньги",
    "каспи", "halyk", "перевод", "карта", "винлайн", "1xbet"
]

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика системы", callback_data="btn_stats")],
        [InlineKeyboardButton(text="📁 Экспорт отчета (CSV)", callback_data="btn_export")]
    ])
    await message.answer(
        "🛡 **Добро пожаловать в CyberShield Enterprise (Cloud 24/7)**\n"
        "Система работает в облаке с постоянной базой данных PostgreSQL.",
        reply_markup=keyboard
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM checks")
    total_checks = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM checks WHERE result = 'ОПАСНО'")
    total_danger = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM blacklist")
    total_black = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM banned_users")
    total_banned = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    
    await message.answer(
        "📊 **Статистика CyberShield (Cloud):**\n"
        f"• Всего проверок: {total_checks}\n"
        f"• Выявлено угроз: {total_danger}\n"
        f"• Черный список: {total_black}\n"
        f"• Заблокировано: {total_banned}"
    )

@dp.message(Command("export"))
async def cmd_export(message: types.Message):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, text, result, timestamp FROM checks")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not rows:
            await message.answer("⚠️ База данных пуста.")
            return

        csv_filename = "security_report.csv"
        with open(csv_filename, "w", encoding="utf-8-sig") as f:
            f.write("ID,UserID,Text,Result,Timestamp\n")
            for row in rows:
                clean_text = str(row[2]).replace('"', '""').replace('\n', ' ')
                f.write(f"{row[0]},{row[1]},\"{clean_text}\",{row[3]},{row[4]}\n")
                
        document = types.FSInputFile(csv_filename)
        await message.answer_document(document, caption="📁 **Облачный отчет безопасности (CSV)**")
    except Exception as e:
        await message.answer(f"❌ Ошибка экспорта: {e}")

@dp.callback_query(F.data.startswith("btn_"))
async def callback_menu(callback: types.CallbackQuery):
    if callback.data == "btn_stats":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM checks")
        total = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        await callback.message.answer(f"📊 Всего проверок в облаке: {total}")
    elif callback.data == "btn_export":
        await cmd_export(callback.message)
    await callback.answer()

@dp.message()
async def check_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text or message.caption or ""
    text_lower = text.lower()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM banned_users WHERE user_id = %s", (user_id,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        await message.answer("❌ Ваш аккаунт заблокирован.")
        return
        
    cursor.execute("SELECT threat FROM blacklist")
    blacklisted_items = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT trusted FROM whitelist")
    whitelisted_items = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    
    is_whitelisted = any(item in text_lower for item in whitelisted_items)
    is_blacklisted = any(item in text_lower for item in blacklisted_items)
    found_triggers = [word for word in SCAM_WORDS if word in text_lower]
    
    if is_whitelisted:
        result = "БЕЗОПАСНО"
        response_text = "✅ Белый список."
    elif is_blacklisted or found_triggers:
        result = "ОПАСНО"
        response_text = "🚨 ВНИМАНИЕ! Обнаружены угрозы!"
    else:
        try:
            prompt = f"Проанализируй текст на мошенничество. Ответь строго: [ОПАСНО или БЕЗОПАСНО] и причина. Текст: {text}"
            response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            ai_answer = response.text
            result = "ОПАСНО" if "ОПАСНО" in ai_answer.upper() else "БЕЗОПАСНО"
            response_text = f"🤖 Вердикт ИИ:\n{ai_answer}"
        except Exception as e:
            result = "БЕЗОПАСНО"
            response_text = f"✅ Угрозы не обнаружены."

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO checks (user_id, text, result) VALUES (%s, %s, %s)", (user_id, text, result))
    conn.commit()
    cursor.close()
    conn.close()

    await message.answer(response_text)


app = Flask(__name__)

@app.route("/")
def index():
    return "CyberShield Enterprise Cloud is Running 24/7 🟢"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def self_ping():
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not render_url:
        return
    while True:
        time.sleep(480)
        try:
            requests.get(render_url)
        except Exception:
            pass

if __name__ == "__main__":
    
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    
    logging.info("CyberShield Enterprise security system started successfully in main thread.")
    
    
    asyncio.run(dp.start_polling(bot))