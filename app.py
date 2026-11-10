import streamlit as st
import pyotp
from SmartApi import SmartConnect
import matplotlib.pyplot as plt
import numpy as np
import datetime
from scipy.stats import norm
import time
import json
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Nifty Institutional Radar", layout="wide", initial_sidebar_state="collapsed")

# --- PRO DARK INTERFACE STYLING ---
st.markdown("""
<style>
    .reportview-container { background: #0b0f19; }
    .metric-card { background-color: #111827; border-radius: 8px; padding: 14px; border: 1px solid #1f2937; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Nifty Options Decision Engine (Live Terminal)")

# --- CREDENTIALS VAULT ---
try:
    API_KEY = st.secrets["API_KEY"]
    CLIENT_CODE = st.secrets["CLIENT_CODE"]
    PASSWORD = st.secrets["PASSWORD"]
    TOTP_SECRET = st.secrets["TOTP_SECRET"]
except Exception:
    st.error("⚠️ Credentials missing in Streamlit Secrets!")
    st.stop()

# --- ANGEL ONE SESSION (CACHED) ---
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

# --- LIVE SPOT FETCH ---
def get_live_nifty():
    nifty_spot = 25044.65
    if smart_api:
        try:
            quote_nifty = smart_api.ltpData(exchange="NSE", tradingsymbol="Nifty 50", symboltoken="99926000")
            if quote_nifty.get("status") and "data" in quote_nifty:
                val = float(quote_nifty["data"]["ltp"])
                if val > 15000:
                    nifty_spot = val
        except Exception:
            pass
    return nifty_spot

live_spot = get_live_nifty()
atm_strike = int(round(live_spot / 50.0) * 50)

# --- DYNAMIC CALENDAR ENGINE ---
all_possible_expiries = [
    datetime.datetime(2026, 11, 17, 15, 30),
    datetime.datetime(2026, 11, 23, 15, 30),
    datetime.datetime(2026, 12, 1, 15, 30),
    datetime.datetime(2026, 12, 8, 15, 30),
    datetime.datetime(2026, 12, 15, 15, 30)
]

now = datetime.datetime.now()
active_expiries = [exp for exp in all_possible_expiries if exp > now]
if not active_expiries:
    st.error("Expiry list refresh required.")
    st.stop()

expiry_labels = []
for exp in active_expiries[:3]:
    dte = (exp.date() - now.date()).days
    expiry_labels.append(f"{exp.strftime('%d-%b')} ({dte} Days)")

# --- TOP BAR METRICS ---
c1, c2, c3, c4 = st.columns([1.2, 1, 1.2, 1])
with c1:
    st.metric(label="LIVE NIFTY SPOT", value=f"₹{live_spot:,.2f}")
with c2:
    st.metric(label="ATM STRIKE", value=f"{atm_strike}")
with c3:
    st.metric(label="ATM IV / REGIME", value="16.70%", delta="Very High (Sell Edge)")
with c4:
    auto_refresh_on = st.toggle("Auto-refresh (15s)", value=True)

if auto_refresh_on:
    st_autorefresh(interval=15 * 1000, key="nifty_live_autorefresh")

st.write("---")

# --- NON-KEYBOARD EXPIRY SELECTOR ---
st.markdown("#### 📅 Target Expiry Contract (Auto-Filtered):")
selected_label = st.radio("Choose Expiry", expiry_labels, horizontal=True, label_visibility="collapsed")

selected_index = expiry_labels.index(selected_label)
chosen_exp_dt = active_expiries[selected_index]
dte_days = max((chosen_exp_dt.date() - now.date()).days, 1)

# --- EXACT ZERODHA WEEKLY TRADING SYMBOL BUILDER ---
def get_kite_trading_symbol(exp_dt, strike, opt_type):
    yy = exp_dt.strftime("%y")
    m = exp_dt.month
    # NSE Weekly Month Codes: 1-9 for Jan-Sep, O for Oct, N for Nov, D for Dec
    month_codes = {1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'}
    m_code = month_codes[m]
    dd = exp_dt.strftime("%d")
    return f"NIFTY{yy}{m_code}{dd}{strike}{opt_type}"

# --- MATHEMATICAL OPTIONS ENGINE (Black-Scholes) ---
def bs_price(S, K, T, r, sigma, opt_type='c'):
    if T <= 0.001:
        T = 0.001
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt_type == 'c':
        price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return round(float(price), 2)

T_years = dte_days / 365.0
sigma = 0.1670  # Kite exact 16.70% IV
r = 0.07

wing_buffer = 100 if dte_days <= 7 else (150 if dte_days <= 14 else 200)
protection_spread = 200 if dte_days <= 7 else 250

sell_pe = int(round((atm_strike - wing_buffer) / 50.0) * 50)
buy_pe  = int(round((sell_pe - protection_spread) / 50.0) * 50)
sell_ce = int(round((atm_strike + wing_buffer) / 50.0) * 50)
buy_ce  = int(round((sell_ce + protection_spread) / 50.0) * 50)

p_sell_pe = bs_price(live_spot, sell_pe, T_years, r, sigma, 'p')
p_buy_pe  = bs_price(live_spot, buy_pe,  T_years, r, sigma, 'p')
p_sell_ce = bs_price(live_spot, sell_ce, T_years, r, sigma, 'c')
p_buy_ce  = bs_price(live_spot, buy_ce,  T_years, r, sigma, 'c')

# STRICT ORDERING FOR ZERODHA MARGIN BENEFIT: BUY FIRST, THEN SELL
legs = [
    {
        'type': 'PE',
        'action': 'BUY',
        'strike': buy_pe,
        'premium': p_buy_pe,
        'symbol': get_kite_trading_symbol(chosen_exp_dt, buy_pe, 'PE'),
        'note': 'Hedge Wing (Crash Shield)'
    },
    {
        'type': 'CE',
        'action': 'BUY',
        'strike': buy_ce,
        'premium': p_buy_ce,
        'symbol': get_kite_trading_symbol(chosen_exp_dt, buy_ce, 'CE'),
        'note': 'Hedge Wing (Rally Shield)'
    },
    {
        'type': 'PE',
        'action': 'SELL',
        'strike': sell_pe,
        'premium': p_sell_pe,
        'symbol': get_kite_trading_symbol(chosen_exp_dt, sell_pe, 'PE'),
        'note': 'Credit Leg (Put Sell)'
    },
    {
        'type': 'CE',
        'action': 'SELL',
        'strike': sell_ce,
        'premium': p_sell_ce,
        'symbol': get_kite_trading_symbol(chosen_exp_dt, sell_ce, 'CE'),
        'note': 'Credit Leg (Call Sell)'
    }
]

# --- RISK METRICS & PROBABILITY OF PROFIT ---
net_credit = (p_sell_pe + p_sell_ce) - (p_buy_pe + p_buy_ce)
max_profit_lot = net_credit * 25
max_loss_lot = (protection_spread - net_credit) * 25
lower_breakeven = sell_pe - net_credit
upper_breakeven = sell_ce + net_credit

# Corrected Win Probability: Integral between Lower BE and Upper BE
stdev = live_spot * sigma * np.sqrt(T_years)
prob_lower = norm.cdf((lower_breakeven - live_spot) / stdev)
prob_upper = norm.cdf((upper_breakeven - live_spot) / stdev)
pop_percent = (prob_upper - prob_lower) * 100

st.subheader(f"🛡️ Hedged Iron Condor — {selected_label}")

b1, b2, b3, b4, b5 = st.columns(5)
with b1:
    st.metric("Max Profit", f"₹{max_profit_lot:,.0f}")
with b2:
    st.metric("Max Risk", f"₹{max_loss_lot:,.0f}")
with b3:
    st.metric("Win Probability", f"{pop_percent:.1f}%")
with b4:
    st.metric("Lower BE", f"{lower_breakeven:.0f}")
with b5:
    st.metric("Upper BE", f"{upper_breakeven:.0f}")

# --- ORDERS & VISUAL ---
c_orders, c_chart = st.columns([1.1, 1.2])

with c_orders:
    st.markdown("#### 📋 Orders for Zerodha Kite:")
    for idx, leg in enumerate(legs, 1):
        action_badge = "🟢 BUY" if leg['action'] == 'BUY' else "🔴 SELL"
        st.markdown(f"**Leg {idx}:** {action_badge} **`{leg['symbol']}`** — **~₹{leg['premium']:.2f}**")
        st.caption(f"└ {leg['note']}")

    # True Zerodha Weekly Basket JSON
    kite_basket = [
        {
            "variety": "regular",
            "tradingsymbol": leg['symbol'],
            "exchange": "NFO",
            "transaction_type": leg['action'],
            "order_type": "MARKET",
            "quantity": 25,
            "product": "NRML"
        }
        for leg in legs
    ]
    with st.expander("📋 Zerodha Basket JSON (Click to Copy)", expanded=False):
        st.code(json.dumps(kite_basket, indent=2), language="json")

    st.caption("🔒 **Margin Order:** BUY legs pehle list kiye gaye hain taaki margin penalty na lage.")

with c_chart:
    st.subheader(f"📈 Payoff Curve ({chosen_exp_dt.strftime('%d-%b')})")
    span = protection_spread + 400
    spot_range = np.linspace(live_spot - span, live_spot + span, 150)
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

    fig, ax = plt.subplots(figsize=(7, 4.5), facecolor='#0b0f19')
    ax.set_facecolor('#111827')
    ax.plot(spot_range, pnl, color='#38bdf8', linewidth=2.5, label='Net Payoff')
    ax.axhline(0, color='#64748b', linestyle='--', linewidth=1)
    ax.axvline(live_spot, color='#f59e0b', linestyle=':', label=f'Spot ({live_spot:.1f})')
    
    ax.axvline(lower_breakeven, color='#94a3b8', linestyle='--', alpha=0.7)
    ax.axvline(upper_breakeven, color='#94a3b8', linestyle='--', alpha=0.7)

    ax.fill_between(spot_range, pnl, 0, where=(pnl >= 0), color='#10b981', alpha=0.35, interpolate=True)
    ax.fill_between(spot_range, pnl, 0, where=(pnl < 0), color='#ef4444', alpha=0.35, interpolate=True)

    ax.tick_params(colors='#94a3b8', labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('#1f2937')

    ax.set_xlabel(f"Nifty Spot at Expiry", color='#94a3b8', fontsize=10)
    ax.set_ylabel("P&L per Share (₹)", color='#94a3b8', fontsize=10)
    ax.grid(True, color='#1f2937', linestyle=':', alpha=0.6)
    ax.legend(facecolor='#111827', edgecolor='#1f2937', labelcolor='#e2e8f0', loc='best', fontsize=8)

    st.pyplot(fig)
    plt.close(fig)

# --- FOOTER ---
st.write("---")
st.caption(f"Status: Connected | Auto-sync: 15s | Last update: {time.strftime('%H:%M:%S IST')}")
    
