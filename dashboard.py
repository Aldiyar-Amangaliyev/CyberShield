import streamlit as st
import sqlite3
import pandas as pd

st.set_page_config(page_title="CyberShield Analytics", page_icon="🛡️", layout="wide")

st.title("🛡️ CyberShield — Панель мониторинга киберугроз")
st.markdown("Аналитическая система мониторинга запросов граждан и выявления мошеннических схем.")

conn = sqlite3.connect("cybershield.db")
df = pd.read_sql("SELECT * FROM checks", conn)
conn.close()

if df.empty:
    st.warning("База данных пока пуста. Отправьте несколько сообщений боту в Telegram!")
else:
    total_checks = len(df)
    danger_checks = len(df[df["result"] == "ОПАСНО"])
    safe_checks = len(df[df["result"] == "БЕЗОПАСНО"])

    col1, col2, col3 = st.columns(3)
    col1.metric("Всего проверок", total_checks)
    col2.metric("Выявлено угроз", danger_checks, delta_color="inverse")
    col3.metric("Безопасные запросы", safe_checks)

    st.markdown("---")
    st.subheader("📋 Последние перехваченные запросы")
    
    st.dataframe(df, use_container_width=True)