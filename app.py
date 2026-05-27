import streamlit as st
import yfinance as yf
from google import genai

# ==========================================
# 1. 設定網頁的標題與輸入框
# ==========================================
st.title("📈 我的專屬 AI 股市分析 App")
st.write("只要輸入股票代碼，AI 就會幫你抓取近一個月的資料並自動分析！")

# 建立一個文字輸入框，讓你可以隨時更改想查的股票 (預設為台積電)
stock_id = st.text_input("請輸入股票代碼 (例如：2330.TW, AAPL, NVDA)", value="2330.TW")

# ==========================================
# 2. 設定 AI 工具
# ==========================================
# 把原本寫死金鑰的那行刪掉，換成下面這行：
# 這代表「請去 Streamlit 的保險箱裡面拿鑰匙」
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
client = genai.Client(api_key=GOOGLE_API_KEY)

# ==========================================
# 3. 建立執行按鈕與核心邏輯
# ==========================================
# 當使用者點擊「開始 AI 分析」這個按鈕時，才會執行底下的程式碼
if st.button("開始 AI 分析"):
    
    # 顯示載入中的動畫
    with st.spinner("🔄 正在為您抓取最新股價資料..."):
        # 抓取股票資料
        stock = yf.Ticker(stock_id)
        hist_data = stock.history(period="1mo")

    # 檢查是否真的有抓到資料
    if hist_data.empty:
        st.error("找不到這檔股票的資料，請確認代碼是否正確！")
    else:
        st.success("✅ 資料抓取成功！")
        
        # Streamlit 超強功能：一行程式碼直接畫出漂亮的收盤價折線圖！
        st.subheader(f"{stock_id} 近一個月收盤價走勢")
        st.line_chart(hist_data['Close'])

        # 準備給 AI 的提示詞
        data_text = hist_data.to_string()
        prompt = f"""
        你是一位專業的股市分析師。
        請根據以下 {stock_id} 最近一個月的歷史股價資料，
        用簡單易懂的繁體中文，幫我分析近期的股價趨勢，並列出 3 個觀察重點。
        
        股票資料如下：
        {data_text}
        """

        # 顯示 AI 分析中的提示
        st.info("🧠 AI 正在努力分析中，這可能需要幾秒鐘...")
        
        # 呼叫 Gemini AI
        try:
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            
            # 把 AI 的回答顯示在網頁上
            st.subheader("🤖 Gemini AI 分析報告")
            st.write(response.text)
            
        except Exception as e:
            st.error(f"❌ AI 分析時發生錯誤，請檢查 API 金鑰或網路狀態。詳細錯誤：{e}")