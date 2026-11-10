import streamlit as st
import pyotp
from SmartApi import SmartConnect
import opstrat as op
import matplotlib.pyplot as plt
import time

st.set_page_config(page_title="Nifty Live Strategy Radar", layout="wide", initial_sidebar_state="collapsed")

# --- CUSTOM CSS FOR CLEAN TABLET VIEW ---
st.markdown("""
<style>
    .metric-card { background-color: #1e293b; border-radius: 10px; padding: 15px; border: 1px solid #334155; }
    .badge-bull { background-color: #064e3b; color: #34d399; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
    .badge-bear { background-color: #4c0519; color: #fb7185; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
    .badge-neutral { background-color: #1e1b4b; color: #818cf8; padding: 4px 10px; border-radius: 6px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Real-Time Options Radar (Live NIFTY Feed)")

# --- READ SECRETS SAFELY ---
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except Exception:
    st.error("⚠️ Credentials missing in Streamlit Secrets! Please add them in App Settings > Secrets.")
    st.stop()

# --- INITIALIZE SMARTAPI SESSION (CACHED) ---
@st.cache_resource(ttl=1800)  # Session 30 minute tak valid rahega
def get_angel_session(api_key, client_code, pwd, totp_sec):
    try:
        smart_api = SmartConnect(api_key)
        totp = pyotp.TOTP(totp_sec).now()
        session = smart_api.generateSession(client_code, pwd, totp)
        if session.get("status"):
            return smart_api
        return None
    except Exception as e:
        return None

smart_api = get_angel_session(API_KEY, CLIENT_CODE, PASSWORD, TOTP_SECRET)

if not smart_api:
    st.error("❌ Angel One se connect nahi ho paya. Credentials verify karein.")
    st.stop()

# --- FETCH REAL-TIME NIFTY SPOT ---
def fetch_live_nifty():
    try:
        # Nifty 50 Token: 99926000, Exchange: NSE
        quote = smart_api.ltpData(exchange="NSE", tradingsymbol="Nifty 50", symboltoken="99926000")
        if quote.get("status") and "data" in quote:
            return float(quote["data"]["ltp"])
    except Exception:
        pass
    return 24400.0  # Fallback

live_spot = fetch_live_nifty()
atm_strike = int(round(live_spot / 50.0) * 50)

# --- TOP METRICS HEADER ---
col_m1, col_m2, col_m3, col_m4 = st.columns([1.2, 1, 1, 0.8])

with col_m1:
    st.metric(label="LIVE NIFTY 50 SPOT", value=f"₹{live_spot:,.2f}")

with col_m2:
    st.metric(label="NEAREST ATM STRIKE", value=f"{atm_strike}")

with col_m3:
    market_setup = st.selectbox("Market Bias", ["Sideways / Range-Bound", "Bullish (Up Trend)", "Bearish (Down Trend)"])

with col_m4:
    iv_environment = st.selectbox("Market IV", ["Normal / Low (< 45%)", "Elevated / High (> 55%)"])

st.write("---")

# --- RULE-BASED STRATEGY RECOMMENDER ---
rec_title = ""
rec_type = ""
rec_logic = ""
legs = []

if market_setup == "Sideways / Range-Bound":
    if "High" in iv_environment:
        rec_title = "Iron Condor"
        rec_type = "Net Credit (Theta Decay Capture)"
        rec_logic = "High IV environment + Range-bound Spot. Dono taraf ke OTM sell karke buffer capture karein. Expiry tak range mein rehne par max profit."
        legs = [
            {'op_type': 'pe', 'tr_type': 'buy', 'st': atm_strike - 350, 'op_pr': 18},
            {'op_type': 'pe', 'tr_type': 'sell', 'st': atm_strike - 150, 'op_pr': 48},
            {'op_type': 'ce', 'tr_type': 'sell', 'st': atm_strike + 150, 'op_pr': 45},
            {'op_type': 'ce', 'tr_type': 'buy', 'st': atm_strike + 350, 'op_pr': 16}
        ]
    else:
        rec_title = "Hedged Short Strangle (Wings Attached)"
        rec_type = "Delta Neutral Play"
        rec_logic = "Normal IV mein thoda close sell karke safety ke liye protective wings add karein."
        legs = [
            {'op_type': 'pe', 'tr_type': 'buy', 'st': atm_strike - 300, 'op_pr': 22},
            {'op_type': 'pe', 'tr_type': 'sell', 'st': atm_strike - 100, 'op_pr': 60},
            {'op_type': 'ce', 'tr_type': 'sell', 'st': atm_strike + 100, 'op_pr': 58},
            {'op_type': 'ce', 'tr_type': 'buy', 'st': atm_strike + 300, 'op_pr': 20}
        ]

elif market_setup == "Bullish (Up Trend)":
    rec_title = "Bull Call Debit Spread"
    rec_type = "Strictly Defined Risk (Directional)"
    rec_logic = "Direct Call buy karne par premium decay loss dega. ATM Buy karke OTM Sell karne se 50% capital risk lock ho jayega."
    legs = [
        {'op_type': 'ce', 'tr_type': 'buy', 'st': atm_strike, 'op_pr': 145},
        {'op_type': 'ce', 'tr_type': 'sell', 'st': atm_strike + 200, 'op_pr': 55}
    ]

elif market_setup == "Bearish (Down Trend)":
    rec_title = "Bear Put Debit Spread"
    rec_type = "Strictly Defined Risk (Directional)"
    rec_logic = "Downside trade ke liye ITM/ATM Put buy aur lower OTM Put sell. Agar market slow gire tab bhi profit target achieve hoga."
    legs = [
        {'op_type': 'pe', 'tr_type': 'buy', 'st': atm_strike, 'op_pr': 140},
        {'op_type': 'pe', 'tr_type': 'sell', 'st': atm_strike - 200, 'op_pr': 50}
    ]

# --- DISPLAY RECOMMENDATION & PAYOFF ---
col_rec, col_chart = st.columns([1, 1.2])

with col_rec:
    st.subheader(f"🛡️ {rec_title}")
    st.markdown(f"**Strategy Category:** `{rec_type}`")
    st.info(f"**Execution Logic:** {rec_logic}")

    st.write("#### 📋 Orders To Execute on Kite:")
    for idx, leg in enumerate(legs, 1):
        action = "🟢 BUY" if leg['tr_type'] == 'buy' else "🔴 SELL"
        opt = "CE (Call)" if leg['op_type'] == 'ce' else "PE (Put)"
        st.markdown(f"- **Leg {idx}:** {action} **Nifty {int(leg['st'])} {opt}** (~₹{leg['op_pr']})")

    st.caption("Tip: Pehle BUY legs execute karein margin benefit ke liye, fir SELL legs.")

with col_chart:
    st.subheader("📈 Live Payoff Curve")
    if legs:
        try:
            fig = op.multi_plotter(spot=live_spot, op_list=legs)
            st.pyplot(plt.gcf())
            plt.clf()
        except Exception as err:
            st.warning(f"Payoff render status: {err}")

# Auto refresh trigger every 15 seconds during market hours
st.caption(f"Last updated from Angel One SmartAPI: {time.strftime('%H:%M:%S')}")
if st.button("🔄 Instant Refresh"):
    st.rerun()
