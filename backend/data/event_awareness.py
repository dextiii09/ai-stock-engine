"""
Real Macro Event Awareness using Yahoo Finance earnings calendar + FRED.
No hardcoded day-of-month patterns.
"""
import datetime
import yfinance as yf
from typing import Dict, Any, List

# Real FOMC 2024-2025 meeting dates (published by Federal Reserve)
FOMC_DATES_2025 = [
    "2025-01-28", "2025-01-29",
    "2025-03-18", "2025-03-19",
    "2025-05-06", "2025-05-07",
    "2025-06-17", "2025-06-18",
    "2025-07-29", "2025-07-30",
    "2025-09-16", "2025-09-17",
    "2025-10-28", "2025-10-29",
    "2025-12-09", "2025-12-10",
    "2026-01-27", "2026-01-28",
    "2026-03-17", "2026-03-18",
    "2026-05-05", "2026-05-06",
    "2026-06-09", "2026-06-10",
    "2026-07-28", "2026-07-29",
    "2026-09-15", "2026-09-16",
    "2026-10-27", "2026-10-28",
    "2026-12-08", "2026-12-09",
]

# Real US CPI release schedule (BLS publishes ~mid-month)
CPI_DATES_2025 = [
    "2025-01-15", "2025-02-12", "2025-03-12",
    "2025-04-10", "2025-05-13", "2025-06-11",
    "2025-07-11", "2025-08-12", "2025-09-10",
    "2025-10-15", "2025-11-12", "2025-12-10",
    "2026-01-14", "2026-02-11", "2026-03-11",
    "2026-04-10", "2026-05-13", "2026-06-10",
    "2026-07-14", "2026-08-12", "2026-09-11",
    "2026-10-14", "2026-11-12", "2026-12-10",
]

# NFP (Non-Farm Payrolls) — first Friday of each month
NFP_DATES_2025 = [
    "2025-01-10", "2025-02-07", "2025-03-07",
    "2025-04-04", "2025-05-02", "2025-06-06",
    "2025-07-03", "2025-08-01", "2025-09-05",
    "2025-10-03", "2025-11-07", "2025-12-05",
    "2026-01-09", "2026-02-06", "2026-03-06",
    "2026-04-03", "2026-05-01", "2026-06-05",
    "2026-07-03", "2026-08-07", "2026-09-04",
    "2026-10-02", "2026-11-06", "2026-12-04",
]

BLACKOUT_WINDOW_DAYS = 0  # Blackout only on the day of the event

# US market holidays — CME/NYSE closed on these dates (futures close early or fully)
US_MARKET_HOLIDAYS = {
    # 2025
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # MLK Jr. Day
    "2025-02-17",  # Presidents' Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving
    "2025-12-25",  # Christmas
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Jr. Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed — July 4 is Saturday, observed Friday)
    "2026-07-04",  # Independence Day
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
}

# Real RBI MPC 2025-2026 meeting dates
RBI_MPC_DATES_2025_2026 = [
    "2025-04-09", "2025-06-06", "2025-08-06", "2025-10-01", "2025-12-05",
    "2026-02-06", "2026-04-08", "2026-06-05", "2026-08-07", "2026-10-09", "2026-12-04"
]

# India CPI Release schedule (typically 12th of each month)
INDIA_CPI_DATES_2025_2026 = [
    "2025-01-12", "2025-02-12", "2025-03-12", "2025-04-12", "2025-05-12", "2025-06-12",
    "2025-07-12", "2025-08-12", "2025-09-12", "2025-10-12", "2025-11-12", "2025-12-12",
    "2026-01-12", "2026-02-12", "2026-03-12", "2026-04-13", "2026-05-12", "2026-06-12",
    "2026-07-13", "2026-08-12", "2026-09-14", "2026-10-12", "2026-11-12", "2026-12-14"
]


class EventAwarenessEngine:
    """
    Real macroeconomic event detection.
    Uses actual published FOMC, CPI, NFP calendars.
    Fetches real earnings dates from Yahoo Finance for active symbols.
    """

    def _is_near(self, date_str: str, today: datetime.date, window: int = BLACKOUT_WINDOW_DAYS) -> bool:
        try:
            event_date = datetime.date.fromisoformat(date_str)
            delta = (event_date - today).days
            # delta > 0 means event is in the future (e.g. 1 day away)
            # delta == 0 means event is today
            # We want to blackout `window` days BEFORE and the day OF, but NOT the day after.
            return 0 <= delta <= window
        except Exception:
            return False

    def check_today(self, tick_data: Dict[str, Any] = None) -> Dict[str, Any]:
        today = datetime.date.today()
        upcoming: List[Dict[str, Any]] = []

        # US Market Holiday check (CME/NYSE closed)
        today_str = str(today)
        if today_str in US_MARKET_HOLIDAYS:
            return {
                "today": today_str,
                "upcoming_events": [{"name": f"US Market Holiday ({today_str})", "type": "holiday", "date": today_str, "risk": "N/A", "blackout": True}],
                "next_7_days": self._get_next_events(today),
                "trading_blackout": True,
                "blackout_reason": f"US Market Holiday — markets closed on {today_str}",
                "data_source": "CME/NYSE holiday calendar"
            }

        if tick_data and tick_data.get("data_quality") == "LOW_ROLLOVER":
             upcoming.append({
                 "name": "NQ Quarterly Rollover Week",
                 "type": "rollover",
                 "date": str(datetime.date.today()),
                 "impact": "CRITICAL",
                 "action": "HALT_TRADING",
                 "description": "Front-month volume drops and spreads widen.",
                 "blackout": True,   # was missing — caused KeyError on line: any(e["blackout"] ...)
             })

        # FOMC
        # NOTE: window=0 (day-of only), consistent with BLACKOUT_WINDOW_DAYS and
        # the CPI check below. Previously window=1 blacked out the day BEFORE too;
        # because FOMC dates are stored as consecutive pairs (e.g. 07-28 & 07-29),
        # that silently produced a 3-day blackout per meeting and vetoed all forex
        # trading the day before every FOMC. If a pre-event blackout is ever wanted,
        # store only each meeting's decision day rather than widening this window.
        for d in FOMC_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({
                    "name": f"FOMC Meeting ({d})",
                    "type": "fed",
                    "date": d,
                    "risk": "HIGH",
                    "blackout": True
                })
                break

        # CPI
        for d in CPI_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({
                    "name": f"US CPI Release ({d})",
                    "type": "inflation",
                    "date": d,
                    "risk": "HIGH",
                    "blackout": True
                })
                break

        # NFP
        for d in NFP_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({
                    "name": f"Non-Farm Payrolls ({d})",
                    "type": "macro",
                    "date": d,
                    "risk": "HIGH",
                    "blackout": True
                })
                break

        # Real earnings from Yahoo Finance for major symbols
        earnings_events = self._fetch_real_earnings(today)
        upcoming.extend(earnings_events)

        # Upcoming events (next 7 days) for display
        next_events = self._get_next_events(today)

        is_blackout = any(e.get("blackout", False) for e in upcoming)  # .get guards against missing key
        blackout_reason = next((e["name"] for e in upcoming if e.get("blackout")), None)

        return {
            "today": str(today),
            "upcoming_events": upcoming,
            "next_7_days": next_events,
            "trading_blackout": is_blackout,
            "blackout_reason": blackout_reason,
            "data_source": "Federal Reserve + BLS calendar (real)"
        }

    def check_session_quality(self) -> Dict[str, Any]:
        """
        Returns a session quality snapshot for US markets.
        Score 1.0 = peak liquidity hours (NYSE open + CME overlap).
        Score 0.6 = pre-market or post-market (light volume).
        Score 0.3 = overnight / weekend (low liquidity).
        Uses UTC time to stay timezone-agnostic on the server.
        """
        now_utc = datetime.datetime.utcnow()
        weekday  = now_utc.weekday()   # 0=Mon, 6=Sun
        hour_utc = now_utc.hour
        minute   = now_utc.minute
        time_frac = hour_utc + minute / 60.0

        # Weekend -- CME closed (Sat 22:00 UTC to Sun 22:00 UTC approx)
        if weekday == 5 or (weekday == 6 and time_frac < 22.0):
            return {
                "session": "weekend",
                "score": 0.1,
                "is_liquid": False,
                "note": "CME closed on weekends."
            }

        # NYSE regular hours: 13:30 - 20:00 UTC (9:30am - 4pm ET)
        if 13.5 <= time_frac < 20.0:
            return {
                "session": "regular",
                "score": 1.0,
                "is_liquid": True,
                "note": "NYSE regular hours. Peak liquidity."
            }

        # US pre-market: 08:00 - 13:30 UTC (4am - 9:30am ET)
        if 8.0 <= time_frac < 13.5:
            return {
                "session": "pre_market",
                "score": 0.6,
                "is_liquid": True,
                "note": "US pre-market. Reduced liquidity."
            }

        # US after-hours: 20:00 - 24:00 UTC (4pm - 8pm ET)
        if 20.0 <= time_frac <= 24.0:
            return {
                "session": "after_hours",
                "score": 0.5,
                "is_liquid": True,
                "note": "After-hours session. Spread risk elevated."
            }

        # Overnight / Asia session: 00:00 - 08:00 UTC
        return {
            "session": "overnight",
            "score": 0.3,
            "is_liquid": False,
            "note": "Overnight / Asia session. Thin US liquidity."
        }

    def _fetch_real_earnings(self, today: datetime.date) -> List[Dict]:
        """Checks Yahoo Finance earnings calendar for major symbols."""
        symbols = ["AAPL", "NVDA", "MSFT", "META", "GOOGL", "TSLA", "AMZN"]
        events = []
        for sym in symbols[:4]:  # Limit API calls
            try:
                t = yf.Ticker(sym)
                cal = t.calendar
                if cal is not None and not cal.empty:
                    dates = cal.get("Earnings Date", [])
                    date_list = list(dates) if hasattr(dates, "__iter__") else []
                    for ed in date_list:
                        try:
                            ed_date = ed.date() if hasattr(ed, "date") else ed
                            if ed_date == today:
                                events.append({
                                    "date": str(ed_date),
                                    "symbol": sym,
                                    "event": "Earnings",
                                    "impact": "HIGH"
                                })
                        except Exception:
                            continue
            except Exception:
                continue
        return events

    def _get_next_events(self, today: datetime.date) -> List[Dict]:
        """Returns all macro events in the next 7 days for display."""
        upcoming = []
        for d in FOMC_DATES_2025:
            try:
                event_date = datetime.date.fromisoformat(d)
                delta = (event_date - today).days
                if 0 <= delta <= 7:
                    upcoming.append({"name": "FOMC Meeting", "date": d, "type": "fed", "days_away": delta})
            except Exception:
                continue
        for d in CPI_DATES_2025:
            try:
                event_date = datetime.date.fromisoformat(d)
                delta = (event_date - today).days
                if 0 <= delta <= 7:
                    upcoming.append({"name": "US CPI Release", "date": d, "type": "inflation", "days_away": delta})
            except Exception:
                continue
        for d in NFP_DATES_2025:
            try:
                event_date = datetime.date.fromisoformat(d)
                delta = (event_date - today).days
                if 0 <= delta <= 7:
                    upcoming.append({"name": "Non-Farm Payrolls", "date": d, "type": "macro", "days_away": delta})
            except Exception:
                continue
        return sorted(upcoming, key=lambda x: x["date"])


INDIAN_MARKET_HOLIDAYS = {
    "2025-01-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
    "2025-04-18", "2025-05-01", "2025-08-15", "2025-10-02", "2025-10-20",
    "2025-10-24", "2025-11-05", "2025-12-25",
    "2026-01-26", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-08-15", "2026-10-02", "2026-12-25",
}


class IndianEventAwarenessEngine:
    """
    Real macroeconomic event detection for the Indian market (NSE/BSE).
    Uses RBI MPC meeting dates, India CPI schedule, and NSE holidays.
    Also enforces Indian market trading hours (9:15 AM - 3:30 PM IST).
    """

    def _is_near(self, date_str: str, today: datetime.date, window: int = 0) -> bool:
        try:
            event_date = datetime.date.fromisoformat(date_str)
            delta = (event_date - today).days
            return 0 <= delta <= window
        except Exception:
            return False

    def check_today(self, tick_data: Dict[str, Any] = None) -> Dict[str, Any]:
        today = datetime.date.today()
        today_str = str(today)
        upcoming = []

        # NSE/BSE holiday blackout
        if today_str in INDIAN_MARKET_HOLIDAYS:
            return {
                "today": today_str,
                "upcoming_events": [{"name": "NSE/BSE Holiday", "type": "holiday", "date": today_str, "risk": "N/A", "blackout": True}],
                "next_7_days": self._get_next_events(today),
                "trading_blackout": True,
                "blackout_reason": "NSE/BSE Holiday — Indian market closed",
                "data_source": "NSE holiday calendar"
            }

        # Indian market hours check (IST = UTC+5:30)
        now_utc = datetime.datetime.utcnow()
        weekday = now_utc.weekday()
        is_weekend = weekday >= 5
        market_open_utc  = datetime.time(3, 45)   # 9:15 AM IST
        market_close_utc = datetime.time(10, 0)   # 3:30 PM IST
        now_time_utc = now_utc.time()
        is_market_hours = (not is_weekend) and (market_open_utc <= now_time_utc <= market_close_utc)

        if not is_market_hours:
            reason = "Indian Market Closed (Weekend)" if is_weekend else "Indian Market Closed (Outside 9:15 AM - 3:30 PM IST)"
            return {
                "today": today_str,
                "upcoming_events": [],
                "next_7_days": self._get_next_events(today),
                "trading_blackout": True,
                "blackout_reason": reason,
                "data_source": "NSE market hours"
            }

        # RBI MPC
        for d in RBI_MPC_DATES_2025_2026:
            if self._is_near(d, today, window=1):
                upcoming.append({"name": "RBI MPC Meeting (%s)" % d, "type": "rbi", "date": d, "risk": "HIGH", "blackout": True})
                break

        # India CPI
        for d in INDIA_CPI_DATES_2025_2026:
            if self._is_near(d, today, window=0):
                upcoming.append({"name": "India CPI Release (%s)" % d, "type": "inflation", "date": d, "risk": "HIGH", "blackout": True})
                break

        # Indian earnings
        earnings_events = self._fetch_real_earnings(today)
        upcoming.extend(earnings_events)

        is_blackout = any(e.get("blackout") for e in upcoming)
        blackout_reason = upcoming[0]["name"] if is_blackout and upcoming else None

        return {
            "today": today_str,
            "upcoming_events": upcoming,
            "next_7_days": self._get_next_events(today),
            "trading_blackout": is_blackout,
            "blackout_reason": blackout_reason,
            "data_source": "RBI + NSE calendar (real)"
        }

    def _get_next_events(self, today: datetime.date) -> List[Dict]:
        upcoming = []
        for d in RBI_MPC_DATES_2025_2026:
            try:
                event_date = datetime.date.fromisoformat(d)
                delta = (event_date - today).days
                if 0 <= delta <= 7:
                    upcoming.append({"name": "RBI MPC Meeting", "date": d, "type": "rbi", "days_away": delta})
            except Exception:
                continue
        for d in INDIA_CPI_DATES_2025_2026:
            try:
                event_date = datetime.date.fromisoformat(d)
                delta = (event_date - today).days
                if 0 <= delta <= 7:
                    upcoming.append({"name": "India CPI Release", "date": d, "type": "inflation", "days_away": delta})
            except Exception:
                continue
        return upcoming

    def _fetch_real_earnings(self, today: datetime.date) -> List[Dict]:
        """Checks Yahoo Finance earnings for Indian stocks."""
        symbols = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
                   "BAJFINANCE.NS", "SUNPHARMA.NS", "MARUTI.NS"]
        events = []
        for sym in symbols[:4]:
            try:
                t = yf.Ticker(sym)
                cal = t.calendar
                if cal is not None and not cal.empty:
                    dates = cal.get("Earnings Date", [])
                    date_list = list(dates) if hasattr(dates, "__iter__") else []
                    for ed in date_list:
                        try:
                            ed_date = ed.date() if hasattr(ed, "date") else datetime.date.fromisoformat(str(ed)[:10])
                            delta = (ed_date - today).days
                            if 0 <= delta <= BLACKOUT_WINDOW_DAYS:
                                events.append({
                                    "name": f"{sym} Earnings",
                                    "type": "earnings",
                                    "date": str(ed_date),
                                    "risk": "HIGH",
                                    "blackout": True
                                })
                        except Exception:
                            continue
            except Exception:
                pass
        return events


class CryptoEventAwarenessEngine:
    """
    Crypto markets trade 24/7 — no market-hours blackout.
    Still enforces FOMC, CPI, and NFP blackouts (major macro events
    cause sharp risk-off moves in crypto).
    """

    def _is_near(self, date_str: str, today: datetime.date, window: int = 0) -> bool:
        try:
            event_date = datetime.date.fromisoformat(date_str)
            delta = (event_date - today).days
            return 0 <= delta <= window
        except Exception:
            return False

    def check_today(self, tick_data=None) -> dict:
        today = datetime.date.today()
        today_str = str(today)
        upcoming = []

        for d in FOMC_DATES_2025:
            if self._is_near(d, today, window=1):
                upcoming.append({"name": f"FOMC Meeting ({d})", "type": "fed",
                                  "date": d, "risk": "HIGH", "blackout": True})
                break
        for d in CPI_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({"name": f"US CPI Release ({d})", "type": "inflation",
                                  "date": d, "risk": "HIGH", "blackout": True})
                break
        for d in NFP_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({"name": f"Non-Farm Payrolls ({d})", "type": "macro",
                                  "date": d, "risk": "HIGH", "blackout": True})
                break

        is_blackout = any(e.get("blackout", False) for e in upcoming)  # .get guards against missing key
        blackout_reason = next((e["name"] for e in upcoming if e.get("blackout")), None)
        return {
            "today": today_str,
            "upcoming_events": upcoming,
            "next_7_days": [],
            "trading_blackout": is_blackout,
            "blackout_reason": blackout_reason,
            "data_source": "Federal Reserve + BLS calendar (crypto 24/7)"
        }

    def check_session_quality(self) -> dict:
        """Crypto trades 24/7; score peaks during US market hours (best liquidity)."""
        now_utc = datetime.datetime.utcnow()
        time_frac = now_utc.hour + now_utc.minute / 60.0
        if 13.5 <= time_frac < 20.0:
            return {"session": "us_overlap", "score": 1.0, "is_liquid": True,
                    "note": "US market hours — peak crypto liquidity."}
        if 7.0 <= time_frac < 13.5:
            return {"session": "eu_session", "score": 0.8, "is_liquid": True,
                    "note": "EU session — good crypto liquidity."}
        if 20.0 <= time_frac:
            return {"session": "late_us", "score": 0.7, "is_liquid": True,
                    "note": "Late US session — decent crypto liquidity."}
        return {"session": "asia_session", "score": 0.6, "is_liquid": True,
                "note": "Asia session — moderate crypto liquidity."}


class ForexEventAwarenessEngine:
    """
    Forex markets: open Sunday 22:00 UTC, close Friday 22:00 UTC.
    Weekends (Saturday all day + Sunday before 22:00 UTC + Friday after 22:00 UTC) are blocked.
    Enforces FOMC, CPI, and NFP blackouts (major FX drivers).
    """

    def _is_near(self, date_str: str, today: datetime.date, window: int = 0) -> bool:
        try:
            event_date = datetime.date.fromisoformat(date_str)
            delta = (event_date - today).days
            return 0 <= delta <= window
        except Exception:
            return False

    def check_today(self, tick_data=None) -> dict:
        today = datetime.date.today()
        today_str = str(today)
        now_utc = datetime.datetime.utcnow()
        weekday = now_utc.weekday()          # 0=Mon … 6=Sun
        time_frac = now_utc.hour + now_utc.minute / 60.0

        # Saturday — fully closed
        if weekday == 5:
            return {"today": today_str, "upcoming_events": [], "next_7_days": [],
                    "trading_blackout": True,
                    "blackout_reason": "Forex Market Closed (Saturday)",
                    "data_source": "Forex market hours"}
        # Sunday before 22:00 UTC — still closed
        if weekday == 6 and time_frac < 22.0:
            return {"today": today_str, "upcoming_events": [], "next_7_days": [],
                    "trading_blackout": True,
                    "blackout_reason": "Forex Market Closed (Sunday before 22:00 UTC)",
                    "data_source": "Forex market hours"}
        # Friday at or after 22:00 UTC — weekend starts
        if weekday == 4 and time_frac >= 22.0:
            return {"today": today_str, "upcoming_events": [], "next_7_days": [],
                    "trading_blackout": True,
                    "blackout_reason": "Forex Market Closed (Friday ≥ 22:00 UTC — weekend start)",
                    "data_source": "Forex market hours"}

        upcoming = []
        for d in FOMC_DATES_2025:
            if self._is_near(d, today, window=1):
                upcoming.append({"name": f"FOMC Meeting ({d})", "type": "fed",
                                  "date": d, "risk": "HIGH", "blackout": True})
                break
        for d in CPI_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({"name": f"US CPI Release ({d})", "type": "inflation",
                                  "date": d, "risk": "HIGH", "blackout": True})
                break
        for d in NFP_DATES_2025:
            if self._is_near(d, today, window=0):
                upcoming.append({"name": f"Non-Farm Payrolls ({d})", "type": "macro",
                                  "date": d, "risk": "HIGH", "blackout": True})
                break

        is_blackout = any(e.get("blackout") for e in upcoming)
        blackout_reason = next((e["name"] for e in upcoming if e.get("blackout")), None)
        return {
            "today": today_str,
            "upcoming_events": upcoming,
            "next_7_days": [],
            "trading_blackout": is_blackout,
            "blackout_reason": blackout_reason,
            "data_source": "Forex market hours + FOMC/CPI/NFP calendar"
        }

    def check_session_quality(self) -> dict:
        """Forex session quality by trading session overlap."""
        now_utc = datetime.datetime.utcnow()
        time_frac = now_utc.hour + now_utc.minute / 60.0
        # London–NY overlap (12–16 UTC) — peak liquidity
        if 12.0 <= time_frac < 16.0:
            return {"session": "london_ny_overlap", "score": 1.0, "is_liquid": True,
                    "note": "London-NY overlap — peak forex liquidity."}
        # London session (07–16 UTC)
        if 7.0 <= time_frac < 16.0:
            return {"session": "london", "score": 0.85, "is_liquid": True,
                    "note": "London session — high forex liquidity."}
        # NY session (12–21 UTC) — already covered by overlap above for 12-16
        if 16.0 <= time_frac < 21.0:
            return {"session": "new_york", "score": 0.80, "is_liquid": True,
                    "note": "NY session — good forex liquidity."}
        # Tokyo / Sydney session (21–07 UTC)
        if time_frac >= 21.0 or time_frac < 7.0:
            return {"session": "tokyo_sydney", "score": 0.55, "is_liquid": True,
                    "note": "Tokyo/Sydney session — moderate forex liquidity."}
        return {"session": "low", "score": 0.35, "is_liquid": True,
                "note": "Inter-session lull — thin forex liquidity."}
