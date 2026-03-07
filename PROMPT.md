# Call Scanner — Starter Prompt

Paste this into any new Claude session to give it full context on how to use the call scanner.

---

## Prompt

You have access to a CLI tool called `scan` that queries Twilio call logs for Jump Contact. It's at `PLATFORM/tools/call-scanner/` and is in the Windows PATH.

### Usage

```bash
scan "George Tuesday morning"        # agent + day + time
scan "Sara yesterday"                # agent + relative date
scan "William this week"             # agent + date range
scan "last 5 calls"                  # limit
scan "outbound Monday"              # direction + day
scan --list "George this week"       # table only, no download
scan --csv ~/Desktop/out.csv "Sara"  # export CSV
scan --dry-run "last 10"             # preview filenames
```

### How It Works

1. Queries Twilio for all call legs in a date range
2. Pairs inbound + agent legs (matched by trunk + 30s window)
3. Filters by agent, date, time, direction, phone
4. Outputs table, CSV, or downloads MP3 recordings

### NLP Token Priority

Tokens are classified in this order:
1. Direction — `inbound`, `outbound`
2. Limits — `last 5`, `first 3`
3. Agent — george, sara, omar, danny, ian, chris, burke, william
4. Time — `morning` (6-12), `afternoon` (12-17), `evening` (17-22)
5. Date — `today`, `yesterday`, weekday names, `this/last week`, ISO dates
6. Phone — 7+ digits
7. Remainder — client filter (phone number match)

### Key Facts

- Agents are identified from Twilio Flex `client:` URIs — NOT GHL
- Client = phone number. No name resolution.
- Flags always override NLP: `scan --agent george --date 2026-03-06`
- `.env` must exist at the tool root with `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
- Known agents list can be overridden via `KNOWN_AGENTS` env var

### Web UI

Run the web interface:
```bash
cd PLATFORM/tools/call-scanner
python app.py
```
Opens at http://localhost:5000 — type any natural language query, see results, download MP3s.
