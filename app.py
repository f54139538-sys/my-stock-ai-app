import streamlit as st
import yfinance as yf
import sqlite3
import pandas as pd
from google import genai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import time
import json
import datetime # 🌟 新增處理時間的套件

# ==========================================
# 1. 網頁初始化與標題設定
# ==========================================
st.set_page_config(page_title="AI 股市分析與自動化系統", layout="wide")
st.title("📈 終極整合：AI 股市分析與郵件自動化系統")

# ==========================================
# 2. 側邊欄設定 (新增時間選擇器與測試模式)
# ==========================================
with st.sidebar:
    st.header("⚙️ 1. 股票設定")
    stock_id = st.text_input("請輸入股票代碼：", value="2330.TW")
    st.caption("💡 格式提醒：台股請加 `.TW` (如 `2330.TW`)；美股請打代碼 (如 `AAPL`)。")
    
    st.markdown("---")
    st.header("🧠 2. AI 模型選擇")
    model_options = {
        "Gemini 3.1 Flash Lite (🔥推薦！限15次/分)": "gemini-3.1-flash-lite",
        "Gemini 2.5 Flash Lite (流速佳, 限10次/分)": "gemini-2.5-flash-lite",
        "Gemini 3.5 Flash (最新主力, 限5次/分)": "gemini-3.5-flash",
        "Gemini 2.5 Flash (限5次/分)": "gemini-2.5-flash"
    }
    selected_model_label = st.selectbox("請手動切換您想使用的 AI 模型：", list(model_options.keys()))
    selected_api_model = model_options[selected_model_label]
    
    st.markdown("---")
    st.header("📝 3. 自訂 AI 分析提示詞")
    default_prompt = f"""你是一位專業的股市分析師。
請根據以下提供的最近一個月歷史股價資料，用簡單易懂的繁體中文，幫我分析近期的股價趨勢，並列出 3 個觀察重點與未來的具體操作建議。(字數控制在約300字))"""
    user_prompt = st.text_area("您可以隨時修改給 AI 的指令：", value=default_prompt, height=150)
    
    st.markdown("---")
    st.header("📧 4. 收件信箱設定")
    recipient_email = st.text_input("請輸入接收報告的 Email：", value="")

    st.markdown("---")
    st.header("⏰ 5. 背景自動化排程中心")
    
    # 🌟 升級版排程選單：加入自訂頻率與測試模式
    schedule_mode = st.selectbox("請選擇排程模式：", ["暫不開啟排程", "按天數執行 (含每日)", "快速測試模式 (按分鐘)"])
    
    freq_days, send_hour, send_minute, freq_mins = 1, 8, 0, 2 # 設定預設變數
    
    if schedule_mode == "按天數執行 (含每日)":
        freq_days = st.number_input("每隔幾天發送一次？ (1 代表每天)", min_value=1, max_value=30, value=1)
        send_time = st.time_input("請選擇發送時間：", value=datetime.time(8, 0)) # 讓你可以精準選到 08:30
        send_hour = send_time.hour
        send_minute = send_time.minute
        st.info(f"✅ 系統將每 **{freq_days} 天** 於 **{send_time.strftime('%H:%M')}** 發送報告。")
        
    elif schedule_mode == "快速測試模式 (按分鐘)":
        freq_mins = st.number_input("每隔幾分鐘發送一次？", min_value=1, max_value=60, value=2)
        st.warning(f"⚠️ 測試模式啟動：系統將每 **{freq_mins} 分鐘** 狂發一次信件！測試完畢請務必切換回正常天數排程。")

# ==========================================
# 3. 讀取金鑰與初始化記憶池
# ==========================================
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
MY_EMAIL = st.secrets["MY_EMAIL"]
MY_APP_PASSWORD = st.secrets["MY_APP_PASSWORD"]

client = genai.Client(api_key=GOOGLE_API_KEY)

if "ai_report" not in st.session_state:
    st.session_state.ai_report = None
if "current_stock" not in st.session_state:
    st.session_state.current_stock = ""
if "last_request_time" not in st.session_state:
    st.session_state.last_request_time = 0

# ==========================================
# 4. 手動即時分析 (移除了中間干擾的假按鈕區塊)
# ==========================================
if st.button("🚀 開始進行即時核心分析"):
    current_time = time.time()
    if (current_time - st.session_state.last_request_time) < 60:
        st.error(f"🛑 流量保護觸發！請稍後重試。")
    else:
        st.session_state.last_request_time = current_time
        st.session_state.current_stock = stock_id
        
        with st.spinner("🔍 資料處理與 AI 分析中..."):
            stock = yf.Ticker(stock_id)
            hist_data = stock.history(period="1mo")
            if not hist_data.empty:
                conn = sqlite3.connect("stock_data.db")
                hist_data.to_sql("daily_price", conn, if_exists="replace")
                df_from_db = pd.read_sql("SELECT * FROM daily_price", conn)
                conn.close()
                
                st.subheader(f"📊 {stock_id} 近一個月走勢")
                st.line_chart(df_from_db.set_index('Date')['Close'])
                
                full_prompt = f"{user_prompt}\n\n股票代碼: {stock_id}\n資料數據如下:\n{df_from_db.to_string()}"
                try:
                    response = client.models.generate_content(model=selected_api_model, contents=full_prompt)
                    st.session_state.ai_report = response.text
                    st.success("✅ 分析完畢！")
                except Exception as e:
                    st.error(f"❌ 呼叫失敗：{e}")

# ==========================================
# 5. 儲存排程設定檔按鈕 (完美打包變數)
# ==========================================
if schedule_mode != "暫不開啟排程":
    st.markdown("---")
    st.subheader("💾 儲存並同步自動化排程")
    if st.button("💾 點擊同步排程設定到後台守護程序"):
        if not recipient_email:
            st.error("❌ 儲存失敗：必須先輸入「接收報告的 Email」！")
        else:
            # 打包所有的設定參數，包含最新的時間頻率
            config_data = {
                "stock_id": stock_id,
                "model": selected_api_model,
                "prompt": user_prompt,
                "recipient_email": recipient_email,
                "schedule_mode": schedule_mode,
                "freq_days": freq_days,
                "send_hour": send_hour,
                "send_minute": send_minute,
                "freq_mins": freq_mins
            }
            # 寫入設定檔
            with open("scheduler_config.json", "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            st.success("🎉 排程設定成功！已同步至本地設定檔。")

# ==========================================
# 6. 渲染手動分析報告與真正的手動寄信按鈕
# ==========================================
if st.session_state.ai_report and st.session_state.current_stock == stock_id:
    st.markdown("---")
    st.subheader(f"🤖 AI 專業分析報告 (由 {selected_api_model} 提供)")
    st.write(st.session_state.ai_report)
    
    st.markdown("---")
    st.subheader("📧 手動通知中心")
    if st.button("✉️ 手動立即寄送此份股市日報"):
        if not recipient_email:
            st.warning("⚠️ 請先在左側邊欄輸入「接收報告的 Email」！")
        else:
            with st.spinner(f"📨 正在發送郵件至 {recipient_email} ..."):
                try:
                    # 這是真正的寄信邏輯，絕不省略！
                    msg = MIMEMultipart()
                    msg['From'] = MY_EMAIL
                    msg['To'] = recipient_email
                    msg['Subject'] = Header(f"🤖 您的專屬 AI 股市日報：{stock_id}", 'utf-8')
                    msg.attach(MIMEText(st.session_state.ai_report, 'plain', 'utf-8'))
                    
                    server = smtplib.SMTP('smtp.gmail.com', 587)
                    server.starttls()
                    server.login(MY_EMAIL, MY_APP_PASSWORD)
                    server.send_message(msg)
                    server.quit()
                    st.success(f"🎉 郵件發送成功！請去信箱檢查。")
                except Exception as e:
                    st.error(f"❌ 郵件發送失敗。詳細錯誤：{e}")