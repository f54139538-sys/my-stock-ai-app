import streamlit as st
import yfinance as yf
import sqlite3
import pandas as pd
from google import genai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import time  # 🌟 新增時間套件，用來計算流量冷卻

# ==========================================
# 1. 網頁初始化與標題設定
# ==========================================
st.set_page_config(page_title="AI 股市分析與自動化系統", layout="wide")
st.title("📈 終極整合：AI 股市分析與郵件自動化系統")

# ==========================================
# 2. 側邊欄設定 (模型切換與流量提醒)
# ==========================================
with st.sidebar:
    st.header("⚙️ 設定面板")
    stock_id = st.text_input("請輸入股票代碼：", value="2330.TW")
    
    st.markdown("---")
    st.header("🧠 AI 模型選擇")
    
    # 建立模型選單字典 (顯示名稱 : 實際 API 呼叫代碼)
    model_options = {
        "Gemini 3.5 Flash (最新主力, 限5次/分)": "gemini-3.5-flash",
        "Gemini 3.1 Flash Lite (流速快, 限15次/分)": "gemini-3.1-flash-lite",
        "Gemini 2.5 Flash": "gemini-2.5-flash",
        "Gemini 2.0 Flash (經典款)": "gemini-2.0-flash"
    }
    # 建立下拉式選單
    selected_model_label = st.selectbox("請手動切換您想使用的 AI 模型：", list(model_options.keys()))
    selected_api_model = model_options[selected_model_label]
    
    st.markdown("---")
    st.warning("⚠️ **流量保護機制已啟動**\n\nGoogle 免費版 API 有嚴格的每分鐘呼叫限制 (RPM)。為保護您的帳號不被鎖定，系統已強制設定**每次分析需間隔 60 秒**。")

# ==========================================
# 3. 讀取金鑰與初始化記憶池 (Session State)
# ==========================================
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
MY_EMAIL = st.secrets["MY_EMAIL"]
MY_APP_PASSWORD = st.secrets["MY_APP_PASSWORD"]
TO_EMAIL = st.secrets["TO_EMAIL"]

client = genai.Client(api_key=GOOGLE_API_KEY)

# 初始化記憶池
if "ai_report" not in st.session_state:
    st.session_state.ai_report = None
if "current_stock" not in st.session_state:
    st.session_state.current_stock = ""
if "last_request_time" not in st.session_state:
    st.session_state.last_request_time = 0  # 記錄上次呼叫 API 的時間

# ==========================================
# 4. 核心邏輯：資料抓取、存庫、AI 分析
# ==========================================
if st.button("🚀 開始進行核心分析（抓取 -> 存庫 -> AI分析）"):
    
    # 🌟 流量防護鎖：檢查距離上次請求是否超過 60 秒
    current_time = time.time()
    time_elapsed = current_time - st.session_state.last_request_time
    
    if time_elapsed < 60:
        wait_time = int(60 - time_elapsed)
        st.error(f"🛑 流量保護觸發！請勿頻繁點擊。為保護您的 API 額度，請再等待 **{wait_time} 秒** 後重試。")
    else:
        # 通過流量檢查，記錄這次的時間
        st.session_state.last_request_time = current_time
        st.session_state.current_stock = stock_id
        
        # 關卡 A：網路爬蟲抓取資料
        with st.spinner("🔍 正在從 Yahoo Finance 抓取最新股價..."):
            stock = yf.Ticker(stock_id)
            hist_data = stock.history(period="1mo")
            
        if hist_data.empty:
            st.error("❌ 找不到該股票資料，請檢查代碼是否正確。")
        else:
            # 關卡 B：存入與讀取 SQLite 資料庫
            with st.spinner("📂 正在將資料寫入並讀取本地 SQLite 資料庫..."):
                conn = sqlite3.connect("stock_data.db")
                hist_data.to_sql("daily_price", conn, if_exists="replace")
                df_from_db = pd.read_sql("SELECT * FROM daily_price", conn)
                conn.close()
            
            st.subheader(f"📊 {stock_id} 最近一個月歷史收盤價走勢")
            st.line_chart(df_from_db.set_index('Date')['Close'])
            
            # 關卡 C：呼叫選定的 Gemini AI 進行分析
            with st.spinner(f"🧠 正在呼叫 {selected_model_label} 進行趨勢分析..."):
                data_text = df_from_db.to_string()
                prompt = f"""
                你是一位專業的股市分析師。
                請根據以下 {stock_id} 最近一個月的歷史股價資料，
                用簡單易懂的繁體中文，幫我分析近期的股價趨勢，並列出 3 個觀察重點與未來建議。
                
                股票資料如下：
                {data_text}
                """
                
                try:
                    # 使用使用者在側邊欄選擇的模型
                    response = client.models.generate_content(
                        model=selected_api_model,
                        contents=prompt
                    )
                    # 存入記憶池
                    st.session_state.ai_report = response.text
                    st.success("✅ AI 分析完畢！")
                except Exception as e:
                    st.error(f"❌ 呼叫 {selected_api_model} 失敗。錯誤原因：{e}")

# ==========================================
# 5. 渲染 AI 分析報告與寄信功能
# ==========================================
if st.session_state.ai_report and st.session_state.current_stock == stock_id:
    st.markdown("---")
    st.subheader(f"🤖 AI 專業分析報告 ({selected_model_label})")
    st.write(st.session_state.ai_report)
    
    st.markdown("---")
    st.subheader("📧 自動化通知中心")
    
    if st.button("✉️ 立即寄送此份股市日報"):
        with st.spinner("📨 正在啟動郵件伺服器，發送郵件中..."):
            try:
                msg = MIMEMultipart()
                msg['From'] = MY_EMAIL
                msg['To'] = TO_EMAIL
                msg['Subject'] = Header(f"🤖 您的專屬 AI 股市日報：{stock_id}", 'utf-8')
                
                msg.attach(MIMEText(st.session_state.ai_report, 'plain', 'utf-8'))
                
                server = smtplib.SMTP('smtp.gmail.com', 587)
                server.starttls()
                server.login(MY_EMAIL, MY_APP_PASSWORD)
                server.send_message(msg)
                server.quit()
                
                st.success(f"🎉 郵件發送成功！請檢查您的信箱。")
            except Exception as e:
                st.error(f"❌ 郵件發送失敗。詳細錯誤：{e}")