# Call Scanner

Query Twilio for call recordings using natural language, pair agent legs, and download as intelligently named MP3 files.

## Setup

```bash
cd PLATFORM/tools/call-scanner
pip install -r requirements.txt
```

`.env` file:
```
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
DOWNLOAD_DIR=./recordings
KNOWN_AGENTS=george,sara,omar,danny,ian,chris,burke
```

## Quick Examples

```bash
# Natural language queries
python main.py "George Tuesday morning"
python main.py "last 5 calls"
python main.py "Sara yesterday"
python main.py "calls with Sapochnick"
python main.py "outbound danny friday afternoon"

# List mode (no download)
python main.py --list "George this week"

# Dry run (show proposed filenames)
python main.py --dry-run "last 10"

# Explicit flags (override NLP)
python main.py --date 2026-03-06 --agent george
python main.py --from 2026-03-01 --to 2026-03-07 --direction inbound
python main.py --client sapochnick --date 2026-03-06 --time-from 14:00 --time-to 17:00
```

## File Naming Pattern

```
{agent}_{date}_{time}_{direction}_{contact}_{sid-prefix}.mp3
```

Example: `george_2026-03-06_2005_in_4037761148_af89c.mp3`

- **Agent first** — files sort by agent naturally
- **Date + time** — chronological within agent
- **Direction** — `in` / `out`
- **Contact** — phone number or cleaned name
- **SID prefix** — 5 chars for uniqueness

## Folder Structure

```
recordings/
├── index.json                  ← Metadata index (auto-updated)
├── 2026-03-06/
│   ├── george_2026-03-06_1432_in_sapochnick-law_b3f9a.mp3
│   └── george_2026-03-06_2005_in_4037761148_af89c.mp3
└── 2026-03-07/
    └── sara_2026-03-07_0912_in_ttn-law_qb2e1.mp3
```

Files are organized into **date subfolders**. The `index.json` sidecar tracks every download with full metadata (agent, client, date, time, direction, duration, phone numbers, SIDs).

## NLP Query Reference

| Token | Interpretation |
|-------|---------------|
| `george`, `sara`, `omar`, `danny`, `ian`, `chris`, `burke` | Agent filter |
| `today`, `yesterday` | Single date |
| `monday`..`sunday`, `mon`..`sun` | Most recent occurrence |
| `last tuesday` | Previous week's Tuesday |
| `this week` | Monday through today |
| `last week` | Previous Monday-Sunday |
| `2026-03-05` | Exact ISO date |
| `morning` | 06:00-12:00 |
| `afternoon` | 12:00-17:00 |
| `evening` | 17:00-22:00 |
| `night` | 17:00-23:59 |
| `inbound`, `outbound` | Direction filter |
| `last 5`, `first 3`, `latest 10` | Limit results |
| Anything else | Client/contact name filter |

Explicit `--flags` always override NLP-parsed values.

## CLI Flags

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Single date (all recordings that day) |
| `--from YYYY-MM-DD` | Start of date range (inclusive) |
| `--to YYYY-MM-DD` | End of date range (inclusive) |
| `--time-from HH:MM` | Start time (requires `--date`) |
| `--time-to HH:MM` | End time (requires `--date`) |
| `--agent NAME` | Agent name filter (partial, case-insensitive) |
| `--client NAME` | Client/contact filter (partial, case-insensitive) |
| `--phone NUMBER` | Phone number filter (from or to) |
| `--direction DIR` | `inbound` or `outbound` |
| `--output DIR` | Download directory (default: `./recordings`) |
| `--list` | Print table only, don't download |
| `--dry-run` | Show proposed filenames, don't download |
| `-v` / `--verbose` | Debug logging |

## Architecture

Twilio-first. All call data comes directly from Twilio API.

Agent identification via Flex call leg URIs (`client:{agent_email_encoded}`). Two legs per answered call are paired by trunk number + timing window (30s). No GHL dependency.

```
main.py              CLI entry point (click + NLP)
src/nlp.py           Natural language query parser
src/twilio_client.py  Twilio API client + leg pairing + downloads
src/filters.py       Date/time/agent/client/direction filtering
src/naming.py        MP3 file naming logic
src/index.py         JSON metadata index manager
```

## Tests

```bash
python -m pytest -v                       # All tests
python -m pytest tests/test_nlp.py -v     # NLP parser only
```
