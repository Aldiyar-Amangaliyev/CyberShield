import os
import threading
from flask import Flask, render_template_string
import asyncio
from bot import main as run_bot 

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>CyberShield Enterprise Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 50px; }
        .card { background: #1e293b; padding: 30px; border-radius: 12px; display: inline-block; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
        h1 { color: #38bdf8; }
        .status { color: #4ade80; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🛡 CyberShield Enterprise</h1>
        <p>Статус системы: <span class="status">🟢 Активна (24/7 Cloud)</span></p>
        <p>Защита ИИ, OCR, Anti-Flood и Audit Log функционируют в штатном режиме.</p>
    </div>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

def start_bot_background():
    asyncio.run(run_bot())

if __name__ == "__main__":
   
    bot_thread = threading.Thread(target=start_bot_background, daemon=True)
    bot_thread.start()
    
  
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)