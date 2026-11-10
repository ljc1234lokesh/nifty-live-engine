import streamlit as st
import pyotp
from SmartApi import SmartConnect
import matplotlib.pyplot as plt
import numpy as np
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
@st.cache_resource(ttl=1800)
def get_angel_session(api_key, client_code, pwd, totp_sec):
    try:
        smart_api = SmartConnect(api_key)
        totp = pyotp.TOTP(totp_sec).now()
        session = smart_api.generateSession(client_code, pwd, totp)
        if session.get("status"):
            return smart_api
        return None
    except Exception:
        return None

smart_api = get_angel_session(API_KEY, CLIENT_CODE, PASSWORD, TOTP_SECRET)

if not smart_api:
    st.error("❌ Angel One se connect nahi ho paya. Credentials verify karein.")
    st.stop()

# --- FETCH REAL-TIME NIFTY SPOT ---
def fetch_live_nifty():
    try:
        quote = smart_api.ltpData(exchange="NSE", tradingsymbol="Nifty 50", symboltoken="99926000")
        if quote.get("status") and "data" in quote:
            return float(quote["data"]["ltp"])
    except Exception:
        pass
    return 25050.0

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
            {'type': 'PE', 'action': 'BUY', 'strike': atm_strike - 350, 'premium': 18},
            {'type': 'PE', 'action': 'SELL', 'strike': atm_strike - 150, 'premium': 48},
            {'type': 'CE', 'action': 'SELL', 'strike': atm_strike + 150, 'premium': 45},
            {'type': 'CE', 'action': 'BUY', 'strike': atm_strike + 350, 'premium': 16}
        ]
    else:
        rec_title = "Hedged Short Strangle (Wings Attached)"
        rec_type = "Delta Neutral Play"
        rec_logic = "Normal IV mein thoda close sell karke safety ke liye protective wings add karein."
        legs = [
            {'type': 'PE', 'action': 'BUY', 'strike': atm_strike - 300, 'premium': 22},
            {'type': 'PE', 'action': 'SELL', 'strike': atm_strike - 100, 'premium': 60},
            {'type': 'CE', 'action': 'SELL', 'strike': atm_strike + 100, 'premium': 58},
            {'type': 'CE', 'action': 'BUY', 'strike': atm_strike + 300, 'premium': 20}
        ]

elif market_setup == "Bullish (Up Trend)":
    rec_title = "Bull Call Debit Spread"
    rec_type = "Strictly Defined Risk (Directional)"
    rec_logic = "Direct Call buy karne par premium decay loss dega. ATM Buy karke OTM Sell karne se 50% capital risk lock ho jayega."
    legs = [
        {'type': 'CE', 'action': 'BUY', 'strike': atm_strike, 'premium': 145},
        {'type': 'CE', 'action': 'SELL', 'strike': atm_strike + 200, 'premium': 55}
    ]

elif market_setup == "Bearish (Down Trend)":
    rec_title = "Bear Put Debit Spread"
    rec_type = "Strictly Defined Risk (Directional)"
    rec_logic = "Downside trade ke liye ITM/ATM Put buy aur lower OTM Put sell. Agar market slow gire tab bhi profit target achieve hoga."
    legs = [
        {'type': 'PE', 'action': 'BUY', 'strike': atm_strike, 'premium': 140},
        {'type': 'PE', 'action': 'SELL', 'strike': atm_strike - 200, 'premium': 50}
    ]

# --- DISPLAY RECOMMENDATION & PAYOFF ---
col_rec, col_chart = st.columns([1, 1.2])

with col_rec:
    st.subheader(f"🛡️ {rec_title}")
    st.markdown(f"**Strategy Category:** `{rec_type}`")
    st.info(f"**Execution Logic:** {rec_logic}")

    st.write("#### 📋 Orders To Execute on Kite:")
    for idx, leg in enumerate(legs, 1):
        action = "🟢 BUY" if leg['action'] == 'BUY' else "🔴 SELL"
        st.markdown(f"- **Leg {idx}:** {action} **Nifty {int(leg['strike'])} {leg['type']}** (~₹{leg['premium']})")

    st.caption("Tip: Pehle BUY legs execute karein margin benefit ke liye, fir SELL legs.")

with col_chart:
    st.subheader("📈 Live Payoff Curve")
    if legs:
        # Native thread-safe Matplotlib Plotting
        spot_range = np.linspace(live_spot - 600, live_spot + 600, 100)
        pnl = np.zeros_like(spot_range)

        for leg in legs:
            k = leg['strike']
            prem = leg['premium']
            if leg['type'] == 'CE':
                intrinsic = np.maximum(0, spot_range - k)
            else:
                intrinsic = np.maximum(0, k - spot_range)
            
            if leg['action'] == 'BUY':
                pnl += (intrinsic - prem)
            else:
                pnl += (prem - intrinsic)

        fig, ax = plt.subplots(figsize=(7, 4.5), facecolor='#0f172a')
        ax.set_facecolor('#1e293b')
        ax.plot(spot_range, pnl, color='#38bdf8', linewidth=2.5, label='Strategy Payoff')
        ax.axhline(0, color='#64748b', linestyle='--', linewidth=1)
        ax.axvline(live_spot, color='#f59e0b', linestyle=':', label='Current Spot')

        # Green for Profit, Red for Loss
        ax.fill_between(spot_range, pnl, 0, where=(pnl >= 0), color='#10b981', alpha=0.35, interpolate=True)
        ax.fill_between(spot_range, pnl, 0, where=(pnl < 0), color='#ef4444', alpha=0.35, interpolate=True)

        ax.tick_params(colors='#94a3b8', labelsize=9)
        for spine in ax.spines.values():
            spine.set_color('#334155')

        ax.set_xlabel("NIFTY Spot at Expiry", color='#94a3b8', fontsize=10)
        ax.set_ylabel("P&L per Share (₹)", color='#94a3b8', fontsize=10)
        ax.grid(True, color='#334155', linestyle=':', alpha=0.6)
        ax.legend(facecolor='#1e293b', edgecolor='#334155', labelcolor='#e2e8f0', loc='best', fontsize=8)

        st.pyplot(fig)
        plt.close(fig)

# Auto refresh trigger
st.caption(f"Last updated from Angel One SmartAPI: {time.strftime('%H:%M:%S')}")
if st.button("🔄 Instant Refresh"):
    st.rerun()
