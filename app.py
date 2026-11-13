import streamlit as st
import matplotlib.pyplot as plt
import json
import pandas as pd
from streamlit_autorefresh import st_autorefresh

from api_service import (
    get_angel_session, load_angel_master_data, get_comprehensive_indices,
    get_live_option_chain_oi, fetch_batch_ltps, send_telegram_alert
)
from strategy_engine import (
    load_saved_strategies, save_strategies_to_disk, get_ist_clock_status,
    get_kite_symbol, build_strategy_specs, compute_payoff_and_chart
)

st.set_page_config(page_title="Nifty Institutional Analytics Terminal", layout="wide", initial_sidebar_state="collapsed")

# --- LOAD EXTERNAL CSS ---
with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# --- SESSION & FLASH POPUP INIT ---
if "saved_strategies" not in st.session_state:
    st.session_state.saved_strategies = load_saved_strategies()

if "flash_msg" in st.session_state and st.session_state.flash_msg:
    st.toast(st.session_state.flash_msg)
    st.session_state.flash_msg = None

# --- CREDENTIALS & API INIT ---
try:
    smart_api = get_angel_session(
        st.secrets["API_KEY"], st.secrets["CLIENT_CODE"],
        st.secrets["PASSWORD"], st.secrets["TOTP_SECRET"]
    )
except Exception:
    st.error("⚠️ Angel One Credentials missing in Streamlit Secrets!")
    st.stop()

if not smart_api:
    st.error("❌ Angel One API se connect nahi ho paya.")
    st.stop()

TG_ACTIVE = bool(st.secrets.get("TELEGRAM_BOT_TOKEN") and st.secrets.get("TELEGRAM_CHAT_ID"))

# --- FETCH LIVE MARKET DATA ---
nfo_df, INDEX_TOKENS = load_angel_master_data()
market_data = get_comprehensive_indices(smart_api, INDEX_TOKENS)
live_spot = market_data["nifty"]["ltp"]
live_vix = market_data["vix"]
atm_strike = int(round(live_spot / 50.0) * 50)
ist_now, ist_time_str, entry_signal, entry_advice, sig_color = get_ist_clock_status()

today_date = ist_now.date()
valid_expiries = sorted([d for d in nfo_df["expiry_dt"].dropna().unique() if d >= today_date])
if not valid_expiries:
    st.stop()

top_expiries = valid_expiries[:4]
expiry_labels = [f"{d.strftime('%d-%b')} ({max((d - today_date).days, 1)}d)" for d in top_expiries]

# ==============================================================================
# FIXED TOP CONTAINER (SCROLL FREEZE ON TOP WITHOUT EXTRA GAP)
# ==============================================================================
active_count = len(st.session_state.saved_strategies)

# Render Fixed HTML Bar directly
st.markdown(f"""
<div class="fixed-top-wrapper">
    <div class="brand-header">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 1.2rem;">📊</span>
            <div>
                <div style="font-size: 0.95rem; font-weight: 800; color: #f8fafc; letter-spacing: 0.5px;">NIFTY INSTITUTIONAL QUANT TERMINAL</div>
                <div style="font-size: 0.65rem; color: #38bdf8;">Advanced Delta & OI-Synced Options Analytics & Live Tracker</div>
            </div>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
            <span style="font-size: 0.75rem; color: #94a3b8; background: #1e293b; padding: 2px 6px; border-radius: 4px; border: 1px solid #334155;">🕒 {ist_time_str} &nbsp;|&nbsp; Active: <b>{active_count}</b></span>
            <span style="background: #1e293b; border: 1px solid #334155; color: #10b981; font-size: 0.68rem; font-weight: 700; padding: 2px 6px; border-radius: 4px;">🟢 LIVE NFO API</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- TOP MARKET TICKER BAR (Controlled via CSS Classes) ---
t1, t2, t3 = st.columns(3)
for col, name, key in [(t1, "NIFTY 50", "nifty"), (t2, "BANKNIFTY", "banknifty"), (t3, "SENSEX", "sensex")]:
    with col:
        d = market_data[key]
        ltp = d['ltp']
        close = d['close'] if d['close'] > 0 else ltp
        
        diff = ltp - close
        pct = (diff / close) * 100 if close > 0 else 0.0
        
        # Select CSS class based on market movement
        css_class = "ticker-ltp-green" if diff >= 0 else "ticker-ltp-red"
        sign_str = "+" if diff >= 0 else ""
        
        st.markdown(f"""
        <div style="background-color: #111827; border: 1px solid #1f2937; border-radius: 6px; padding: 6px 8px; text-align: center; margin-bottom: 2px;">
            <div style="font-weight: 700; font-size: 0.85rem; color: #f8fafc;">
                {name}: <span class="{css_class}">₹{ltp:,.2f}</span> 
                <span class="ticker-change">{sign_str}{diff:,.2f} ({sign_str}{pct:.2f}%)</span>
            </div>
            <div style="font-size: 0.65rem; color: #94a3b8; margin-top: 2px;">O: {d['open']:,.1f} | H: {d['high']:,.1f} | L: {d['low']:,.1f} | C: {close:,.1f}</div>
        </div>
        """, unsafe_allow_html=True)
        
# --- COMMAND NAVIGATION & SYNC TOGGLE BAR ---
nav_col1, nav_col2 = st.columns([3, 1])
with nav_col1:
    nav_mode = st.radio("Workspace", ["⚡ Quant Terminal", "🛡️ Saved Live Tracker"], horizontal=True, label_visibility="collapsed", key="main_nav_mode")
with nav_col2:
    auto_refresh_on = st.toggle("Sync (10s)", value=True, key="top_sync_toggle")

if auto_refresh_on:
    st_autorefresh(interval=10 * 1000, key="terminal_fixed_sync_v10")

st.markdown("<hr style='margin: 4px 0 10px 0; border-color: #1f2937;'>", unsafe_allow_html=True)

# ==============================================================================
# WORKSPACE A: SAVED LIVE TRACKER
# ==============================================================================
if nav_mode == "🛡️ Saved Live Tracker":
    head_l, head_r = st.columns([3.5, 1.5])
    with head_l:
        st.markdown(f"### 🛡️ Live Trade Tracker & P&L Desk ({len(st.session_state.saved_strategies)} Active)")
        st.caption("📲 **Telegram Alerts: ACTIVE**" if TG_ACTIVE else "🔕 **Telegram Alerts: OFF**")
    with head_r:
        if TG_ACTIVE and st.button("🔔 Send Test Alert", key="test_tg_btn", use_container_width=True):
            ok = send_telegram_alert(f"✅ <b>Quant Terminal Connected!</b>\nNifty Spot: ₹{live_spot:,.2f}\nTime: {ist_time_str}")
            st.toast("✅ Telegram par Test Alert bhej diya gaya hai!" if ok else "❌ Telegram message fail hua.")

    if not st.session_state.saved_strategies:
        st.info("ℹ️ Abhi koi active trade track nahi ho raha hai. '⚡ Quant Terminal' par jakar apni strategy save karein.")
    else:
        all_tokens = [str(l["token"]) for s in st.session_state.saved_strategies for l in s.get("legs", []) if l.get("token")]
        saved_live_ltps = fetch_batch_ltps(smart_api, all_tokens)
        state_changed = False

        for idx, strat in enumerate(st.session_state.saved_strategies[:]):
            lot_qty = strat.get("lot_size", 65)
            running_pnl_pts, leg_html_rows, exit_lines = 0.0, "", []

            for l_idx, leg in enumerate(strat.get("legs", []), 1):
                entry_p = float(leg["premium"])
                curr_p = saved_live_ltps.get(str(leg.get("token", "")), entry_p)
                if curr_p <= 0.05:
                    curr_p = entry_p

                leg_pnl_pts = (entry_p - curr_p) if leg["action"] == "SELL" else (curr_p - entry_p)
                running_pnl_pts += leg_pnl_pts
                leg_pnl_rs = leg_pnl_pts * lot_qty

                b_col = "#10b981" if leg["action"] == "BUY" else "#ef4444"
                b_txt = "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
                pnl_col = "#10b981" if leg_pnl_rs >= 0 else "#ef4444"
                pnl_sign = "+" if leg_pnl_rs >= 0 else ""

                leg_html_rows += (
                    f"<div class='leg-row' style='border-left-color:{b_col}; margin-bottom:5px;'>"
                    f"<div><b>Leg {l_idx}:</b> {b_txt} <code>{leg['readable']}</code></div>"
                    f"<div style='font-size:0.83rem; color:#e2e8f0;'>Entry: <b>₹{entry_p:.2f}</b> &rarr; Live: <b>₹{curr_p:.2f}</b> &nbsp;|&nbsp; "
                    f"<span style='color:{pnl_col}; font-weight:700;'>{pnl_sign}₹{leg_pnl_rs:,.0f}</span></div></div>"
                )
                exit_lines.append(f"• {leg['action']} {leg['readable']}: ₹{entry_p:.2f} → ₹{curr_p:.2f} ({pnl_sign}₹{leg_pnl_rs:,.0f})")

            total_running_pnl = running_pnl_pts * lot_qty
            tot_col = "#10b981" if total_running_pnl >= 0 else "#ef4444"
            tot_sign = "+" if total_running_pnl >= 0 else ""
            price_drift = live_spot - strat['entry_spot']
            max_p, max_l = max(strat.get('max_profit', 1), 1), max(strat.get('max_loss', 1), 1)
            last_alert = strat.get("last_alert_state", "HOLD")

            if total_running_pnl >= 0.65 * max_p:
                status_banner, status_bg = "🟣 <b>STATUS: TARGET HIT (BOOK PROFIT)</b> — 65%+ Max Profit target achieved!", "#3b0764"
                if last_alert != "TARGET_HIT" and send_telegram_alert(f"🟣 <b>TARGET HIT!</b>\n<b>{strat['name']} ({strat['expiry']})</b>\nLive P&L: <b>+₹{total_running_pnl:,.0f}</b>"):
                    st.session_state.saved_strategies[idx]["last_alert_state"] = "TARGET_HIT"
                    state_changed = True
            elif total_running_pnl <= -0.50 * max_l or abs(price_drift) >= 160:
                status_banner, status_bg = "🔴 <b>STATUS: STOP-LOSS / EXIT ALERT</b> — Market range breach ya risk limit hit!", "#450a0a"
                if last_alert != "SL_HIT" and send_telegram_alert(f"🔴 <b>STOP-LOSS ALERT!</b>\n<b>{strat['name']} ({strat['expiry']})</b>\nLive P&L: <b>{tot_sign}₹{total_running_pnl:,.0f}</b>"):
                    st.session_state.saved_strategies[idx]["last_alert_state"] = "SL_HIT"
                    state_changed = True
            elif abs(price_drift) < 70:
                status_banner, status_bg = "🟢 <b>STATUS: TIKE RAHO (HOLD)</b> — Market safe corridor mein hai, Theta decay chal raha hai.", "#064e3b"
            else:
                status_banner, status_bg = f"🟡 <b>STATUS: MONITOR CLOSELY</b> — Spot Drift: {price_drift:+.1f} pts.", "#422006"

            st.markdown(f"""
            <div class="section-box" style="margin-bottom: 6px;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
                    <div style="color:#f8fafc; font-size:0.95rem;"><b>#{idx+1} • {strat['name']}</b> <span style="color:#38bdf8;">({strat['expiry']})</span> <span style="color:#94a3b8; font-size:0.75rem;">| Saved: {strat.get('time', '')}</span></div>
                    <div style="font-size:0.85rem; color:#e2e8f0;">Entry Spot: <b style="color:#38bdf8;">₹{strat['entry_spot']:,.2f}</b> &nbsp;|&nbsp; Live Spot: <b style="color:#f59e0b;">₹{live_spot:,.2f}</b> ({price_drift:+.1f})</div>
                </div>
                <div class="risk-strip" style="margin-top:8px;">
                    <div>Max Profit: <b style="color:#10b981;">₹{strat['max_profit']:,.0f}</b></div>
                    <div>Max Risk: <b style="color:#ef4444;">₹{strat['max_loss']:,.0f}</b></div>
                    <div>Lot Qty: <b>{lot_qty}</b></div>
                    <div style="font-size:0.92rem;">Running P&L: <b style="color:{tot_col};">{tot_sign}₹{total_running_pnl:,.0f}</b> ({running_pnl_pts:+.2f} pts)</div>
                </div>
                {leg_html_rows}
                <div style="background:{status_bg}; padding:7px 12px; border-radius:6px; font-size:0.82rem; margin-top:6px; color:#f8fafc;">{status_banner}</div>
            </div>
            """, unsafe_allow_html=True)

            act_col1, act_col2, act_col3 = st.columns([3.4, 1.3, 1.3])
            with act_col1:
                with st.expander(f"✏️ Edit Strikes & Entry Prices (#{idx+1})", expanded=False):
                    edit_cols = st.columns(len(strat.get("legs", [])))
                    updated_legs_data = []
                    for l_i, leg in enumerate(strat.get("legs", [])):
                        with edit_cols[l_i]:
                            st.markdown(f"**Leg {l_i+1}: {leg['action']} {leg['type']}**")
                            n_st = st.number_input("Strike", 15000, 35000, int(leg["strike"]), 50, key=f"ed_st_{idx}_{l_i}")
                            n_pr = st.number_input("Entry (₹)", 0.05, 5000.0, float(leg["premium"]), 0.05, format="%.2f", key=f"ed_pr_{idx}_{l_i}")
                            updated_legs_data.append((n_st, n_pr))

                    if st.button("💾 Save Changes", key=f"save_ed_{idx}", use_container_width=True):
                        exp_str = strat["expiry"]
                        for l_i, (n_strike, n_prem) in enumerate(updated_legs_data):
                            old_leg = st.session_state.saved_strategies[idx]["legs"][l_i]
                            o_type = old_leg["type"]
                            matched = nfo_df[(nfo_df["strike_int"] == int(n_strike)) & (nfo_df["opt_type"] == o_type) & (nfo_df["expiry_dt"].apply(lambda d: d.strftime("%d-%b") if pd.notnull(d) else "") == exp_str)]
                            if not matched.empty:
                                old_leg["token"] = str(matched.iloc[0]["token"])
                            old_leg["strike"], old_leg["premium"], old_leg["readable"] = int(n_strike), float(n_prem), f"NIFTY {exp_str} {int(n_strike)} {o_type}"

                        st.session_state.saved_strategies[idx]["last_alert_state"] = "HOLD"
                        save_strategies_to_disk(st.session_state.saved_strategies)
                        legs_txt = "\n".join([f"• {l['action']} {l['readable']} @ ₹{l['premium']:.2f}" for l in st.session_state.saved_strategies[idx]["legs"]])
                        send_telegram_alert(f"✏️ <b>Strategy Updated!</b>\n<b>#{idx+1} • {strat['name']} ({exp_str})</b>\n{legs_txt}\n⏰ {ist_time_str}")
                        st.session_state.flash_msg = "✅ Updated Strikes Saved & Sent to Telegram!"
                        st.rerun()

            with act_col2:
                if st.button("🚪 Exit Trade", key=f"exit_st_{idx}", use_container_width=True):
                    badge = "🟢 PROFIT BOOKED" if total_running_pnl >= 0 else "🔴 LOSS BOOKED"
                    send_telegram_alert(f"🚪 <b>TRADE EXITED — {badge}</b>\n<b>{strat['name']} ({strat['expiry']})</b>\nNet: <b>{running_pnl_pts:+.2f} pts</b> | P&L: <b>{tot_sign}₹{total_running_pnl:,.0f}</b>\n\n" + "\n".join(exit_lines))
                    st.session_state.saved_strategies.pop(idx)
                    save_strategies_to_disk(st.session_state.saved_strategies)
                    st.session_state.flash_msg = f"🚪 Trade Exited ({tot_sign}₹{total_running_pnl:,.0f}) & Report Sent!"
                    st.rerun()

            with act_col3:
                if st.button("🗑️ Delete", key=f"del_st_{idx}", use_container_width=True):
                    st.session_state.saved_strategies.pop(idx)
                    save_strategies_to_disk(st.session_state.saved_strategies)
                    st.session_state.flash_msg = "🗑️ Strategy Deleted!"
                    st.rerun()

            st.markdown("<hr style='margin: 10px 0 14px 0; border-color: #1f2937;'>", unsafe_allow_html=True)

        if state_changed:
            save_strategies_to_disk(st.session_state.saved_strategies)

# ==============================================================================
# WORKSPACE B: QUANT TERMINAL
# ==============================================================================
else:
    ctrl_l, ctrl_r = st.columns([2.2, 1.5])
    with ctrl_l:
        selected_label = st.radio("Expiry", expiry_labels, horizontal=True, label_visibility="collapsed")
    with ctrl_r:
        strat_mode_choice = st.selectbox("Strategy Mode", [
            "🤖 AI Auto-Select (OI-Synced)", "🦅 Short Iron Condor (Rangebound)",
            "🦋 Iron Butterfly (High Theta Pinning)", "🐻 Bear Call Spread (Resistance Defense)",
            "🐂 Bull Put Spread (Support Defense)"
        ], label_visibility="collapsed")

    chosen_exp_date = top_expiries[expiry_labels.index(selected_label)]
    dte_days = max((chosen_exp_date - today_date).days, 1)
    display_exp = chosen_exp_date.strftime("%d-%b")

    oi_data = get_live_option_chain_oi(smart_api, nfo_df, chosen_exp_date.isoformat(), atm_strike)
    live_pcr, live_max_pain, call_wall, put_wall = oi_data["pcr"], oi_data["max_pain"], oi_data["call_wall"], oi_data["put_wall"]
    pcr_sentiment = "Bullish" if live_pcr >= 1.15 else ("Bearish" if live_pcr <= 0.75 else "Neutral / Range")

    strat_name, strat_reason, leg_specs = build_strategy_specs(strat_mode_choice, live_spot, atm_strike, live_vix, oi_data)

    exp_subset = nfo_df[nfo_df["expiry_dt"] == chosen_exp_date]
    LOT_SIZE = int(exp_subset["lotsize_int"].iloc[0]) if (not exp_subset.empty and int(exp_subset["lotsize_int"].iloc[0]) > 0) else 65

    tokens_to_fetch = []
    for spec in leg_specs:
        row = exp_subset[(exp_subset["strike_int"] == spec["strike"]) & (exp_subset["opt_type"] == spec["type"])]
        spec["token"] = str(row.iloc[0]["token"]) if not row.empty else None
        if spec["token"]:
            tokens_to_fetch.append(spec["token"])

    live_ltp_map = dict(oi_data.get("ltp_dict", {}))
    missing = [t for t in tokens_to_fetch if t not in live_ltp_map or live_ltp_map[t] <= 0]
    if missing:
        live_ltp_map.update(fetch_batch_ltps(smart_api, missing))

    display_legs = []
    for spec in leg_specs:
        ltp_val = live_ltp_map.get(spec["token"], 0.0)
        if ltp_val <= 0.5:
            ltp_val = round(130.0 * (1.0 if dte_days <= 7 else 1.3), 2)
        display_legs.append({
            "type": spec["type"], "action": spec["action"], "strike": spec["strike"],
            "token": spec["token"], "premium": ltp_val,
            "readable": f"NIFTY {display_exp} {spec['strike']} {spec['type']}",
            "kite_sym": get_kite_symbol(chosen_exp_date, spec["strike"], spec["type"], valid_expiries),
            "note": spec["note"]
        })

    metrics = compute_payoff_and_chart(display_legs, live_spot, live_vix, dte_days, LOT_SIZE, display_exp)

    # --- ZONE 3: INSTITUTIONAL MARKET PULSE ---
    oi_badge = "🟢" if oi_data["is_live"] else "🟡"
    put_oi_str = f"OI: {oi_data['put_wall_oi']:,}" if oi_data["put_wall_oi"] > 0 else "Put Base"
    call_oi_str = f"OI: {oi_data['call_wall_oi']:,}" if oi_data["call_wall_oi"] > 0 else "Call Wall"

    st.markdown(f"""
    <div class="analytics-grid">
        <div class="card"><div class="card-label">India VIX</div><div class="card-val" style="color:#f59e0b !important;">{live_vix:.2f}</div><div class="card-sub">Volatility</div></div>
        <div class="card"><div class="card-label">Live PCR ({oi_badge})</div><div class="card-val">{live_pcr:.2f}</div><div class="card-sub">{pcr_sentiment}</div></div>
        <div class="card"><div class="card-label">Max Pain</div><div class="card-val">₹{live_max_pain}</div><div class="card-sub">Expiry Magnet</div></div>
        <div class="card"><div class="card-label">Put Support</div><div class="card-val">₹{put_wall}</div><div class="card-sub">{put_oi_str}</div></div>
        <div class="card"><div class="card-label">Call Resistance</div><div class="card-val">₹{call_wall}</div><div class="card-sub">{call_oi_str}</div></div>
    </div>
    <div class="section-box" style="background:#1e293b !important; border-color:#334155 !important; padding:10px 14px;">
        <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:4px; color:#f8fafc !important;">
            <div>🤖 <b style="color:#f8fafc !important;">Selected Setup: <span style="color:#38bdf8 !important;">{strat_name} ({display_exp})</span></b></div>
            <div>⏰ <b style="color:#f8fafc !important;">Window: <span style="color:{sig_color} !important;">{entry_signal}</span></b></div>
        </div>
        <div style="color:#e2e8f0 !important; font-size:0.82rem;">💡 {strat_reason} &nbsp;<span style="color:#94a3b8 !important;">({entry_advice})</span></div>
    </div>
    """, unsafe_allow_html=True)

    # --- ZONE 4: EXECUTION & PAYOFF WORKSPACE ---
    col_left, col_right = st.columns([1.15, 1.15])
    with col_left:
        st.markdown(f"""
        <div class="risk-strip">
            <div>Win Prob: <b style="color:#38bdf8;">{metrics['pop']:.1f}%</b></div>
            <div>Max Profit: <b style="color:#10b981;">₹{metrics['max_profit']:,.0f}</b> (+{metrics['net_credit']:.1f})</div>
            <div>Max Risk: <b style="color:#ef4444;">₹{metrics['max_loss']:,.0f}</b> (1:{1/metrics['rr']:.2f})</div>
            <div>Lot: <b>{LOT_SIZE}</b></div>
        </div>
        """, unsafe_allow_html=True)

        for idx, leg in enumerate(display_legs, 1):
            b_col = "#10b981" if leg["action"] == "BUY" else "#ef4444"
            b_txt = "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
            st.markdown(
                f"<div class='leg-row' style='border-left-color:{b_col};'>"
                f"<div style='color:#f8fafc !important;'><b style='color:#f8fafc !important;'>Leg {idx}:</b> {b_txt} <code>{leg['readable']}</code><br/><span style='color:#94a3b8 !important;font-size:0.74rem'>{leg['note']}</span></div>"
                f"<div style='font-weight:700;color:#f8fafc !important; font-size:0.95rem;'>₹{leg['premium']:.2f}</div></div>",
                unsafe_allow_html=True
            )

        btn_c1, btn_c2 = st.columns([1.2, 1.0])
        with btn_c1:
            if st.button("💾 Save Strategy to Live Tracker", use_container_width=True):
                st.session_state.saved_strategies.append({
                    "name": strat_name, "expiry": display_exp, "lot_size": LOT_SIZE,
                    "legs": display_legs, "max_profit": float(metrics["max_profit"]),
                    "max_loss": float(metrics["max_loss"]), "entry_spot": float(live_spot),
                    "time": ist_time_str, "last_alert_state": "HOLD"
                })
                save_strategies_to_disk(st.session_state.saved_strategies)
                legs_txt = "\n".join([f"• {l['action']} {l['readable']} @ ₹{l['premium']:.2f}" for l in display_legs])
                send_telegram_alert(f"💾 <b>New Strategy Saved!</b>\n<b>{strat_name} ({display_exp})</b>\nSpot: ₹{live_spot:,.2f}\n{legs_txt}")
                st.session_state.flash_msg = "✅ Strategy Saved to Live Tracker!"
                st.rerun()

        with btn_c2:
            json_legs = sorted(display_legs, key=lambda x: 0 if x["action"] == "BUY" else 1)
            kite_basket = [{"variety": "regular", "tradingsymbol": l["kite_sym"], "exchange": "NFO", "transaction_type": l["action"], "order_type": "MARKET", "quantity": LOT_SIZE, "product": "NRML"} for l in json_legs]
            with st.expander("📋 Zerodha JSON", expanded=False):
                st.code(json.dumps(kite_basket, indent=2), language="json")

    with col_right:
        st.pyplot(metrics["fig"])
        plt.close(metrics["fig"])
