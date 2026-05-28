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
import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==========================================
# 1. 應用程式初始化與全域設定 (Application Initialization)
# ==========================================
st.set_page_config(page_title="QUANT TERMINAL | AI Analysis", layout="wide")
st.title("QUANT TERMINAL | 股市量化分析與自動化系統")

# ==========================================
# 2. 側邊欄設定與參數配置 (Sidebar & Parameter Configuration)
# ==========================================
with st.sidebar:
    st.subheader("PARAMETER SETTINGS")
    stock_id = st.text_input("輸入股票代碼：", value="2330.TW")
    st.caption("格式：台股加 `.TW` (如 2330.TW)；美股直入代碼 (如 AAPL)。")
    
    timeframe_option = st.selectbox("圖表資料尺度：", ["日線", "周線", "月線"])
    ma_options = st.multiselect("顯示移動平均線：", ["5MA", "10MA", "20MA", "60MA"], default=["5MA", "20MA"])
    
    st.markdown("---")
    st.subheader("AI ENGINE SETTINGS")
    model_options = {
        "Gemini 3.1 Flash Lite (高效益推薦)": "gemini-3.1-flash-lite",
        "Gemini 2.5 Flash Lite (高流速)": "gemini-2.5-flash-lite",
        "Gemini 3.5 Flash (主力深度分析)": "gemini-3.5-flash",
        "Gemini 2.5 Flash (標準分析)": "gemini-2.5-flash",
        "禁用 AI 分析模組 (僅渲染圖表)": "none"
    }
    selected_model_label = st.selectbox("切換運算模型：", list(model_options.keys()))
    selected_api_model = model_options[selected_model_label]
    
    st.markdown("---")
    st.subheader("CUSTOM PROMPT")
    # 強制 LLM 輸出機構級結構化報告，過濾冗餘問候語
    default_prompt = f"""你是一個機構級量化分析系統。請根據以下數據，直接輸出市場分析，絕對不要包含任何問候語或自我介紹。請嚴格按照以下格式輸出：
【趨勢判定】(簡短一句話)
【關鍵支撐與壓力】(明確列出價位)
【量價結構觀察】(說明現況)
【具體操作建議】(給出策略)"""
    user_prompt = st.text_area("自訂系統分析指令：", value=default_prompt, height=200)
    
    st.markdown("---")
    st.subheader("AUTOMATION & MAIL")
    recipient_email = st.text_input("設定收件 Email：", value="")

    schedule_mode = st.selectbox("排程觸發模式：", ["暫停排程", "按天數執行 (常態)", "快速測試模式 (按分鐘)"])
    freq_days, send_hour, send_minute, freq_mins = 1, 8, 0, 2
    
    if schedule_mode == "按天數執行 (常態)":
        freq_days = st.number_input("發送間隔天數：", min_value=1, max_value=30, value=1)
        send_time = st.time_input("每日發送時間：", value=datetime.time(8, 0))
        send_hour = send_time.hour
        send_minute = send_time.minute
        st.info(f"排程已設定：每 {freq_days} 天於 {send_time.strftime('%H:%M')} 觸發。")
    elif schedule_mode == "快速測試模式 (按分鐘)":
        freq_mins = st.number_input("發送間隔(分鐘)：", min_value=1, max_value=60, value=2)
        st.warning(f"注意：測試模式啟動，系統將每 {freq_mins} 分鐘觸發一次。")

# ==========================================
# 3. 環境變數載入與狀態管理 (Environment Variables & State Management)
# ==========================================
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
MY_EMAIL = st.secrets["MY_EMAIL"]
MY_APP_PASSWORD = st.secrets["MY_APP_PASSWORD"]

client = genai.Client(api_key=GOOGLE_API_KEY)

# 初始化 Streamlit Session State，確保跨組件狀態重繪時不遺失
if "ai_report" not in st.session_state:
    st.session_state.ai_report = None
if "current_stock" not in st.session_state:
    st.session_state.current_stock = ""
if "last_request_time" not in st.session_state:
    st.session_state.last_request_time = 0
if "raw_data" not in st.session_state:
    st.session_state.raw_data = None 

# ==========================================
# 4. 核心邏輯：手動觸發資料同步與 AI 推理 (Core Logic: Data Sync & AI Inference)
# ==========================================
if st.button("EXECUTE / 執行核心抓取與運算", type="primary"):
    current_time = time.time()
    
    # 實作簡易 Rate Limiting 避免 API 濫用
    if (current_time - st.session_state.last_request_time) < 3:
        st.error(f"SYSTEM BLOCKED: 觸發防護機制，請稍後重試。")
    else:
        st.session_state.last_request_time = current_time
        st.session_state.current_stock = stock_id
        
        with st.spinner("FETCHING DATA / 正在向資料源請求歷史數據..."):
            stock = yf.Ticker(stock_id)
            # 獲取最大合理範圍歷史數據供後續時間尺度切換使用
            hist_data = stock.history(period="15y", interval="1d")
            
        if not hist_data.empty:
            # 寫入本地 SQLite 進行快取 (Caching)
            conn = sqlite3.connect("stock_data.db")
            hist_data.to_sql("daily_price", conn, if_exists="replace")
            conn.close()
            st.session_state.raw_data = hist_data 
            
            if selected_api_model == "none":
                st.session_state.ai_report = None
                st.success("DATA SYNCED / 數據同步完成 (AI 模組已停用)")
            else:
                with st.spinner(f"PROCESSING / 引擎 {selected_api_model} 運算中..."):
                    # 擷取尾端 30 筆資料供 LLM 推理，最佳化 Token 消耗
                    df_init = hist_data.tail(30)
                    full_prompt = f"{user_prompt}\n\n目標標的: {stock_id}\n近期交易數據:\n{df_init.to_string()}"
                    try:
                        response = client.models.generate_content(model=selected_api_model, contents=full_prompt)
                        st.session_state.ai_report = response.text
                        st.success("ANALYSIS COMPLETE / 分析運算完成")
                    except Exception as e:
                        st.error(f"API ERROR / 運算節點異常：{e}")
        st.rerun()

# ==========================================
# 5. 實時動態圖表渲染區 (Real-time Chart Rendering)
# ==========================================
if st.session_state.raw_data is not None and st.session_state.current_stock == stock_id:
    
    # 從本地 SQLite 讀取快取數據
    conn = sqlite3.connect("stock_data.db")
    df_db = pd.read_sql("SELECT * FROM daily_price", conn)
    conn.close()
    
    df_db['Date'] = pd.to_datetime(df_db['Date'])
    df_db.set_index('Date', inplace=True)
    
    # 提取最新一筆交易日數據
    latest_row = df_db.iloc[-1]
    latest_date_str = df_db.index[-1].strftime('%Y-%m-%d')
    
    # 頂部儀表板配置 (Top Dashboard Metrics)
    st.markdown("---")
    st.subheader(f"{stock_id} 市場報價總覽")
    st.caption(f"Last Update: {latest_date_str}")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Open / 開盤", value=f"{latest_row['Open']:.2f}")
    with col2:
        st.metric(label="High / 最高", value=f"{latest_row['High']:.2f}")
    with col3:
        st.metric(label="Low / 最低", value=f"{latest_row['Low']:.2f}")
    with col4:
        st.metric(label="Close / 收盤", value=f"{latest_row['Close']:.2f}")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 依據使用者選擇進行 Pandas 重新取樣 (Resampling OHLC)
    agg_dict = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
    
    if "周線" in timeframe_option:
        df_resampled = df_db.resample('W').agg(agg_dict).dropna() 
    elif "月線" in timeframe_option:
        df_resampled = df_db.resample('ME').agg(agg_dict).dropna()  
    else:
        df_resampled = df_db.dropna()                      
        
    df_plot = df_resampled.copy() 

    # 設定預設可視視窗範圍 (Viewport Window Configuration)
    total_points = len(df_plot)
    if "周線" in timeframe_option:
        visible_window = 260  
    elif "月線" in timeframe_option:
        visible_window = 180  
    else:
        visible_window = 250  

    start_idx = max(0, total_points - visible_window)
    end_idx = total_points - 1

    # 計算 Y 軸動態範圍，加入 5% 留白緩衝 (Padding)
    df_visible = df_plot.tail(visible_window)
    price_min = df_visible['Low'].min() * 0.95
    price_max = df_visible['High'].max() * 1.05

    # 計算移動平均線 (Moving Averages)
    for ma in ma_options:
        window = int(ma.replace("MA", ""))
        df_plot[ma] = df_plot['Close'].rolling(window=window).mean()
        
    # 計算 KD 隨機指標 (Stochastic Oscillator)
    low_min = df_plot['Low'].rolling(window=9).min()
    high_max = df_plot['High'].rolling(window=9).max()
    rsv = (df_plot['Close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(50) 
    
    k_list, d_list = [], []
    k_val, d_val = 50.0, 50.0 
    for r in rsv:
        k_val = (2/3) * k_val + (1/3) * r
        d_val = (2/3) * d_val + (1/3) * k_val
        k_list.append(k_val)
        d_list.append(d_val)
        
    df_plot['K'] = k_list
    df_plot['D'] = d_list

    # Plotly 雙圖表實例化 (Subplot Instantiation)
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True,          
        vertical_spacing=0.06,      
        row_heights=[0.68, 0.32]    
    )

    x_dates_str = df_plot.index.strftime('%Y-%m-%d')
    
    # 繪製主圖表：收盤價走勢線
    fig.add_trace(go.Scatter(
        x=x_dates_str, y=df_plot['Close'],
        mode='lines', name='Price',
        line=dict(color='#2ecc71', width=3, dash='solid')
    ), row=1, col=1)

    # 疊加均線
    ma_colors = {"5MA": "#e67e22", "10MA": "#9b59b6", "20MA": "#e74c3c", "60MA": "#3498db"}
    for ma in ma_options:
        if ma in df_plot.columns:
            fig.add_trace(go.Scatter(
                x=x_dates_str, y=df_plot[ma],
                mode='lines', name=ma,
                line=dict(color=ma_colors.get(ma, 'gray'), width=1.5, dash='dash')
            ), row=1, col=1)

    # 繪製副圖表：KD 指標
    fig.add_trace(go.Scatter(
        x=x_dates_str, y=df_plot['K'],
        mode='lines', name='K (Fast)',
        line=dict(color='#3498db', width=2)
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=x_dates_str, y=df_plot['D'],
        mode='lines', name='D (Slow)',
        line=dict(color='#e67e22', width=2)
    ), row=2, col=1)

    # KD 指標超買超賣基準線 (Overbought / Oversold thresholds)
    fig.add_hline(y=80, line_dash="dot", line_color="rgba(231, 76, 60, 0.4)", row=2, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color="rgba(52, 152, 219, 0.4)", row=2, col=1)

    # 佈局與軸線配置 (Layout & Axis Configuration)
    fig.update_layout(dragmode='pan')

    # 設定 X 軸為分類型態，確保交易日連續無斷點
    fig.update_xaxes(type='category', range=[start_idx, end_idx], row=1, col=1)
    fig.update_xaxes(type='category', range=[start_idx, end_idx], row=2, col=1, title_text="Date")
    
    # 允許使用者在必要時進行 Y 軸的垂直拖曳 (解除 fixedrange)
    fig.update_yaxes(range=[price_min, price_max], fixedrange=False, row=1, col=1)
    fig.update_yaxes(range=[0, 100], fixedrange=False, row=2, col=1) 

    # 繪製外框線，提升專業視覺質感
    fig.update_xaxes(showline=True, linewidth=1.5, linecolor='#444444', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1.5, linecolor='#444444', mirror=True)

    fig.update_layout(
        yaxis_title="Price",
        yaxis2_title="KD Index",
        hovermode="x unified",
        height=650, 
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            bgcolor="rgba(0, 0, 0, 0)",
            bordercolor="rgba(0, 0, 0, 0)"
        ),
        margin=dict(l=10, r=10, t=40, b=10) 
    )

    st.subheader(f"TECHNICAL ANALYSIS | {timeframe_option}")
    st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': True})

# ==========================================
# 6. AI 分析報告呈現與電子郵件派發 (AI Report Rendering & Email Dispatch)
# ==========================================
if st.session_state.ai_report and st.session_state.current_stock == stock_id:
    st.markdown("---")
    
    # 採用摺疊面板收納長篇幅報告，最佳化頁面空間
    with st.expander(f"QUANTITATIVE REPORT | 機構級分析報告 (Model: {selected_api_model})", expanded=True):
        st.write(st.session_state.ai_report)
    
    st.markdown("<br>", unsafe_allow_html=True)
    col_btn1, col_btn2 = st.columns([1, 1])
    
    with col_btn1:
        if st.button("MANUAL DISPATCH / 手動派發報告至信箱", use_container_width=True):
            if not recipient_email:
                st.warning("SYSTEM ALERT: 請先設定收件 Email 位址。")
            else:
                with st.spinner(f"DISPATCHING / 正在遞送至 {recipient_email} ..."):
                    try:
                        msg = MIMEMultipart()
                        msg['From'] = MY_EMAIL
                        msg['To'] = recipient_email
                        msg['Subject'] = Header(f"QUANT REPORT | 標的 {stock_id} 分析報告", 'utf-8')
                        msg.attach(MIMEText(st.session_state.ai_report, 'plain', 'utf-8'))
                        
                        server = smtplib.SMTP('smtp.gmail.com', 587)
                        server.starttls()
                        server.login(MY_EMAIL, MY_APP_PASSWORD)
                        server.send_message(msg)
                        server.quit()
                        st.success(f"DISPATCH SUCCESS / 報告已成功派發。")
                    except Exception as e:
                        st.error(f"DISPATCH FAILED / 遞送失敗：{e}")

# ==========================================
# 7. 排程設定檔同步 (Scheduler Configuration Synchronization)
# ==========================================
if schedule_mode != "暫停排程":
    st.markdown("---")
    if st.button("SYNC DAEMON / 同步排程設定至背景常駐程式"):
        if not recipient_email:
            st.error("SYSTEM ALERT: 無法同步，請確認 Email 欄位。")
        else:
            config_data = {
                "stock_id": stock_id,
                "model": selected_api_model,
                "prompt": user_prompt,
                "recipient_email": recipient_email,
                "schedule_mode": schedule_mode,
                "freq_days": freq_days,
                "send_hour": send_hour,
                "send_minute": send_minute,
                "freq_mins": freq_mins,
                "timeframe": timeframe_option
            }
            # 將設定序列化為 JSON，供守護程式 (Daemon) 讀取
            with open("scheduler_config.json", "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            st.success("SYNC SUCCESS / 排程參數已寫入本機設定檔。")