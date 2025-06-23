#
#
#  --- Enhanced Forex & Volatility Index Signal Scanner ---
#
#  This script connects to the Deriv API to analyze multiple financial symbols.
#  It uses a combination of Fibonacci retracement levels and technical indicators
#  (MACD, RSI, 200 SMA) to identify the single best trading opportunity
#  across all configured symbols during each scan cycle.
#
#  Version: 2.0
#  Date: 2025-06-23
#
#

import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

import numpy as _np
_пр.NaN = _np.nan
import pandas as pd
import pandas_ta as ta
from deriv_api import DerivAPI
from deriv_api.errors import ResponseError
from dotenv import load_dotenv

import firestore_config

# --- Configuration ---
_np.NaN = _np.nan  # Set numpy NaN representation
load_dotenv()

# --- API and Account Settings ---
API_TOKEN = os.getenv("DERIV_TOKEN")
INITIAL_CAPITAL = float(os.getenv("CAPITAL", "10000"))

# --- Strategy Parameters ---
RISK_PCT = 0.02  # Percentage of capital to risk per trade
RRR = 3.0  # Risk-to-Reward Ratio
FIB_TOLERANCE = 0.015  # 1.5% tolerance zone around Fibonacci levels
STOP_LOSS_PIPS = {  # Pips/points for stop loss calculation
    "DEFAULT": 60,
    "XAUUSD": 100,  # Gold uses a wider stop
}

# --- Technical Indicator Settings ---
MA_LONG, MA_SHORT = 200, 20
RSI_LEN, SMA_LEN = 16, 16
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 4, 24, 16

# --- Fibonacci Levels for Analysis ---
# Key: Entry level, Value: Target level
FIB_LEVELS = {
    0.382: 0.618,
    0.5: 0.0,
    0.618: 0.382,
}

# --- Symbols to Scan ---
SYMBOLS = [
    "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD", "frxNZDUSD", "frxUSDCAD",
    "frxUSDCHF", "frxGBPJPY", "frxEURGBP", "frxEURJPY", "frxEURCHF", "frxAUDJPY",
    "frxAUDCAD", "frxAUDCHF", "frxAUDNZD", "frxNZDJPY", "frxGBPCHF", "frxGBPAUD",
    "frxGBPNZD", "frxXAUUSD", "R_10", "R_25", "R_50", "R_75", "R_100", "1HZ10V",
    "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V", "1HZ150V", "1HZ250V", "JD10", "JD25",
    "JD50", "JD75", "JD100",
]

# --- Firestore Settings ---
SAVE_TO_DB_THRESHOLD = 3 # Only save signals with a score of 3 ("High")

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_pip_value(symbol: str) -> float:
    """Returns the value of a single pip for a given symbol."""
    if "JPY" in symbol:
        return 0.01
    if "XAUUSD" in symbol:
        return 0.01
    return 0.0001


async def fetch_live_candles(api: DerivAPI, symbol: str, granularity: int, count: int) -> pd.DataFrame:
    """Fetches historical candle data from the Deriv API."""
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
            logger.debug(f"No candles returned for {symbol}")
            return pd.DataFrame()
        df["epoch"] = pd.to_datetime(df["epoch"], unit="s")
        return df.set_index("epoch").sort_index()
    except ResponseError as e:
        logger.error(f"API Error fetching candles for {symbol}: {e}")
        return pd.DataFrame()


def compute_indicators(df2h: pd.DataFrame, df5m: pd.DataFrame) -> (pd.DataFrame, dict):
    """Calculates all required technical indicators and Fibonacci levels."""
    # 1. Calculate Fibonacci levels from the 2-hour chart swing
    swing = df2h.iloc[-50:]
    hi, lo = swing["high"].max(), swing["low"].min()
    fibs = {lvl: lo + lvl * (hi - lo) for lvl in FIB_LEVELS}
    
    # Also add the swing high and low to the fibs dictionary for potential use
    fibs[0.0] = lo
    fibs[1.0] = hi

    # 2. Calculate technical indicators on the 5-minute chart
    df = df5m.copy()
    df["ma_long"] = ta.sma(df["close"], length=MA_LONG)
    df["ma_short"] = ta.sma(df["close"], length=MA_SHORT)
    df["rsi"] = ta.rsi(df["close"], length=RSI_LEN)
    df["sma"] = ta.sma(df["close"], length=SMA_LEN)
    macd = ta.macd(df["close"], fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    
    return df.join(macd).dropna(), fibs


def analyze_signal_for_symbol(df: pd.DataFrame, fibs: dict, equity: float, symbol: str) -> dict | None:
    """
    Analyzes the latest candle data against the strategy rules and returns a scored signal.
    Returns: A dictionary with the signal details or None.
    """
    if df.empty or len(df) < MA_LONG:
        return None

    last = df.iloc[-1]
    price = last["close"]

    for lvl, lvl_price in fibs.items():
        # --- Condition 1: Price Location ---
        # Is the current price within the tolerance zone of a Fibonacci level?
        if abs(price - lvl_price) / lvl_price < FIB_TOLERANCE:
            score = 1
            direction = None

            # --- Condition 2: Primary Trend (MACD & RSI) ---
            is_uptrend_primary = last["MACDh_4_24_16"] > 0 and last["rsi"] > 50
            is_downtrend_primary = last["MACDh_4_24_16"] < 0 and last["rsi"] < 50

            if is_uptrend_primary:
                score += 1
                direction = "BUY"
            elif is_downtrend_primary:
                score += 1
                direction = "SELL"

            # --- Condition 3: Confirmation Trend (200 SMA) ---
            if direction == "BUY" and price > last["ma_long"]:
                score += 1
            elif direction == "SELL" and price < last["ma_long"]:
                score += 1
            
            # --- Determine Signal Strength and Finalize ---
            if direction:
                signal_strength_map = {1: "Low", 2: "Medium", 3: "High"}
                signal_strength = signal_strength_map.get(score, "Low")

                # Calculate Trade Parameters
                pip_value = get_pip_value(symbol)
                sl_pips = STOP_LOSS_PIPS.get(symbol, STOP_LOSS_PIPS["DEFAULT"])
                adverse_distance = sl_pips * pip_value
                
                sl = price - adverse_distance if direction == "BUY" else price + adverse_distance
                tp = price + (adverse_distance * RRR) if direction == "BUY" else price - (adverse_distance * RRR)

                return {
                    "symbol": symbol,
                    "strength": signal_strength,
                    "score": score,
                    "direction": direction,
                    "entry_price": price,
                    "tp": tp,
                    "stop_loss": sl,
                    "stake": equity * RISK_PCT,
                    "timestamp": datetime.now(ZoneInfo("Africa/Lagos")).isoformat()
                }

    return None


async def scan_signals_once():
    """Main function to run the scanning loop."""
    logger.info("Connecting to Deriv API...")
    api = DerivAPI(app_id=os.getenv("DERIV_APP_ID", "1"), access_token=API_TOKEN)
    await api.authorize({"authorize": API_TOKEN})
    logger.info("Connection successful. Starting scanner...")

    while True:
        now = datetime.now(ZoneInfo("Africa/Lagos"))
        if now.hour >= 22 or now.hour < 8:
            logger.info(f"Outside trading hours ({now.strftime('%H:%M')}). Sleeping for 5 minutes.")
            await asyncio.sleep(300)
            continue

        best_signal = None

        for symbol in SYMBOLS:
            df2h = await fetch_live_candles(api, symbol, 7200, 50)  # 2-hour candles for swing
            df5m = await fetch_live_candles(api, symbol, 300, MA_LONG + 50)  # 5-min candles for entry

            if df2h.empty or df5m.empty or len(df5m) < MA_LONG:
                logger.debug(f"Skipping {symbol} due to insufficient data.")
                continue

            df_with_indicators, fib_levels = compute_indicators(df2h, df5m)
            current_signal = analyze_signal_for_symbol(df_with_indicators, fib_levels, INITIAL_CAPITAL, symbol)

            if current_signal:
                # If we find a signal, check if it's better than the best one we've seen so far
                if best_signal is None or current_signal["score"] > best_signal["score"]:
                    best_signal = current_signal
        
        # After checking all symbols, report the single best one
        if best_signal:
            logger.info(f"Found Best Signal: [{best_signal['strength'].upper()} SIGNAL] for {best_signal['symbol']} "
                        f"(Score: {best_signal['score']}/3) -> {best_signal['direction']}")
            
            # Save to database only if it's a high-quality signal
            if best_signal["score"] >= SAVE_TO_DB_THRESHOLD:
                try:
                    firestore_config.db.collection("signals").add(best_signal)
                    logger.info(f"High signal for {best_signal['symbol']} saved to database.")
                except Exception as e:
                    logger.error(f"Failed to save signal to Firestore: {e}")
        else:
            logger.info(f"No qualifying signal found across all symbols in this cycle.")

        logger.info("Scan complete. Waiting for the next 5-minute candle...")
        await asyncio.sleep(300)


if __name__ == "__main__":
    try:
        firestore_config.initialize_firestore()
        asyncio.run(scan_signals_once())
    except Exception as e:
        logger.error(f"A critical error occurred: {e}")

