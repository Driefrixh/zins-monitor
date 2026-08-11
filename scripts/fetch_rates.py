#!/usr/bin/env python3
"""
Zins-Monitor
============
Holt die Zinsstrukturkurve der EZB (AAA-Euro-Staatsanleihen, praktisch
deckungsgleich mit der Bundesanleihe), berechnet Veraenderungen ueber
verschiedene Zeitraeume und schreibt:

    data/latest.json   -> Anzeige (Scriptable-Widget)
    data/history.csv   -> langfristige Zeitreihe
    data/state.json    -> merkt sich den zuletzt gemeldeten Handelstag

Optional wird eine Push-Nachricht ueber ntfy verschickt.
Benoetigt keinerlei externe Pakete - nur Python-Standardbibliothek.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

ECB_BASE = "https://data-api.ecb.europa.eu/service/data/YC"

# Serien-IDs der EZB-Zinsstrukturkurve (letzte Schluesselkomponente)
SERIES = {
    "SR_2Y": "2 Jahre",
    "SR_5Y": "5 Jahre",
    "SR_10Y": "10 Jahre",
    "SR_30Y": "30 Jahre",
}

# B = werktaeglich, U2 = Euroraum, G_N_A = Staatsanleihen mit Triple-A-Rating
SERIES_KEY = "B.U2.EUR.4F.G_N_A.SV_C_YM." + "+".join(SERIES)

LEAD = "SR_10Y"           # Leitwert fuer Ueberschrift und Sparkline
LOOKBACK_DAYS = 430       # Historie, die pro Lauf von der EZB geholt wird
SPARK_POINTS = 90         # Punkte fuer die Sparkline im Widget

DATA_DIR = Path("data")
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.csv"
STATE_FILE = DATA_DIR / "state.json"

# Ab dieser Tagesveraenderung (in Basispunkten) wird die Nachricht als
# Alarm markiert.
ALERT_BP = float(os.environ.get("ALERT_BP", "10"))

# Vergleichszeitraeume: Label -> Anzahl Kalendertage zurueck
HORIZONS = {
    "1T": 1,
    "1W": 7,
    "1M": 30,
    "3M": 91,
    "1J": 365,
}


# --------------------------------------------------------------------------
# Datenabruf
# --------------------------------------------------------------------------

def fetch_series() -> dict[str, dict[str, float]]:
    """Laedt die Serien von der EZB. Rueckgabe: {serie: {datum: wert}}."""
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    query = urllib.parse.urlencode({"startPeriod": start, "format": "csvdata"})
    url = f"{ECB_BASE}/{SERIES_KEY}?{query}"

    req = urllib.request.Request(
        url,
        headers={"Accept": "text/csv", "User-Agent": "zins-monitor/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8-sig")

    out: dict[str, dict[str, float]] = {sid: {} for sid in SERIES}

    for row in csv.DictReader(io.StringIO(raw)):
        # Serien-ID entweder aus der Spalte KEY (letzte Komponente)
        # oder aus der Dimensionsspalte DATA_TYPE_FM ableiten.
        sid = (row.get("KEY") or "").split(".")[-1]
        if sid not in SERIES:
            sid = (row.get("DATA_TYPE_FM") or "").strip()
        if sid not in SERIES:
            continue

        day = (row.get("TIME_PERIOD") or "").strip()
        val = (row.get("OBS_VALUE") or "").strip()
        if not day or not val:
            continue
        try:
            out[sid][day] = float(val)
        except ValueError:
            continue

    if not out.get(LEAD):
        raise SystemExit("Keine Daten fuer die Leitserie erhalten - "
                         "Serienschluessel oder API-Antwort pruefen.")
    return out


# --------------------------------------------------------------------------
# Historie
# --------------------------------------------------------------------------

def merge_history(fresh: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Fuehrt neue Daten mit der bereits gespeicherten CSV zusammen."""
    merged: dict[str, dict[str, float]] = {}

    if HISTORY_FILE.exists():
        with HISTORY_FILE.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                day = row.get("date")
                if not day:
                    continue
                merged[day] = {
                    sid: float(row[sid])
                    for sid in SERIES
                    if row.get(sid) not in (None, "")
                }

    for sid, points in fresh.items():
        for day, val in points.items():
            merged.setdefault(day, {})[sid] = val

    return merged


def write_history(merged: dict[str, dict[str, float]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", *SERIES])
        for day in sorted(merged):
            row = merged[day]
            writer.writerow([
                day,
                *[f"{row[sid]:.4f}" if sid in row else "" for sid in SERIES],
            ])


# --------------------------------------------------------------------------
# Auswertung
# --------------------------------------------------------------------------

def value_at_or_before(points: list[tuple[str, float]], target: str):
    """Letzter verfuegbarer Wert an oder vor dem Zieldatum (Feiertage!)."""
    candidates = [v for d, v in points if d <= target]
    return candidates[-1] if candidates else None


def build_payload(merged: dict[str, dict[str, float]]) -> dict:
    per_series = {
        sid: sorted((d, vals[sid]) for d, vals in merged.items() if sid in vals)
        for sid in SERIES
    }

    last_day = per_series[LEAD][-1][0]
    ref = datetime.strptime(last_day, "%Y-%m-%d").date()

    series_out = {}
    for sid, points in per_series.items():
        if not points:
            continue
        current = points[-1][1]
        deltas = {}
        for label, days in HORIZONS.items():
            target = (ref - timedelta(days=days)).isoformat()
            past = value_at_or_before(points, target)
            if past is not None:
                deltas[label] = round((current - past) * 100, 1)  # Basispunkte
        series_out[sid] = {
            "label": SERIES[sid],
            "value": round(current, 3),
            "deltas": deltas,
        }

    spark = per_series[LEAD][-SPARK_POINTS:]

    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": last_day,
        "source": "EZB Data Portal - Zinsstrukturkurve AAA-Staatsanleihen Euroraum",
        "unit": "Prozent p.a.",
        "lead": LEAD,
        "series": series_out,
        "spark": {
            "dates": [d for d, _ in spark],
            "values": [round(v, 3) for _, v in spark],
        },
    }

    if "SR_10Y" in series_out and "SR_2Y" in series_out:
        payload["spread_10y_2y"] = round(
            series_out["SR_10Y"]["value"] - series_out["SR_2Y"]["value"], 3
        )

    return payload


# --------------------------------------------------------------------------
# Benachrichtigung
# --------------------------------------------------------------------------

def de(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def arrow(bp: float) -> str:
    if bp > 0.5:
        return "\u25b2"   # nach oben
    if bp < -0.5:
        return "\u25bc"   # nach unten
    return "\u25ac"       # unveraendert


def signed_bp(bp: float) -> str:
    if bp > 0:
        sign = "+"
    elif bp < 0:
        sign = "\u2212"
    else:
        sign = "\u00b1"
    return f"{sign}{de(abs(bp), 1)} Bp"


def build_message(payload: dict) -> tuple[str, str, bool]:
    """Liefert (Titel, Nachrichtentext, Alarm-Flag) als reinen Text."""
    lead = payload["series"][payload["lead"]]
    day = datetime.strptime(payload["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
    d1 = lead["deltas"].get("1T", 0.0)
    is_alert = abs(d1) >= ALERT_BP

    title = f"{arrow(d1)} 10J: {de(lead['value'])} %  ({signed_bp(d1)})"
    if is_alert:
        title = "Deutliche Zinsbewegung \u00b7 " + title

    lines = [f"Renditen AAA-Staatsanleihen \u00b7 {day}", ""]

    order = ["1W", "1M", "3M", "1J"]
    parts = [f"{h} {signed_bp(lead['deltas'][h])}"
             for h in order if h in lead["deltas"]]
    if parts:
        lines.append("10 Jahre: " + "   ".join(parts))
        lines.append("")

    for sid, info in payload["series"].items():
        if sid == payload["lead"]:
            continue
        bp = info["deltas"].get("1T", 0.0)
        lines.append(
            f"{info['label']:>9}   {de(info['value'])} %   ({signed_bp(bp)})"
        )

    if "spread_10y_2y" in payload:
        lines.append("")
        lines.append(f"Spread 10J\u22122J: {de(payload['spread_10y_2y'])} Pp")

    return title, "\n".join(lines), is_alert


def send_ntfy(title: str, text: str, payload: dict, is_alert: bool) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    # Nicht gesetzte GitHub-Secrets kommen als leerer String an, nicht als None
    server = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")

    if not topic:
        print("Kein NTFY_TOPIC gesetzt - Nachricht nur in der Konsole:")
        print(f"{title}\n{text}")
        return

    lead = payload["series"][payload["lead"]]
    d1 = lead["deltas"].get("1T", 0.0)
    if is_alert:
        tag = "warning"
    elif d1 > 0.5:
        tag = "chart_with_upwards_trend"
    elif d1 < -0.5:
        tag = "chart_with_downwards_trend"
    else:
        tag = "left_right_arrow"

    body = json.dumps({
        "topic": topic,
        "title": title,
        "message": text,
        # 2 = leise zustellen, 4 = mit Ton und Vibration
        "priority": 4 if is_alert else 2,
        "tags": [tag],
        "click": "https://data.ecb.europa.eu/data/datasets/YC/"
                 "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
    }, ensure_ascii=False).encode("utf-8")

    headers = {"Content-Type": "application/json; charset=utf-8"}
    token = os.environ.get("NTFY_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(server + "/", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        print("ntfy-Nachricht verschickt.")
    except Exception as exc:                      # noqa: BLE001
        print(f"ntfy-Versand fehlgeschlagen: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------

def main() -> None:
    fresh = fetch_series()
    merged = merge_history(fresh)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_history(merged)

    payload = build_payload(merged)
    LATEST_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Stand {payload['date']}: "
          f"10J = {payload['series'][LEAD]['value']} %")

    # An Feiertagen / vor der Veroeffentlichung liefert die EZB denselben
    # Tag noch einmal - dann keine zweite Nachricht schicken.
    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    force = os.environ.get("FORCE_NOTIFY", "").lower() in ("1", "true", "yes")
    if state.get("last_notified") == payload["date"] and not force:
        print("Kein neuer Handelstag - keine Benachrichtigung.")
        return

    title, text, is_alert = build_message(payload)
    send_ntfy(title, text, payload, is_alert)

    state["last_notified"] = payload["date"]
    STATE_FILE.write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
