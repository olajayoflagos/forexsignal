import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from flask import current_app

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.investing.com/economic-calendar/",
}

def fetch_economic_calendar(date_filter=None):
    try:
        url = "https://www.investing.com/economic-calendar/"
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        events = []
        table = soup.find("table", {"id": "economicCalendarData"})
        if not table:
            current_app.logger.warning("Economic calendar table not found")
            return events

        for row in table.find_all("tr", {"class": ["js-event-item", "economic-event"]}, recursive=False):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 5:
                continue
            
            # Extract date and time
            date_time = cells[0].find("span", class_="date").get_text(strip=True)
            event_date = datetime.strptime(date_time.split()[0], "%Y-%m-%d").date()
            if date_filter and event_date != date_filter:
                continue
            time_str = cells[1].get_text(strip=True) if cells[1].get_text(strip=True) else "All Day"

            # Extract currency and event
            currency = cells[2].find("a").get_text(strip=True) if cells[2].find("a") else "N/A"
            event = cells[3].find("a").get_text(strip=True) if cells[3].find("a") else cells[3].get_text(strip=True)

            # Extract impact
            impact_elem = cells[4].find("span")
            impact = "low"
            if impact_elem and "green" in impact_elem.get("class", []):
                impact = "low"
            elif impact_elem and "orange" in impact_elem.get("class", []):
                impact = "medium"
            elif impact_elem and "red" in impact_elem.get("class", []):
                impact = "high"

            events.append({
                "date": event_date.isoformat(),
                "time": time_str,
                "currency": currency,
                "event": event,
                "impact": impact
            })
        return events
    except Exception as e:
        current_app.logger.warning("Calendar fetch failed: %s", e)
        return []

# Keep the news fetch as a fallback (optional)
def fetch_forexfactory_news():
    # This can be removed or kept as a backup
    current_app.logger.warning("ForexFactory news fetch not implemented")
    return []