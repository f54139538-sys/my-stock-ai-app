import streamlit as st
import yfinance as yf
import sqlite3
import pandas as pd
from google import genai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# ==========================================
# 1. 網頁初始化與標題設定
# ==========================================
st.set_page_config(page_title="AI 股市分析與自動化系統", layout="wide")
st.title("📈 終極整合：AI 股市分析與郵件自動化系統")
st.write("本系統已整合：歷史資料爬蟲、SQLite資料庫儲存、Gemini AI趨勢分析、Gmail一鍵通知。")

# 建立左側邊欄，讓介面更乾淨漂亮
with st.sidebar:
    st.header("⚙️ 設定面板")
    stock_id = st.text_input("請輸入股票代碼：", value="2330.TW")
    st.info("提示：台股請加 .TW (如 2330.TW)，美股直接打代碼 (如 AAPL, NVDA)")

# ==========================================
# 2. 讀取 Streamlit 雲端保險箱的金鑰與信箱資訊
# ==========================================
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
MY_EMAIL = st.secrets["MY_EMAIL"]
MY_APP_PASSWORD = st.secrets["MY_APP_PASSWORD"]
TO_EMAIL = st.secrets["TO_EMAIL"]

# 初始化 Gemini AI 客戶端
client = genai.Client(api_key=GOOGLE_API_KEY)

# 🌟 初始化網頁記憶池 (Session State)
# 這樣可以防止網頁重新整理時，AI 報告消失或重複重複發送 API 請求
if "ai_report" not in st.session_state:
    st.session_state.ai_report = None
if "current_stock" not in st.session_state:
    st.session_state.current_stock = ""

# ==========================================
# 3. 核心邏輯：資料抓取、存庫、AI 分析
# ==========================================
if st.button("🚀 開始進行核心整併流程（抓取 -> 存庫 -> AI分析）"):
    st.session_state.current_stock = stock_id
    
    # 關卡 A：網路爬蟲抓取資料
    with st.spinner("🔍 第一步：正在從 Yahoo Finance 抓取最新股價..."):
        stock = yf.Ticker(stock_id)
        hist_data = stock.history(period="1mo")
        
    if hist_data.empty:
        st.error("❌ 找不到該股票資料，請檢查代碼是否正確。")
    else:
        st.success("✅ 關卡 A 成功：資料抓取完畢！")
        
        # 關卡 B：存入與讀取 SQLite 資料庫
        with st.spinner("📂 第二步：正在將資料寫入本地 SQLite 資料庫..."):
            conn = sqlite3.connect("stock_data.db")
            # 存入資料庫
            hist_data.to_sql("daily_price", conn, if_exists="replace")
            # 重新從資料庫讀出來（確保資料庫功能完全正常）
            df_from_db = pd.read_sql("SELECT * FROM daily_price", conn)
            conn.close()
        st.success("✅ 關卡 B 成功：本地資料庫寫入與驗證讀取成功！")
        
        # 畫出折線圖
        st.subheader(f"📊 {stock_id} 最近一個月歷史收盤價走勢")
        st.line_chart(df_from_db.set_index('Date')['Close'])
        
        # 關卡 C：將資料餵給 Gemini AI 進行專業分析
        with st.spinner("🧠 第三步：正在將資料庫數據打包，呼叫 Gemini AI 進行趨勢分析..."):
            data_text = df_from_db.to_string()
            prompt = f"""
            你是一位專業的股市分析師。
            請根據以下 {stock_id} 最近一個月的歷史股價資料，
            用簡單易懂的繁體中文，幫我分析近期的股價趨勢，並列出 3 個觀察重點與未來建議。
            
            股票資料如下：
            {data_text}
            """
            
            try:
                response = client.models.generate_content(
                    model='gemini-1.5-flash',
                    contents=prompt
                )
                # 🌟 將 AI 的回答存進網頁的「短暫記憶池」
                st.session_state.ai_report = response.text
            except Exception as e:
                st.error(f"AI 呼叫失敗，可能流速受限，請稍後再試。錯誤：{e}")

# ==========================================
# 4. 渲染/顯示 AI 分析報告
# ==========================================
# 如果記憶池裡面有報告，就把他顯示在網頁上
if st.session_state.ai_report and st.session_state.current_stock == stock_id:
    st.markdown("---")
    st.subheader("🤖 Gemini AI 專業分析報告")
    st.write(st.session_state.ai_report)
    
    st.markdown("---")
    st.subheader("📧 自動化通知中心")
    st.write(f"點擊下方按鈕，系統會將上方這份 {stock_id} 的分析報告自動寄送到您的信箱 ({TO_EMAIL})。")
    
    # 關卡 D：一鍵寄送電子報
    if st.button("✉️ 立即寄送 AI 股市分析日報"):
        with st.spinner("📨 正在啟動郵件伺服器，發送郵件中..."):
            try:
                # 設定信件格式
                msg = MIMEMultipart()
                msg['From'] = MY_EMAIL
                msg['To'] = TO_EMAIL
                msg['Subject'] = Header(f"🤖 您的專屬 AI 股市日報：{stock_id}", 'utf-8')
                
                # 放入記憶池中的報告內容
                msg.attach(MIMEText(st.session_state.ai_report, 'plain', 'utf-8'))
                
                # 連線到 Gmail 伺服器並寄出
                server = smtplib.SMTP('smtp.gmail.com', 587)
                server.starttls()
                server.login(MY_EMAIL, MY_APP_PASSWORD)
                server.send_message(msg)
                server.quit()
                
                st.success(f"🎉 郵件發送成功！請檢查您的信箱：{TO_EMAIL}")
            except Exception as e:
                st.error(f"❌ 郵件發送失敗。請檢查 Secrets 中的密碼設定。詳細錯誤：{e}")