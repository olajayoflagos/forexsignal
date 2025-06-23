import numpy as _np
_np.NaN = _np.nan

import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

import pandas as pd
import pandas_ta as ta
from deriv_api import DerivAPI
from deriv_api.errors import ResponseError
from dotenv import load_dotenv

import firestore_config

load_dotenv()
API_TOKEN = os.getenv("DERIV_TOKEN")
INITIAL_CAPITAL = float(os.getenv("CAPITAL", "10000"))
RISK_PCT = 0.02
FIB_TOLERANCE = 0.005
SPREAD_PIPS = 1.0
RRR = 3.0

SYMBOLS = [
    "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD", "frxNZDUSD", "frxUSDCAD",
    "frxUSDCHF", "frxGBPJPY", "frxEURGBP", "frxEURJPY", "frxEURCHF", "frxAUDJPY",
    "frxAUDCAD", "frxAUDCHF", "frxAUDNZD", "frxNZDJPY", "frxGBPCHF", "frxGBPAUD",
    "frxGBPNZD", "frxXAUUSD", "R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V",
    "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V", "1HZ150V", "1HZ250V", "JD10", "JD25",
    "JD50", "JD75", "JD100",
]

MA_LONG, MA_SHORT = 200, 20
RSI_LEN, SMA_LEN = 16, 16
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 4, 24, 16

FIB_LEVELS = {
    0.0: None,
    0.3: 0.618,
    0.5: -0.3,
    0.618: 1.0,
    -1.618: None
}

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def fetch_live_candles(api, symbol: str, granularity: int, count: int):
    end_time = int(datetime.now().timestamp())
    req = {
        "ticks_history": symbol,
        "style": "candles",
        "granularity": granularity,
        "count": count,
        "end": end_time,
        "adjust_start_time": 1
    }
    try:
        resp = await api.send(req)
        df = pd.DataFrame(resp.get("candles", []))
        if df.empty:
            logger.warning(f"[{symbol}] No candles returned")
            return pd.DataFrame()
        df["epoch"] = pd.to_datetime(df["epoch"], unit="s")
        return df.set_index("epoch").sort_index().tail(count)
    except ResponseError as e:
        logger.error(f"[{symbol}] fetch error: {e}")
        return pd.DataFrame()

def compute_indicators(df2h: pd.DataFrame, df5m: pd.DataFrame):
    swing = df2h.iloc[-50:]
    hi, lo = swing["high"].max(), swing["low"].min()
    fibs = {lvl: lo + lvl * (hi - lo) for lvl in FIB_LEVELS}

    df = df5m.copy()
    df["ma_long"] = ta.sma(df["close"], length=MA_LONG)
    df["ma_short"] = ta.sma(df["close"], length=MA_SHORT)
    df["rsi"] = ta.rsi(df["close"], length=RSI_LEN)
    df["sma"] = ta.sma(df["close"], length=SMA_LEN)
    macd = ta.macd(df["close"], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    return df.join(macd).dropna(), fibs

def generate_signal(df: pd.DataFrame, fibs: dict, equity: float, symbol: str):
    if df.empty or len(df) < MA_LONG:
        return None, 0, None

    last = df.iloc[-1]
    price = last["close"]
    score = 0
    tp = None

    for lvl, lvl_price in fibs.items():
        if lvl_price is None:
            continue
        if abs(price - lvl_price) / lvl_price < FIB_TOLERANCE:
            score += 1
            opp = FIB_LEVELS[lvl]
            if opp in fibs and fibs.get(FIB_LEVELS.get(lvl)):
                tp = fibs[FIB_LEVELS[lvl]]
            else:
                adverse = (1000 if "XAUUSD" in symbol else 600) * 0.0001
                tp = price + (adverse * RRR if last["MACDh_4_24_16"] > 0 else -adverse * RRR)

            long_cond = last["MACDh_4_24_16"] > 0 and last["rsi"] > 50 and price > last["ma_long"]
            short_cond = last["MACDh_4_24_16"] < 0 and last["rsi"] < 50 and price < last["ma_long"]

            if long_cond:
                score += 2
                direction = "BUY"
            elif short_cond:
                score += 2
                direction = "SELL"
            else:
                return None, 0, None

            adverse = (1000 if "XAUUSD" in symbol else 600) * 0.0001
            if abs(price - lvl_price) >= adverse:
                score += 1
                sl = price - adverse if direction == "BUY" else price + adverse
                stake = equity * RISK_PCT
                return {
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": price,
                    "tp": tp,
                    "stop_loss": sl,
                    "stake": stake
                }, score, adverse / 0.0001

    return None, 0, None

async def scan_signals_once():
    api = DerivAPI(app_id="1", access_token=API_TOKEN)
    await api.authorize({"authorize": API_TOKEN})

    while True:
        now = datetime.now(ZoneInfo("Africa/Lagos"))
        if now.hour >= 18 or now.hour < 5:
            logger.info("↪️ Outside trading hours: %s", now.time())
            await asyncio.sleep(300)
            continue

        best_score = -1
        best_sig = None
        best_pips = None

        for symbol in SYMBOLS:
            df2h = await fetch_live_candles(api, symbol, 7200, 50)
            df5m = await fetch_live_candles(api, symbol, 300, MA_LONG + 50)
            if df2h.empty or df5m.empty or len(df5m) < MA_LONG:
                continue

            df_ind, fibs = compute_indicators(df2h, df5m)
            sig, score, pips = generate_signal(df_ind, fibs, INITIAL_CAPITAL, symbol)
            if score > best_score:
                best_score = score
                best_sig = sig
                best_pips = pips

        if best_sig and best_score >= 3:
            best_sig["time"] = now.isoformat()
            best_sig["score"] = best_score
            best_sig["pips_threshold"] = best_pips
            firestore_config.db.collection("signals").add(best_sig)

            logger.info(f"\n[{now.strftime('%H:%M')}] Signal ✔️ {best_sig}")
        else:
            logger.info(f"[{now.strftime('%H:%M')}] No strong signal (score={best_score})")

        await asyncio.sleep(300)
        if __name__ == "__main__":
            firestore_config.initialize_firestore()
            asyncio.run(scan_signals_once())
