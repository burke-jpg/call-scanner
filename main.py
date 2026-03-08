"""CLI entry point for Twilio Recording Retrieval Tool.

Architecture: Twilio-first. All call data comes directly from Twilio.
Agent identification via Flex call leg URIs (client:{agent_email_encoded}).
No GHL dependency.

Supports natural language queries:
  python main.py "George Tuesday morning"
  python main.py "last 5 calls"
  python main.py "calls with Sapochnick"
"""

import csv
import logging
import os
import sys
from datetime import date

import click
from dotenv import load_dotenv
from tabulate import tabulate

from src.agents import discover_agents, save_agents
from src.filters import apply_filters
from src.index import add_entry, load_index, save_index
from src.naming import build_filename
from src.nlp import parse_query
from src.twilio_client import TwilioClient

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("twilio-recordings")


@click.command()
@click.argument("query", required=False, default=None)
@click.option("--date", "single_date", help="Single date YYYY-MM-DD (all recordings that day)")
@click.option("--from", "date_from", help="Start of date range YYYY-MM-DD (inclusive)")
@click.option("--to", "date_to", help="End of date range YYYY-MM-DD (inclusive)")
@click.option("--time-from", help="Start time HH:MM (requires --date)")
@click.option("--time-to", help="End time HH:MM (requires --date)")
@click.option("--agent", help="Agent name filter (partial, case-insensitive)")
@click.option("--client", help="Client/contact name filter (partial, case-insensitive)")
@click.option("--phone", help="Phone number filter (from or to)")
@click.option("--direction", help="Call direction filter (inbound/outbound)")
@click.option("--output", default=None, help="Download directory (default: ./recordings)")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded, don't download")
@click.option("--list", "list_only", is_flag=True, help="Print results as table, don't download")
@click.option("--csv", "csv_path", default=None, help="Export results to CSV file")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--refresh-agents", is_flag=True, help="Scan Twilio to discover all agents, save to agents.json, then exit")
@click.option("--days", default=14, help="Days to look back when refreshing agents (default: 14)")
def main(
    query,
    single_date,
    date_from,
    date_to,
    time_from,
    time_to,
    agent,
    client,
    phone,
    direction,
    output,
    dry_run,
    list_only,
    csv_path,
    verbose,
    refresh_agents,
    days,
):
    """Twilio Recording Retrieval Tool.

    Query Twilio for calls, pair agent legs, and download recordings
    as intelligently named MP3 files.

    Supports natural language queries as a positional argument.
    Explicit flags always override NLP-parsed values.

    \b
    Examples (natural language):
      python main.py "George Tuesday morning"
      python main.py "last 5 calls"
      python main.py "Sara yesterday"
      python main.py "calls with Sapochnick"
      python main.py --list "George this week"

    \b
    Examples (flags):
      python main.py --date 2026-03-07
      python main.py --agent george --date 2026-03-06
      python main.py --client sapochnick --time-from 14:00 --time-to 17:00 --date 2026-03-06
      python main.py --from 2026-03-01 --to 2026-03-07 --dry-run
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ---- Refresh agents mode ----
    if refresh_agents:
        click.echo(f"\n  Scanning Twilio for agents (last {days} days)...")
        try:
            twilio = TwilioClient()
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
        agents_list = discover_agents(twilio, days=days)
        save_agents(agents_list)
        click.echo(f"  Discovered {len(agents_list)} agents:")
        for a in agents_list:
            click.echo(f"    - {a}")
        click.echo(f"\n  Saved to agents.json")
        sys.exit(0)

    # ---- NLP: parse natural language query, merge with flags ----
    parsed = parse_query(query, date.today())
    limit = None
    limit_from = "tail"

    if parsed.has_filters():
        # Flags override NLP-parsed values
        single_date = single_date or parsed.date
        date_from = date_from or parsed.date_from
        date_to = date_to or parsed.date_to
        time_from = time_from or parsed.time_from
        time_to = time_to or parsed.time_to
        agent = agent or parsed.agent
        client = client or parsed.client
        phone = phone or parsed.phone
        direction = direction or parsed.direction
        limit = parsed.limit
        limit_from = parsed.limit_from

        click.echo(f"\n  -> Interpreted: {parsed.summary()}")

    # Validate options
    if time_from and not single_date:
        click.echo("Error: --time-from requires --date", err=True)
        sys.exit(1)
    if time_to and not single_date:
        click.echo("Error: --time-to requires --date", err=True)
        sys.exit(1)
    if not single_date and not date_from and not date_to and not agent and not client and not phone and not direction and limit is None:
        click.echo("Error: At least one filter is required (query, --date, --from/--to, --agent, --client, --phone, or --direction)", err=True)
        sys.exit(1)

    # Resolve output dir
    download_dir = output or os.getenv("DOWNLOAD_DIR", "./recordings")

    # Determine date range for Twilio query
    query_from = single_date or date_from
    query_to = single_date or date_to or query_from

    click.echo(f"\n{'='*60}")
    click.echo("  Twilio Recording Retrieval Tool")
    click.echo(f"{'='*60}")

    # Step 1: Query Twilio for all call legs
    click.echo(f"\n[1/3] Querying Twilio for calls ({query_from} to {query_to})...")
    try:
        twilio = TwilioClient()
    except ValueError as e:
        logger.error("Twilio client init failed: %s", e)
        click.echo(f"Error: {e}", err=True)
        click.echo("  -> Make sure TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are set in .env", err=True)
        sys.exit(1)

    raw_calls = twilio.get_calls(date_from=query_from, date_to=query_to)

    if not raw_calls:
        click.echo("  No calls found for the specified date range.")
        sys.exit(0)

    click.echo(f"  -> {len(raw_calls)} call leg(s) from Twilio")

    # Pair inbound + agent legs into unified records
    records = twilio.pair_call_legs(raw_calls)
    click.echo(f"  -> {len(records)} unified call record(s) after pairing")

    # Step 2: Apply filters
    click.echo("\n[2/3] Applying filters...")
    records = apply_filters(
        records,
        date=single_date,
        date_from=date_from,
        date_to=date_to,
        time_from=time_from,
        time_to=time_to,
        agent=agent,
        client=client,
        phone=phone,
        direction=direction,
    )

    if not records:
        click.echo("\n  No records match your filters.")
        sys.exit(0)

    # Apply limit slicing (from NLP: "last 5", "first 3", etc.)
    if limit is not None and limit > 0:
        if limit_from == "head":
            records = records[:limit]
        else:
            records = records[-limit:]
        click.echo(f"  -> Limited to {len(records)} call(s) ({limit_from} {limit})")

    click.echo(f"  -> {len(records)} call(s) matched")

    # Step 3: Download or list
    if dry_run or list_only:
        _print_table(records, dry_run)
        if csv_path:
            _export_csv(records, csv_path)
        sys.exit(0)

    click.echo(f"\n[3/3] Downloading recordings to {download_dir}...")
    stats = twilio.bulk_download(records, output_dir=download_dir)

    # Update metadata index
    index_entries = stats.get("index_entries", [])
    if index_entries:
        index = load_index(download_dir)
        for entry in index_entries:
            add_entry(
                index,
                filename=entry["filename"],
                relative_path=entry["relative_path"],
                call_record=entry["record"],
                recording_sid=entry["recording_sid"],
                size_bytes=entry.get("size_bytes", 0),
            )
        save_index(download_dir, index)
        click.echo(f"  -> Index updated ({len(index_entries)} new entries)")

    # Export CSV if requested
    if csv_path:
        _export_csv(records, csv_path)

    click.echo(f"\n{'='*60}")
    click.echo("  Download Complete")
    click.echo(f"{'='*60}")
    click.echo(f"  Downloaded:    {stats['downloaded']}")
    click.echo(f"  Skipped:       {stats['skipped']}")
    click.echo(f"  No recording:  {stats['no_recording']}")
    click.echo(f"  Failed:        {stats['failed']}")
    click.echo(f"  Output dir:    {os.path.abspath(download_dir)}")
    click.echo()


def _export_csv(records: list[dict], filepath: str):
    """Export call records to a CSV file."""
    fieldnames = [
        "agent", "contact", "date", "time", "direction",
        "duration_sec", "duration_fmt", "phone_from", "phone_to",
        "call_sid", "filename",
    ]
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            duration = record.get("duration", 0) or 0
            timestamp = record.get("timestamp", "")
            date_part = timestamp[:10] if len(timestamp) >= 10 else ""
            time_part = timestamp[11:16] if len(timestamp) >= 16 else ""
            writer.writerow({
                "agent": record.get("agent_name", ""),
                "contact": record.get("contact_name", ""),
                "date": date_part,
                "time": time_part,
                "direction": record.get("direction", ""),
                "duration_sec": duration,
                "duration_fmt": f"{duration // 60}:{duration % 60:02d}" if duration else "",
                "phone_from": record.get("phone_from", ""),
                "phone_to": record.get("phone_to", ""),
                "call_sid": record.get("call_sid", ""),
                "filename": build_filename(record),
            })
    click.echo(f"  -> CSV exported: {os.path.abspath(filepath)} ({len(records)} rows)")


def _print_table(records: list[dict], show_filenames: bool = False):
    """Print call records as a formatted table."""
    headers = ["#", "Contact", "Agent", "Timestamp", "Dir", "From", "To", "Dur"]
    if show_filenames:
        headers.append("Proposed Filename")

    rows = []
    for i, record in enumerate(records, 1):
        duration = record.get("duration", 0)
        dur_str = f"{duration // 60}:{duration % 60:02d}" if duration else "-"
        row = [
            i,
            record.get("contact_name", "")[:25],
            record.get("agent_name", "")[:15],
            record.get("timestamp", "")[:19],
            record.get("direction", "")[:3],
            record.get("phone_from", "")[-10:],
            record.get("phone_to", "")[-10:],
            dur_str,
        ]
        if show_filenames:
            row.append(build_filename(record))
        rows.append(row)

    click.echo()
    click.echo(tabulate(rows, headers=headers, tablefmt="simple"))
    click.echo(f"\n  Total: {len(records)} call(s)")


if __name__ == "__main__":
    main()
