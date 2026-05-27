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
import json  # 🌟 新增 JSON 套件，用來儲存排程設定檔

# ==========================================
# 1. 網頁初始化與標題設定
# ==========================================
st.set_page_config(page_title="AI 股市分析與自動化系統", layout="wide")
st.title("📈 終極整合：AI 股市分析與郵件自動化系統")

# ==========================================
# 2. 側邊欄設定 (新增格式提醒、自訂Prompt、排程設定)
# ==========================================
with st.sidebar:
    st.header("⚙️ 1. 股票設定")
    stock_id = st.text_input("請輸入股票代碼：", value="2330.TW")
    # 🌟 需求 1：在輸入框下方新增精緻的格式提醒字
    st.caption("💡 格式提醒：台股請務必加上字尾 `.TW`（如 `2330.TW`、`0050.TW`）；美股請直接輸入大寫代碼（如 `AAPL`、`NVDA`、`TSLA`）。")
    
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
    # 🌟 需求 2：加入可輸入 prompt 的大文字欄位，並給予專業的預設值
    default_prompt = f"""你是一位專業的股市分析師。
請根據以下提供的最近一個月歷史股價資料，用簡單易懂的繁體中文，幫我分析近期的股價趨勢，並列出 3 個觀察重點與未來的具體操作建議。"""
    
    user_prompt = st.text_area("您可以隨時修改給 AI 的指令：", value=default_prompt, height=150)
    
    st.markdown("---")
    st.header("📧 4. 收件信箱設定")
    recipient_email = st.text_input("請輸入接收報告的 Email：", value="")

    st.markdown("---")
    # 🌟 需求 3：網頁端的排程設定 UI 面板
    st.header("⏰ 5. 背景自動化排程中心")
    schedule_mode = st.selectbox("請選擇自動通知的週期：", ["暫不開啟排程", "每日固定時間發送", "每三天固定發送通知"])
    
    if schedule_mode == "每日固定時間發送":
        send_hour = st.slider("請選擇每天早上幾點發送 (24小時制)：", min_value=0, max_value=23, value=8)
        st.info(f"設定成功：系統將於每天 **{send_hour}:00** 自動為您分析並寄信。")
    elif schedule_mode == "每三天固定發送通知":
        st.info("設定成功：系統將每隔 **3 天** 自動為您打包發送一次股市概況報告。")

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
# 4. 核心邏輯：即時手動分析按鈕
# ==========================================
if st.button("🚀 開始進行即時核心分析（抓取 -> 存庫 -> AI分析）"):
    current_time = time.time()
    time_elapsed = current_time - st.session_state.last_request_time
    
    if time_elapsed < 60:
        wait_time = int(60 - time_elapsed)
        st.error(f"🛑 流量保護觸發！為保護您的 API 額度，請再等待 **{wait_time} 秒** 後重試。")
    else:
        st.session_state.last_request_time = current_time
        st.session_state.current_stock = stock_id
        
        with st.spinner("🔍 正在從 Yahoo Finance 抓取最新股價..."):
            stock = yf.Ticker(stock_id)
            hist_data = stock.history(period="1mo")
            
        if hist_data.empty:
            st.error("❌ 找不到該股票資料，請檢查代碼是否正確。")
        else:
            with st.spinner("📂 正在將資料寫入並讀取本地 SQLite 資料庫..."):
                conn = sqlite3.connect("stock_data.db")
                hist_data.to_sql("daily_price", conn, if_exists="replace")
                df_from_db = pd.read_sql("SELECT * FROM daily_price", conn)
                conn.close()
            
            st.subheader(f"📊 {stock_id} 最近一個月歷史收盤價走勢")
            st.line_chart(df_from_db.set_index('Date')['Close'])
            
            with st.spinner(f"🧠 正在呼叫 {selected_api_model} 進行分析..."):
                data_text = df_from_db.to_string()
                # 🌟 將原本死硬的提示詞，換成使用者在網頁大文字框裡輸入的「user_prompt」
                full_prompt = f"{user_prompt}\n\n股票代碼: {stock_id}\n資料數據如下:\n{data_text}"
                
                try:
                    response = client.models.generate_content(
                        model=selected_api_model,
                        contents=full_prompt
                    )
                    st.session_state.ai_report = response.text
                    st.success("✅ AI 分析完畢！")
                except Exception as e:
                    st.error(f"❌ 呼叫失敗。錯誤原因：{e}")

# ==========================================
# 5. 儲存排程設定檔按鈕（核心整併關鍵）
# ==========================================
if schedule_mode != "暫不開啟排程":
    st.markdown("---")
    st.subheader("💾 儲存並同步自動化排程")
    if st.button("💾 點擊同步排程設定到後台守護程序"):
        if not recipient_email:
            st.error("❌ 儲存失敗：必須先輸入「接收報告的 Email」才能啟動背景排程功能！")
        else:
            # 打包所有的設定參數
            config_data = {
                "stock_id": stock_id,
                "model": selected_api_model,
                "prompt": user_prompt,
                "recipient_email": recipient_email,
                "schedule_mode": schedule_mode,
                "send_hour": send_hour if schedule_mode == "每日固定時間發送" else 8
            }
            # 寫入本地 config.json，供背景的排程腳本讀取
            with open("scheduler_config.json", "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            st.success("🎉 排程設定成功！已成功同步至本地設定檔 `scheduler_config.json`。")

# ==========================================
# 6. 渲染手動分析報告與寄信
# ==========================================
if st.session_state.ai_report and st.session_state.current_stock == stock_id:
    st.markdown("---")
    st.subheader(f"🤖 AI 專業分析報告 (由 {selected_api_model} 提供)")
    st.write(st.session_state.ai_report)
    
    st.markdown("---")
    st.subheader("📧 自動化通知中心")
    if st.button("✉️ 立即寄送此份股市日報"):
        if not recipient_email:
            st.warning("⚠️ 請先在左側邊欄輸入「接收報告的 Email」！")
        else:
            with st.spinner(f"📨 正在發送郵件至 {recipient_email} ..."):
                try:
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
                    st.success(f"🎉 郵件發送成功！")
                except Exception as e:
                    st.error(f"❌ 郵件發送失敗。詳細錯誤：{e}")