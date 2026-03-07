"""Web UI for Call Scanner — query Twilio calls with natural language."""

import io
import os
import sys
import zipfile

from flask import Flask, Response, jsonify, request, send_from_directory

# Ensure src/ is importable
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date

import requests as http_requests
from dotenv import load_dotenv

from src.filters import apply_filters
from src.nlp import parse_query
from src.twilio_client import TwilioClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__, static_folder="static")

# Lazy-init Twilio client (fails fast if creds missing)
_twilio: TwilioClient | None = None


def get_twilio() -> TwilioClient:
    global _twilio
    if _twilio is None:
        _twilio = TwilioClient()
    return _twilio


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query is required", "results": [], "count": 0}), 400

    parsed = parse_query(q, date.today())

    # Determine date range for Twilio
    query_from = parsed.date or parsed.date_from
    query_to = parsed.date or parsed.date_to or query_from

    # Default to today if no date extracted
    if not query_from:
        query_from = date.today().isoformat()
        query_to = query_from

    try:
        twilio = get_twilio()
    except ValueError as e:
        return jsonify({"error": str(e), "results": [], "count": 0}), 500

    # Query Twilio
    raw = twilio.get_calls(date_from=query_from, date_to=query_to)
    records = twilio.pair_call_legs(raw)

    # Apply filters
    records = apply_filters(
        records,
        date=parsed.date,
        date_from=parsed.date_from,
        date_to=parsed.date_to,
        time_from=parsed.time_from,
        time_to=parsed.time_to,
        agent=parsed.agent,
        client=parsed.client,
        phone=parsed.phone,
        direction=parsed.direction,
    )

    # Apply limit
    if parsed.limit and parsed.limit > 0:
        if parsed.limit_from == "head":
            records = records[: parsed.limit]
        else:
            records = records[-parsed.limit :]

    # Format for frontend
    results = []
    for r in records:
        dur = r.get("duration", 0) or 0
        ts = r.get("timestamp", "")
        results.append(
            {
                "agent": r.get("agent_name", "") or "Unknown",
                "client": r.get("contact_name", ""),
                "timestamp": ts[:19] if len(ts) >= 19 else ts,
                "date": ts[:10] if len(ts) >= 10 else "",
                "time": ts[11:16] if len(ts) >= 16 else "",
                "direction": r.get("direction", ""),
                "duration": f"{dur // 60}:{dur % 60:02d}" if dur else "-",
                "duration_sec": dur,
                "phone_from": r.get("phone_from", ""),
                "phone_to": r.get("phone_to", ""),
                "call_sid": r.get("call_sid", ""),
                "agent_sid": r.get("agent_sid", ""),
            }
        )

    return jsonify(
        {
            "interpreted": parsed.summary(),
            "query": q,
            "count": len(results),
            "results": results,
        }
    )


@app.route("/api/recording/<call_sid>")
def recording(call_sid: str):
    """Find and stream the MP3 recording for a call."""
    twilio = get_twilio()

    # Find recording SID (try the call_sid, then agent_sid if passed)
    agent_sid = request.args.get("agent_sid", "")
    recordings = twilio.get_recordings_for_call(call_sid)
    if not recordings and agent_sid:
        recordings = twilio.get_recordings_for_call(agent_sid)

    if not recordings:
        return jsonify({"error": "No recording found for this call"}), 404

    rec_sid = recordings[0]["recording_sid"]

    # Proxy the Twilio MP3 stream
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{twilio.account_sid}"
        f"/Recordings/{rec_sid}.mp3"
    )

    resp = http_requests.get(
        url,
        auth=(twilio.account_sid, twilio.auth_token),
        stream=True,
        timeout=120,
    )

    if resp.status_code != 200:
        return jsonify({"error": f"Twilio returned {resp.status_code}"}), 502

    return Response(
        resp.iter_content(chunk_size=8192),
        content_type="audio/mpeg",
        headers={
            "Content-Disposition": f"attachment; filename={rec_sid}.mp3",
        },
    )


@app.route("/api/download-all", methods=["POST"])
def download_all():
    """Download multiple recordings as a ZIP file."""
    data = request.get_json(silent=True) or {}
    calls = data.get("calls", [])
    if not calls:
        return jsonify({"error": "No calls provided"}), 400

    twilio = get_twilio()
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in calls:
            call_sid = c.get("call_sid", "")
            agent_sid = c.get("agent_sid", "")
            label = c.get("label", call_sid)
            if not call_sid:
                continue

            recordings = twilio.get_recordings_for_call(call_sid)
            if not recordings and agent_sid:
                recordings = twilio.get_recordings_for_call(agent_sid)
            if not recordings:
                continue

            rec_sid = recordings[0]["recording_sid"]
            url = (
                f"https://api.twilio.com/2010-04-01/Accounts/{twilio.account_sid}"
                f"/Recordings/{rec_sid}.mp3"
            )
            resp = http_requests.get(
                url,
                auth=(twilio.account_sid, twilio.auth_token),
                timeout=120,
            )
            if resp.status_code == 200:
                zf.writestr(f"{label}.mp3", resp.content)

    buf.seek(0)
    return Response(
        buf.getvalue(),
        content_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=recordings.zip"},
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"\n  Call Scanner Web UI -> http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=True)
