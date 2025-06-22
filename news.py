import os, time, logging
from flask import Blueprint, render_template, request
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

news = Blueprint('news', __name__, url_prefix='/news')

API_KEY = os.getenv("ALPHAVANTAGE_KEY")
TOPICS = os.getenv("AV_NEWS_TOPICS", "forex,usd,eur,gbp,jpy,CHF,cad,aud,nzd,bank,market").split(",")
PAGE_SIZE = int(os.getenv("AV_NEWS_PER_PAGE", 20))
CACHE_TTL = int(os.getenv("AV_FEED_TTL", 300))

_cache = {
    'cal': {'ts': 0, 'entries': []},
    'news': {'ts': 0, 'entries': []},
}

def fetch_calendar(date_filter=None):
    """Grab Investing.com economic calendar via scraping."""
    now = time.time()
    if now - _cache['cal']['ts'] < CACHE_TTL:
        return _cache['cal']['entries']

    from ff_feeds import fetch_economic_calendar
    entries = fetch_economic_calendar(date_filter)
    _cache['cal'] = {'ts': now, 'entries': entries}
    return entries

def fetch_news():
    """Grab Alpha Vantage news sentiment on your topics."""
    now = time.time()
    if now - _cache['news']['ts'] < CACHE_TTL:
        return _cache['news']['entries']

    URL = "https://www.alphavantage.co/query"
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": ",".join(TOPICS),
        "apikey": API_KEY,
    }
    try:
        resp = requests.get(URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("feed", [])
        for it in data:
            t = it.get("time_published") or it.get("published_at") or it.get("time")
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                it["published"] = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except:
                it["published"] = t or ""
        entries = data
    except Exception as e:
        logging.warning(f"[news] news fetch failed: {e}")
        entries = _cache['news']['entries']

    _cache['news'] = {'ts': now, 'entries': entries}
    return entries

@news.route("/")
@news.route("/page/<int:page>")
@news.route("/date/<string:date>")
def view_news(page=1, date=None):
    # Convert date string to date object if provided
    date_filter = datetime.strptime(date, "%Y-%m-%d").date() if date else None
    
    # 1) calendar
    cal = fetch_calendar(date_filter)[:50]  # Limit to 50 events
    
    # 2) news + pagination
    all_news = fetch_news()
    total = len(all_news)
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    start = (page - 1) * PAGE_SIZE
    slice_ = all_news[start:start + PAGE_SIZE]

    return render_template(
        "news.html",
        calendar=cal,
        news_items=slice_,
        page=page,
        pages=pages,
        selected_date=date if date else datetime.now(timezone.utc).date().isoformat()
    )