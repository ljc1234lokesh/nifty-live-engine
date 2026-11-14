import streamlit as st
from streamlit_autorefresh import st_autorefresh
import datetime
import os

from api_service import (
    send_telegram_alert,
    get_angel_session,
    load_angel_master_data,
    get_comprehensive_indices,
    get_live_option_chain_oi,
    fetch_batch_ltps
)
from strategy_engine import (
    load_saved_strategies,
    save_strategies_to_disk,
    get_ist_clock_status,
    get_kite_symbol,
    build_strategy_specs,
    compute_payoff_and_chart
)

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="NIFTY Institutional Quant Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- LOAD EXTERNAL BASE CSS ---
if os.path.exists("style.css"):
    with open("style.css") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "saved_strategies" not in st.session_state:
    st.session_state.saved_strategies = load_saved_strategies()
if "alerted_ids" not in st.session_state:
    st.session_state.alerted_ids = set()

# --- API AUTHENTICATION & MASTER DATA ---
API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_CODE = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

smart_api = get_angel_session(API_KEY, CLIENT_CODE, PASSWORD, TOTP_SECRET)
nfo_df, idx_tokens = load_angel_master_data()
market_data = get_comprehensive_indices(smart_api, idx_tokens)

live_spot = market_data["nifty"]["ltp"]
live_vix = market_data["vix"]
atm_strike = int(round(live_spot / 50.0) * 50)

ist_now, ist_time_str, market_badge, timing_advice, badge_color = get_ist_clock_status()
active_count = len(st.session_state.saved_strategies)
api_status_badge = "🟢 LIVE NFO API" if smart_api else "🟡 SIMULATED MODE"
api_badge_color = "#10b981" if smart_api else "#f59e0b"

# ==============================================================================
# FIXED TOP COMMAND HEADER (LOCKED TO VIEWPORT TOP)
# ==============================================================================
with st.container():
    st.markdown('<div class="sticky-header-target"></div>', unsafe_allow_html=True)
    
    # --- COMPACT TOP HEADER TITLE ---
    st.markdown(
        f'<div style="background-color:#111827; border:1px solid #1f2937; border-radius:6px; padding:6px 12px; margin-bottom:4px;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px;">'
        f'<div>'
        f'<div style="font-size:1rem; font-weight:800; color:#f8fafc;">📊 NIFTY INSTITUTIONAL QUANT TERMINAL</div>'
        f'<div style="font-size:0.68rem; color:#38bdf8;">Advanced Delta & OI-Synced Options Analytics & Live Tracker</div>'
        f'</div>'
        f'<div style="display:flex; gap:6px; align-items:center;">'
        f'<span style="background:#1e293b; color:#e2e8f0; padding:2px 6px; border-radius:4px; font-size:0.7rem; font-weight:600;">🕒 {ist_time_str} | Active: {active_count}</span>'
        f'<span style="background:#1e293b; color:{api_badge_color}; padding:2px 6px; border-radius:4px; font-size:0.7rem; font-weight:600;">{api_status_badge}</span>'
        f'</div></div></div>',
        unsafe_allow_html=True
    )

    # --- COMPACT TOP MARKET TICKER BAR ---
    ticker_html = (
        '<style>'
        '.ticker-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 4px; } '
        '@media (max-width: 768px) { .ticker-grid { grid-template-columns: repeat(2, 1fr); } } '
        '.ticker-box { background-color: #111827; border: 1px solid #1f2937; border-radius: 4px; padding: 4px 6px; text-align: center; }'
        '</style>'
        '<div class="ticker-grid">'
    )
    for name, key in [("NIFTY 50", "nifty"), ("BANKNIFTY", "banknifty"), ("SENSEX", "sensex")]:
        d = market_data[key]
        ltp = d["ltp"]
        close = d["close"] if d["close"] > 0 else ltp
        diff = ltp - close
        pct = (diff / close) * 100 if close > 0 else 0.0
        css_color = "#34d399" if diff >= 0 else "#f87171"
        sign_str = "+" if diff >= 0 else ""
        
        ticker_html += (
            f'<div class="ticker-box">'
            f'<div style="font-weight: 700; font-size: 0.8rem; color: #f8fafc;">'
            f'{name}: <span style="color: {css_color}; font-weight: 700;">₹{ltp:,.2f}</span> '
            f'<span style="color: #94a3b8; font-size: 0.75rem;">{sign_str}{diff:,.2f} ({sign_str}{pct:.2f}%)</span>'
            f'</div>'
            f'<div style="font-size: 0.6rem; color: #94a3b8; margin-top: 1px;">O: {d["open"]:,.1f} | H: {d["high"]:,.1f} | L: {d["low"]:,.1f} | C: {close:,.1f}</div>'
            f'</div>'
        )
        
    ticker_html += (
        f'<div class="ticker-box" style="display: flex; flex-direction: column; justify-content: center;">'
        f'<div style="font-weight: 700; font-size: 0.8rem; color: #f8fafc;">'
        f'INDIA VIX: <span style="color: #38bdf8; font-weight: 800;">{live_vix:.2f}</span>'
        f'</div></div></div>'
    )
    st.markdown(ticker_html, unsafe_allow_html=True)

    # --- COMMAND NAVIGATION & 7s SYNC TOGGLE BAR ---
    nav_col1, nav_col2 = st.columns([3, 1])
    with nav_col1:
        nav_mode = st.radio(
            "Workspace",
            ["⚡ Quant Terminal", "🛡️ Saved Live Tracker"],
            horizontal=True,
            label_visibility="collapsed",
            key="main_nav_mode"
        )
    with nav_col2:
        auto_refresh_on = st.toggle("Sync (7s)", value=True, key="top_sync_toggle")

if auto_refresh_on:
    st_autorefresh(interval=7 * 1000, key="terminal_fixed_sync_v10")

# ==============================================================================
# WORKSPACE 1: QUANT TERMINAL (STRATEGY BUILDER & ANALYTICS)
# ==============================================================================
if "Quant Terminal" in nav_mode:
    today_dt = ist_now.date()
    valid_exps = sorted([d for d in nfo_df["expiry_dt"].dropna().unique() if d >= today_dt])[:4]
    if not valid_exps:
        valid_exps = [today_dt + datetime.timedelta(days=7)]

    exp_labels = {d: f"{d.strftime('%d-%b')} ({(d - today_dt).days}d)" for d in valid_exps}
    
    opt_c1, opt_c2 = st.columns([1.5, 1])
    with opt_c1:
        sel_exp_label = st.radio(
            "Expiry Selection",
            list(exp_labels.values()),
            horizontal=True,
            label_visibility="collapsed",
            key="exp_selector"
        )
    with opt_c2:
        strat_mode_choice = st.selectbox(
            "Strategy Engine",
            [
                "🤖 AI Auto-Select (OI-Synced)",
                "🦅 Short Iron Condor (Range Bound)",
                "🦋 Short Iron Butterfly (ATM Pinning)",
                "🐻 Bear Call Credit Spread (Resistance)",
                "🐂 Bull Put Credit Spread (Support)"
            ],
            label_visibility="collapsed",
            key="strat_mode_select"
        )

    selected_exp_dt = [d for d, lbl in exp_labels.items() if lbl == sel_exp_label][0]
    dte_days = max((selected_exp_dt - today_dt).days, 1)
    display_exp = selected_exp_dt.strftime("%d-%b")

    oi_data = get_live_option_chain_oi(smart_api, nfo_df, selected_exp_dt.isoformat(), atm_strike)
    live_pcr = oi_data["pcr"]
    live_max_pain = oi_data["max_pain"]
    call_wall = oi_data["call_wall"]
    put_wall = oi_data["put_wall"]

    pcr_sentiment = "Bullish Support" if live_pcr >= 1.15 else ("Bearish Pressure" if live_pcr <= 0.78 else "Neutral / Range")
    pcr_color = "#10b981" if live_pcr >= 1.0 else "#f59e0b"

    # --- 4 COMPACT INSTITUTIONAL METRIC CARDS ---
    metrics_html = (
        '<style>'
        '.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 4px; } '
        '@media (max-width: 768px) { .metrics-grid { grid-template-columns: repeat(2, 1fr); } } '
        '.metric-box { background-color: #111827; border: 1px solid #1f2937; border-radius: 6px; padding: 6px 10px; }'
        '</style>'
        '<div class="metrics-grid">'
        
        f'<div class="metric-box">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#94a3b8; letter-spacing:0.5px;">LIVE PCR (🟢)</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin:1px 0;">{live_pcr:.2f}</div>'
        f'<div style="font-size:0.68rem; color:{pcr_color}; font-weight:600;">{pcr_sentiment}</div>'
        f'</div>'
        
        f'<div class="metric-box">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#94a3b8; letter-spacing:0.5px;">MAX PAIN</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin:1px 0;">₹{live_max_pain}</div>'
        f'<div style="font-size:0.68rem; color:#a855f7; font-weight:600;">Expiry Magnet</div>'
        f'</div>'
        
        f'<div class="metric-box">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#94a3b8; letter-spacing:0.5px;">PUT SUPPORT</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin:1px 0;">₹{put_wall}</div>'
        f'<div style="font-size:0.68rem; color:#10b981; font-weight:600;">OI: {oi_data["put_wall_oi"]:,}</div>'
        f'</div>'
        
        f'<div class="metric-box">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#94a3b8; letter-spacing:0.5px;">CALL RESISTANCE</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:#f8fafc; margin:1px 0;">₹{call_wall}</div>'
        f'<div style="font-size:0.68rem; color:#ef4444; font-weight:600;">OI: {oi_data["call_wall_oi"]:,}</div>'
        f'</div>'
        '</div>'
    )
    st.markdown(metrics_html, unsafe_allow_html=True)

    # --- COMPACT MARKET TIMING BANNER ---
    st.markdown(
        f'<div style="background-color:#111827; border-left:4px solid {badge_color}; border:1px solid #1f2937; border-radius:4px; padding:4px 10px; margin:2px 0 6px 0;">'
        f'<span style="font-weight:800; font-size:0.75rem; color:{badge_color};">{market_badge}</span>'
        f'<span style="font-size:0.72rem; color:#94a3b8; margin-left:8px;">— {timing_advice}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    # --- STRATEGY GENERATION ---
    strat_title, strat_desc, raw_legs = build_strategy_specs(strat_mode_choice, live_spot, atm_strike, live_vix, oi_data)
    exp_nfo = nfo_df[nfo_df["expiry_dt"] == selected_exp_dt]
    lot_size = int(exp_nfo["lotsize_int"].iloc[0]) if not exp_nfo.empty else 65

    leg_tokens = []
    leg_token_map = {}
    for idx, lg in enumerate(raw_legs):
        match_row = exp_nfo[(exp_nfo["strike_int"] == lg["strike"]) & (exp_nfo["opt_type"] == lg["type"])]
        if not match_row.empty:
            tok = str(match_row["token"].iloc[0])
            leg_tokens.append(tok)
            leg_token_map[idx] = tok

    live_ltps = fetch_batch_ltps(smart_api, leg_tokens)
    display_legs = []
    for idx, lg in enumerate(raw_legs):
        tok = leg_token_map.get(idx, "")
        prem = live_ltps.get(tok, 0.0)
        if prem <= 0:
            dist = abs(live_spot - lg["strike"])
            prem = round(max(12.0, 165.0 * (0.994 ** dist)), 2)
        kite_sym = get_kite_symbol(selected_exp_dt, lg["strike"], lg["type"], valid_exps)
        display_legs.append({
            "type": lg["type"],
            "action": lg["action"],
            "strike": lg["strike"],
            "premium": prem,
            "note": lg["note"],
            "token": tok,
            "symbol": kite_sym
        })

    payoff_res = compute_payoff_and_chart(display_legs, live_spot, live_vix, dte_days, lot_size, display_exp)

    # --- RESPONSIVE SIDE-BY-SIDE LAYOUT (Legs Left, Graph Right) ---
    col_legs, col_chart = st.columns([1, 1.3], gap="medium")
    
    with col_legs:
        st.markdown(
            f'<div style="background-color:#111827; border:1px solid #1f2937; border-radius:6px; padding:10px; margin-bottom:6px;">'
            f'<div style="font-size:0.95rem; font-weight:800; color:#38bdf8;">🎯 {strat_title}</div>'
            f'<div style="font-size:0.72rem; color:#94a3b8; margin-top:1px;">{strat_desc}</div>'
            f'<div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:6px; font-size:0.75rem; font-weight:700;">'
            f'<span style="color:#10b981;">Max Profit: ₹{payoff_res["max_profit"]:,.0f}</span>'
            f'<span style="color:#ef4444;">Max Risk: ₹{payoff_res["max_loss"]:,.0f}</span>'
            f'<span style="color:#a855f7;">Win Prob: {payoff_res["pop"]:.1f}%</span>'
            f'<span style="color:#f59e0b;">Lot: {lot_size}</span>'
            f'</div></div>',
            unsafe_allow_html=True
        )

        for i, lg in enumerate(display_legs, 1):
            act_col = "#10b981" if lg["action"] == "BUY" else "#ef4444"
            st.markdown(
                f'<div style="background-color:#111827; border-left:4px solid {act_col}; border:1px solid #1f2937; border-radius:4px; padding:6px 10px; margin-bottom:4px;">'
                f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">'
                f'<div>'
                f'<span style="font-weight:800; font-size:0.8rem; color:{act_col};">Leg {i}: {lg["action"]}</span> '
                f'<span style="font-weight:700; font-size:0.8rem; color:#f8fafc; margin-left:4px;">NIFTY {display_exp} {lg["strike"]} {lg["type"]}</span> '
                f'<span style="font-size:0.65rem; color:#94a3b8; margin-left:6px;">({lg["note"]})</span>'
                f'</div>'
                f'<div style="font-weight:800; font-size:0.85rem; color:#f8fafc;">LTP: ₹{lg["premium"]:.2f}</div>'
                f'</div></div>',
                unsafe_allow_html=True
            )

        if st.button("🚀 Deploy & Save to Live P&L Tracker", use_container_width=True, type="primary"):
            new_id = len(st.session_state.saved_strategies) + 1
            new_entry = {
                "id": int(datetime.datetime.now().timestamp()),
                "name": strat_title,
                "expiry": display_exp,
                "saved_time": ist_time_str,
                "entry_spot": live_spot,
                "lot_size": lot_size,
                "max_profit": round(payoff_res["max_profit"]),
                "max_loss": round(payoff_res["max_loss"]),
                "legs": [{"action": l["action"], "type": l["type"], "strike": l["strike"], "entry_price": l["premium"], "token": l["token"], "symbol": l["symbol"]} for l in display_legs]
            }
            st.session_state.saved_strategies.append(new_entry)
            save_strategies_to_disk(st.session_state.saved_strategies)
            
            # --- DETAILED TELEGRAM NOTIFICATION FOR DEPLOYMENT ---
            tg_msg = f"🚀 <b>NEW STRATEGY DEPLOYED</b>\n#{new_id}. <b>{strat_title}</b> ({display_exp})\nSaved: {ist_time_str}    Spot: ₹{live_spot:,.2f}\n"
            for lg in display_legs:
                tg_msg += f"• {lg['action']} NIFTY {display_exp} {lg['strike']} {lg['type']} @ ₹{lg['premium']:.2f}\n"
            
            send_telegram_alert(tg_msg)
            st.toast(f"🚀 Telegram Notification Sent: New Strategy Deployed!", icon="✅")
            st.success("✅ Strategy saved!")
            st.rerun()

    with col_chart:
        st.pyplot(payoff_res["fig"], use_container_width=True)

# ==============================================================================
# WORKSPACE 2: SAVED LIVE TRACKER & P&L DESK
# ==============================================================================
else:
    t_c1, t_c2 = st.columns([3, 1])
    with t_c1:
        st.markdown(f"#### 🛡️ Live Trade Tracker & P&L Desk ({len(st.session_state.saved_strategies)} Active)")
    with t_c2:
        if st.button("🔔 Send Test Alert", use_container_width=True):
            ok = send_telegram_alert(f"🔔 <b>Quant Terminal Test Alert</b>\nNifty Spot: ₹{live_spot:,.2f}\nTime: {ist_time_str}")
            if ok: 
                st.toast("🔔 Telegram Notification Sent: Test Message!", icon="✅")
                st.success("✅ Alert Sent!")

    if not st.session_state.saved_strategies:
        st.info("Abhi koi active strategy nahi hai. '⚡ Quant Terminal' tab se koi strategy deploy karein.")
    else:
        all_tokens = [lg.get("token", "") for s in st.session_state.saved_strategies for lg in s.get("legs", []) if lg.get("token")]
        tracker_ltps = fetch_batch_ltps(smart_api, all_tokens)

        for idx, strat in enumerate(st.session_state.saved_strategies):
            strat_id = strat.get("id", idx)
            lot_q = strat.get("lot_size", strat.get("lot", 65))
            ent_spot = strat.get("entry_spot", live_spot)
            spot_drift = live_spot - ent_spot
            total_pnl_pts = 0.0

            legs_html = ""
            strat_display_legs = [] 
            
            # --- For Telegram Exit Alert ---
            tg_exit_legs = ""
            
            for l_i, lg in enumerate(strat.get("legs", []), 1):
                tok = lg.get("token", "")
                ent_price = float(lg.get("entry_price", lg.get("entry", lg.get("premium", 0.0))))
                strat_display_legs.append({"action": lg["action"], "type": lg["type"], "strike": lg["strike"], "premium": ent_price})
                
                cur_p = tracker_ltps.get(tok, ent_price)
                if cur_p <= 0: cur_p = ent_price

                diff_p = (cur_p - ent_price) if lg["action"] == "BUY" else (ent_price - cur_p)
                total_pnl_pts += diff_p
                leg_pnl_rs = diff_p * lot_q
                pnl_col = "#10b981" if leg_pnl_rs >= 0 else "#ef4444"
                act_col = "#10b981" if lg["action"] == "BUY" else "#ef4444"
                sign_p = "+" if leg_pnl_rs >= 0 else ""
                
                tg_exit_legs += f"• {lg['action']} NIFTY {strat.get('expiry', '')} {lg['strike']} {lg['type']}: ₹{ent_price:.2f} → ₹{cur_p:.2f} ({sign_p}₹{leg_pnl_rs:,.0f})\n"

                legs_html += (
                    f'<div style="background-color:#111827; border-left:4px solid {act_col}; border:1px solid #1f2937; border-radius:4px; padding:4px 8px; margin-bottom:4px;">'
                    f'<div style="font-size:0.75rem; font-weight:700; color:#f8fafc;">Leg {l_i}: <span style="color:{act_col};">{lg["action"]}</span> NIFTY {strat.get("expiry", "")} {lg["strike"]} {lg["type"]}</div>'
                    f'<div style="font-size:0.75rem; color:#94a3b8; margin-top:1px;">Entry: ₹{ent_price:.2f} → Live: <b style="color:#f8fafc;">₹{cur_p:.2f}</b> | <span style="color:{pnl_col}; font-weight:800;">{sign_p}₹{leg_pnl_rs:,.0f}</span></div>'
                    f'</div>'
                )

            net_pnl_rs = total_pnl_pts * lot_q
            net_col = "#10b981" if net_pnl_rs >= 0 else "#ef4444"
            net_sign = "+" if net_pnl_rs >= 0 else ""

            status_txt = f"🟡 MONITOR CLOSELY — Drift: {spot_drift:+.1f} pts." if abs(spot_drift) >= 100 else f"🟢 SAFE ZONE — Drift: {spot_drift:+.1f} pts."
            status_bg = "rgba(234, 179, 8, 0.15)" if abs(spot_drift) >= 100 else "rgba(16, 185, 129, 0.15)"
            status_col = "#f59e0b" if abs(spot_drift) >= 100 else "#10b981"

            max_p_clean = round(float(strat.get("max_profit", 0)))
            max_l_clean = round(float(strat.get("max_loss", 0)))

            card_html = (
                f'<div style="background-color:#111827; border:1px solid #1f2937; border-radius:8px; padding:10px; margin-bottom:8px;">'
                f'<div style="font-size:0.9rem; font-weight:800; color:#f8fafc;">#{idx+1} • {strat.get("name", "Strategy")} <span style="color:#38bdf8;">({strat.get("expiry", "")})</span></div>'
                f'<div style="font-size:0.7rem; color:#94a3b8; margin-bottom:4px;">Saved: {strat.get("saved_time", "")} | Entry Spot: ₹{ent_spot:,.2f} | Live: ₹{live_spot:,.2f}</div>'
                f'<div style="display:flex; gap:12px; flex-wrap:wrap; font-size:0.75rem; font-weight:700; margin-bottom:4px;">'
                f'<span style="color:#10b981;">Max Profit: ₹{max_p_clean:,}</span>'
                f'<span style="color:#ef4444;">Max Risk: ₹{max_l_clean:,}</span>'
                f'<span style="color:#f8fafc;">Lot: {lot_q}</span>'
                f'</div>'
                f'<div style="font-size:1rem; font-weight:800; color:#f8fafc; margin-bottom:8px;">Running P&L: <span style="color:{net_col};">{net_sign}₹{net_pnl_rs:,.0f} ({total_pnl_pts:+.2f} pts)</span></div>'
                f'{legs_html}'
                f'<div style="background:{status_bg}; color:{status_col}; padding:4px 8px; border-radius:4px; font-size:0.75rem; font-weight:800; margin-top:6px;">{status_txt}</div>'
                f'</div>'
            )

            c_info, c_graph = st.columns([1, 1.3], gap="medium")
            
            with c_info:
                st.markdown(card_html, unsafe_allow_html=True)
                
                # --- NEW: 3 BUTTONS SIDE BY SIDE ---
                btn_c1, btn_c2, btn_c3 = st.columns(3)
                
                with btn_c1:
                    if st.button("🚪 Exit Trade", key=f"exit_{strat_id}", use_container_width=True):
                        # Exit: Detailed TG Notification
                        pnl_status = "🟢 PROFIT BOOKED" if net_pnl_rs >= 0 else "🔴 LOSS BOOKED"
                        tg_msg = f"🚪 <b>TRADE EXITED — {pnl_status}</b>\nSaved: {strat.get('saved_time', '')}\n#{idx+1}. <b>{strat.get('name', 'Strategy')}</b> ({strat.get('expiry', '')})\nNet: {net_sign}{total_pnl_pts:+.2f} pts | P&L: <b>{net_sign}₹{net_pnl_rs:,.0f}</b>\n{tg_exit_legs}"
                        send_telegram_alert(tg_msg)
                        
                        st.toast(f"🚀 Telegram Notification Sent: Trade Exited! P&L: {net_sign}₹{net_pnl_rs:,.0f}", icon="✅")
                        st.session_state.saved_strategies.pop(idx)
                        save_strategies_to_disk(st.session_state.saved_strategies)
                        st.rerun()

                with btn_c2:
                    edit_key = f"edit_mode_{strat_id}"
                    if edit_key not in st.session_state:
                        st.session_state[edit_key] = False
                    if st.button("✏️ Edit Trade", key=f"btn_edit_{strat_id}", use_container_width=True):
                        st.session_state[edit_key] = not st.session_state[edit_key]
                        st.rerun()
                        
                with btn_c3:
                    if st.button("🗑️ Delete", key=f"del_{strat_id}", use_container_width=True):
                        # Delete: Quietly removes strategy (NO Notification)
                        st.session_state.saved_strategies.pop(idx)
                        save_strategies_to_disk(st.session_state.saved_strategies)
                        st.rerun()

                # --- DYNAMIC EDIT FORM ---
                if st.session_state.get(f"edit_mode_{strat_id}", False):
                    st.markdown("<div style='background-color:#1e293b; padding:12px; border-radius:6px; margin-top:8px;'>", unsafe_allow_html=True)
                    st.markdown("<div style='color:#f8fafc; font-weight:bold; font-size:0.9rem; margin-bottom:10px;'>Update Strikes & Entry Prices</div>", unsafe_allow_html=True)
                    
                    updated = False
                    new_legs = []
                    tg_edit_msg = f"✏️ <b>TRADE EDITED</b>\n#{idx+1}. <b>{strat.get('name', 'Strategy')}</b> ({strat.get('expiry', '')})\n"
                    
                    for l_i, lg in enumerate(strat.get("legs", [])):
                        cur_ent_val = float(lg.get("entry_price", lg.get("entry", lg.get("premium", 0.0))))
                        c1, c2 = st.columns(2)
                        with c1:
                            new_st = st.number_input(f"Leg {l_i+1} Strike", value=int(lg["strike"]), step=50, key=f"st_{strat_id}_{l_i}")
                        with c2:
                            new_pr = st.number_input(f"Leg {l_i+1} Entry ₹", value=cur_ent_val, step=0.5, key=f"pr_{strat_id}_{l_i}")
                        
                        new_legs.append({"action": lg["action"], "type": lg["type"], "strike": new_st, "entry_price": new_pr, "token": lg.get("token", ""), "symbol": lg.get("symbol", "")})
                        if new_st != lg["strike"] or new_pr != cur_ent_val:
                            updated = True
                            tg_edit_msg += f"• Leg {l_i+1}: {lg['action']} {lg['type']} -> Strike: {new_st}, Entry: ₹{new_pr}\n"
                    
                    if st.button("💾 Save Changes", key=f"save_{strat_id}", type="primary", use_container_width=True):
                        if updated:
                            st.session_state.saved_strategies[idx]["legs"] = new_legs
                            save_strategies_to_disk(st.session_state.saved_strategies)
                            
                            # Detailed Edit Notification
                            send_telegram_alert(tg_edit_msg)
                            st.toast("🚀 Telegram Notification Sent: Trade Edited!", icon="✅")
                            
                        st.session_state[f"edit_mode_{strat_id}"] = False
                        st.rerun()
                        
                    st.markdown("</div>", unsafe_allow_html=True)
            
            with c_graph:
                saved_payoff = compute_payoff_and_chart(strat_display_legs, ent_spot, live_vix, 1, lot_q, strat.get("expiry", ""))
                st.pyplot(saved_payoff["fig"], use_container_width=True)
            
            st.markdown("<hr style='border-color: #1f2937; margin: 15px 0;'>", unsafe_allow_html=True)
