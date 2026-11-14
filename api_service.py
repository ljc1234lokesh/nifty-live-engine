import streamlit as st
import pyotp
from SmartApi import SmartConnect
import datetime
import requests
import pandas as pd

def send_telegram_alert(message_text):
    tg_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
    if not tg_token or not tg_chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        payload = {"chat_id": tg_chat_id, "text": message_text, "parse_mode": "HTML"}
        r = requests.post(url, json=payload, timeout=8)
        return r.status_code == 200 and bool(r.json().get("ok"))
    except Exception:
        return False

@st.cache_resource(ttl=1800, show_spinner=False)
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

@st.cache_data(ttl=43200, show_spinner=False)
def load_angel_master_data():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    r = requests.get(url, timeout=30)
    data = r.json()
    df = pd.DataFrame(data)
    
    idx_map = {
        "NIFTY": "99926000",
        "BANKNIFTY": "99926009",
        "VIX": "99926017",
        "SENSEX": "99919000"
    }
    
    idx_df = df[df["instrumenttype"] == "AMXIDX"]
    for _, row in idx_df.iterrows():
        nm = str(row["name"]).upper().strip()
        sym = str(row["symbol"]).upper().strip()
        tok = str(row["token"]).strip()
        if nm == "INDIA VIX" or sym == "INDIA VIX":
            idx_map["VIX"] = tok
        elif (nm == "SENSEX" or sym == "SENSEX") and str(row["exch_seg"]) == "BSE":
            idx_map["SENSEX"] = tok

    opt_df = df[(df["exch_seg"] == "NFO") & (df["name"] == "NIFTY") & (df["instrumenttype"] == "OPTIDX")].copy()
    opt_df["strike_int"] = (pd.to_numeric(opt_df["strike"], errors="coerce") / 100).round().astype(int)
    opt_df["lotsize_int"] = pd.to_numeric(opt_df["lotsize"], errors="coerce").fillna(65).astype(int)
    opt_df["opt_type"] = opt_df["symbol"].str[-2:]
    opt_df["expiry_dt"] = pd.to_datetime(opt_df["expiry"], format="%d%b%Y", errors="coerce").dt.date
    return opt_df[["token", "symbol", "expiry", "expiry_dt", "strike_int", "opt_type", "lotsize_int"]], idx_map

@st.cache_data(ttl=30, show_spinner=False)
def get_comprehensive_indices(_smart_api, idx_tokens):
    # Never fabricate live prices when a broker quote is missing.
    empty = {k: None for k in ("ltp", "open", "high", "low", "close")}
    out = {"nifty": dict(empty), "banknifty": dict(empty),
           "sensex": dict(empty), "vix": None}
    if _smart_api is None:
        return out
    try:
        t_nifty, t_bnf, t_vix, t_snx = idx_tokens["NIFTY"], idx_tokens["BANKNIFTY"], idx_tokens["VIX"], idx_tokens["SENSEX"]
        
        # Fetch full market quote for NSE indices to get open, high, low, close directly
        res_nse = _smart_api.getMarketData("FULL", {"NSE": [t_nifty, t_bnf, t_vix]})
        if res_nse and res_nse.get("status") and "data" in res_nse:
            for item in res_nse["data"].get("fetched", []):
                tok = str(item.get("symbolToken"))
                ltp = float(item.get("ltp", 0))
                opn = float(item.get("open", ltp))
                hi = float(item.get("high", ltp))
                lo = float(item.get("low", ltp))
                cl = float(item.get("close", ltp))
                
                if tok == t_nifty and ltp > 10000:
                    out["nifty"] = {"ltp": ltp, "open": opn if opn > 0 else ltp, "high": hi if hi > 0 else ltp, "low": lo if lo > 0 else ltp, "close": cl if cl > 0 else ltp}
                elif tok == t_bnf and ltp > 25000:
                    out["banknifty"] = {"ltp": ltp, "open": opn if opn > 0 else ltp, "high": hi if hi > 0 else ltp, "low": lo if lo > 0 else ltp, "close": cl if cl > 0 else ltp}
                elif tok == t_vix and ltp > 0:
                    out["vix"] = ltp

        # Fetch full market quote for BSE Sensex
        res_bse = _smart_api.getMarketData("FULL", {"BSE": [t_snx]})
        if res_bse and res_bse.get("status") and "data" in res_bse:
            for item in res_bse["data"].get("fetched", []):
                if str(item.get("symbolToken")) == t_snx:
                    ltp = float(item.get("ltp", 0))
                    opn = float(item.get("open", ltp))
                    hi = float(item.get("high", ltp))
                    lo = float(item.get("low", ltp))
                    cl = float(item.get("close", ltp))
                    if ltp > 10000:
                        out["sensex"] = {"ltp": ltp, "open": opn if opn > 0 else ltp, "high": hi if hi > 0 else ltp, "low": lo if lo > 0 else ltp, "close": cl if cl > 0 else ltp}
    except Exception:
        pass
    return out

@st.cache_data(ttl=15, show_spinner=False)
def get_live_option_chain_oi(_smart_api, nfo_df, exp_date_str, atm_val):
    fallback = {
        "pcr": 0.0, "max_pain": atm_val,
        "call_wall": atm_val + 150, "put_wall": atm_val - 150,
        "call_wall_oi": 0, "put_wall_oi": 0,
        "is_live": False, "ltp_dict": {}
    }
    try:
        exp_dt_obj = datetime.date.fromisoformat(exp_date_str)
        sub_df = nfo_df[nfo_df["expiry_dt"] == exp_dt_obj]
        if sub_df.empty:
            return fallback

        strikes_scan = [atm_val + i * 50 for i in range(-8, 9)]
        scan_df = sub_df[sub_df["strike_int"].isin(strikes_scan)]
        tokens = scan_df["token"].astype(str).tolist()
        if not tokens:
            return fallback

        res_full = _smart_api.getMarketData("FULL", {"NFO": tokens})
        if not (res_full and res_full.get("status") and "data" in res_full):
            return fallback

        fetched = res_full["data"].get("fetched", [])
        if not fetched:
            return fallback

        tok_meta = {str(r["token"]): (int(r["strike_int"]), str(r["opt_type"])) for _, r in scan_df.iterrows()}
        ce_oi_map, pe_oi_map, ltp_dict = {}, {}, {}

        for item in fetched:
            tok = str(item.get("symbolToken", ""))
            if tok in tok_meta:
                st_k, o_type = tok_meta[tok]
                oi_val = float(item.get("opnInterest", 0))
                ltp_dict[tok] = float(item.get("ltp", 0))
                if o_type == "CE":
                    ce_oi_map[st_k] = oi_val
                elif o_type == "PE":
                    pe_oi_map[st_k] = oi_val

        tot_ce_oi, tot_pe_oi = sum(ce_oi_map.values()), sum(pe_oi_map.values())
        if tot_ce_oi <= 0 or tot_pe_oi <= 0:
            fallback["ltp_dict"] = ltp_dict
            return fallback

        pcr_live = round(tot_pe_oi / tot_ce_oi, 2)
        otm_ce = {k: v for k, v in ce_oi_map.items() if k >= atm_val}
        call_wall_k = max(otm_ce, key=otm_ce.get) if otm_ce else max(ce_oi_map, key=ce_oi_map.get)

        otm_pe = {k: v for k, v in pe_oi_map.items() if k <= atm_val}
        put_wall_k = max(otm_pe, key=otm_pe.get) if otm_pe else max(pe_oi_map, key=pe_oi_map.get)

        min_pain_val = float("inf")
        max_pain_k = atm_val
        for candidate_spot in strikes_scan:
            pain = sum((candidate_spot - k_c) * oi_c for k_c, oi_c in ce_oi_map.items() if candidate_spot > k_c)
            pain += sum((k_p - candidate_spot) * oi_p for k_p, oi_p in pe_oi_map.items() if candidate_spot < k_p)
            if pain < min_pain_val:
                min_pain_val = pain
                max_pain_k = candidate_spot

        return {
            "pcr": pcr_live, "max_pain": max_pain_k,
            "call_wall": call_wall_k, "put_wall": put_wall_k,
            "call_wall_oi": int(ce_oi_map.get(call_wall_k, 0)),
            "put_wall_oi": int(pe_oi_map.get(put_wall_k, 0)),
            "is_live": True, "ltp_dict": ltp_dict
        }
    except Exception:
        return fallback

def fetch_batch_ltps(smart_api, tokens):
    ltp_map = {}
    if not tokens:
        return ltp_map
    try:
        if smart_api is None:
            return ltp_map
        res = smart_api.getMarketData("LTP", {"NFO": list(set(str(t) for t in tokens if t))})
        if res and res.get("status") and "data" in res:
            for item in res["data"].get("fetched", []):
                price = float(item.get("ltp") or 0)
                if price > 0:
                    ltp_map[str(item["symbolToken"])] = price
    except Exception:
        pass
    return ltp_map
    
