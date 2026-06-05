#!/usr/bin/env python3
"""
Yahoo SMTP email sender.

Sends randomly selected drafts from the drafts/ folder via Yahoo SMTP.
Each email's subject is suffixed with [runId:<id>] [<uuid>] to identify
the run and individual email instance.

Usage:
    # Mode 1: Send N emails concurrently
    python yahoo_smtp_send.py concurrent --count 5 --to recipient@example.com

    # Mode 2: Send N batches (each batch 1-5 emails, random 0.5-30s delay between batches)
    python yahoo_smtp_send.py batch --batches 3 --to recipient@example.com

Environment (.env):
    SMTP_EMAIL     - Yahoo email address
    SMTP_PASSWORD  - Yahoo app password
"""

import argparse
import concurrent.futures
import json
import os
import random
import smtplib
import ssl
import sys
import threading
import time
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SMTP_HOST = "smtp.mail.yahoo.com"
SMTP_PORT = 465  # SSL/TLS

SCRIPT_DIR = Path(__file__).parent
DRAFTS_DIR = SCRIPT_DIR / "drafts"
ENV_FILE = SCRIPT_DIR / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Parse .env and populate os.environ (existing vars are not overwritten)."""
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_drafts() -> list[dict]:
    """Return all drafts from drafts/*.json as a list of {subject, body} dicts."""
    drafts = []
    for path in sorted(DRAFTS_DIR.glob("*.json")):
        with open(path) as f:
            drafts.append(json.load(f))
    if not drafts:
        print(f"Error: no draft files found in {DRAFTS_DIR}", file=sys.stderr)
        sys.exit(1)
    return drafts


def pick_draft(drafts: list[dict], run_id: str) -> tuple[str, str, str]:
    """
    Pick a random draft and return (subject_with_ids, body, instance_uuid).
    Subject format: <original subject> [runId:<run_id>] [<instance_uuid>]
    """
    draft = random.choice(drafts)
    instance_id = str(uuid.uuid4())
    subject = f"{draft['subject']} [runId:{run_id}] [{instance_id}]"
    return subject, draft["body"], instance_id


RETRY_COUNT = 3  # attempts after the first failure
RETRY_BACKOFF = 60.0  # seconds; doubles each attempt: 60 → 120 → 240


def send_one(
    smtp_email: str, smtp_password: str, to: str, subject: str, body: str
) -> None:
    """Open a fresh SMTP_SSL connection and send one email. Raises on failure."""
    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, to, msg.as_string())


def send_with_retry(
    smtp_email: str,
    smtp_password: str,
    to: str,
    subject: str,
    body: str,
    retries: int = RETRY_COUNT,
    backoff: float = RETRY_BACKOFF,
) -> None:
    """Call send_one, retrying on failure with exponential backoff. Raises after all attempts."""
    for attempt in range(retries + 1):
        try:
            send_one(smtp_email, smtp_password, to, subject, body)
            return
        except Exception as exc:
            if attempt == retries:
                raise
            wait = backoff * (2**attempt)
            print(
                f"      [retry {attempt + 1}/{retries}] {exc} — waiting {wait:.0f}s..."
            )
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


MAX_CONNECTIONS = 3  # Yahoo safe default; override with --max-connections


MAX_SEND_DELAY = 2.0  # seconds between sends per connection slot; override with --delay


def mode_concurrent(
    smtp_email: str,
    smtp_password: str,
    to: str,
    drafts: list[dict],
    count: int,
    max_connections: int,
    delay: float,
    retries: int,
    retry_backoff: float,
) -> tuple[int, int]:
    """Send `count` emails in parallel, capped at `max_connections` simultaneous SMTP connections."""
    run_id = str(uuid.uuid4())[:8]
    print(
        f"[concurrent] runId={run_id}  count={count}  max_connections={max_connections}  delay={delay}s  to={to}"
    )

    emails = [pick_draft(drafts, run_id) for _ in range(count)]
    sem = threading.Semaphore(max_connections)

    def worker(subject: str, body: str, instance_id: str) -> tuple[str, bool, str]:
        with sem:
            try:
                send_with_retry(
                    smtp_email,
                    smtp_password,
                    to,
                    subject,
                    body,
                    retries=retries,
                    backoff=retry_backoff,
                )
                if delay > 0:
                    time.sleep(delay)
                return instance_id, True, ""
            except Exception as exc:
                return instance_id, False, str(exc)

    sent = failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
        futures = {
            pool.submit(worker, subject, body, instance_id): instance_id
            for subject, body, instance_id in emails
        }
        # Print results as they complete
        for future in concurrent.futures.as_completed(futures):
            instance_id, ok, err = future.result()
            # Find the original subject for display
            orig_subject = next(s for s, _, iid in emails if iid == instance_id)
            tag = "OK  " if ok else f"FAIL ({err})"
            print(f"  [{instance_id[:8]}] {tag}  {orig_subject[:70]}")
            if ok:
                sent += 1
            else:
                failed += 1

    print(f"\nDone. {sent} sent, {failed} failed.")
    return sent, failed


def mode_batch(
    smtp_email: str,
    smtp_password: str,
    to: str,
    drafts: list[dict],
    num_batches: int,
    retries: int,
    retry_backoff: float,
) -> tuple[int, int]:
    """Send `num_batches` batches; each batch has 1-5 emails; random 0.5-30s delay between batches."""
    run_id = str(uuid.uuid4())[:8]
    print(f"[batch] runId={run_id}  batches={num_batches}  to={to}")

    total_sent = total_failed = 0

    for batch_idx in range(1, num_batches + 1):
        batch_size = random.randint(1, 5)
        print(
            f"\n  Batch {batch_idx}/{num_batches}  ({batch_size} email{'s' if batch_size > 1 else ''})"
        )

        for i in range(1, batch_size + 1):
            subject, body, instance_id = pick_draft(drafts, run_id)
            try:
                send_with_retry(
                    smtp_email,
                    smtp_password,
                    to,
                    subject,
                    body,
                    retries=retries,
                    backoff=retry_backoff,
                )
                print(f"    [{i}/{batch_size}] OK   [{instance_id[:8]}] {subject[:65]}")
                total_sent += 1
            except Exception as exc:
                print(
                    f"    [{i}/{batch_size}] FAIL [{instance_id[:8]}] {subject[:55]} — {exc}"
                )
                total_failed += 1

        if batch_idx < num_batches:
            delay = random.uniform(0.5, 30.0)
            print(f"  Waiting {delay:.1f}s before next batch...")
            time.sleep(delay)

    print(f"\nDone. {total_sent} sent, {total_failed} failed.")
    return total_sent, total_failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--to", required=True, metavar="EMAIL", help="Recipient email address"
    )
    parent.add_argument(
        "--retries",
        type=int,
        default=RETRY_COUNT,
        metavar="N",
        help=f"Retry attempts per email after a failure (default: {RETRY_COUNT})",
    )
    parent.add_argument(
        "--retry-backoff",
        type=float,
        default=RETRY_BACKOFF,
        metavar="SECONDS",
        dest="retry_backoff",
        help=f"Base backoff in seconds between retries, doubles each attempt (default: {RETRY_BACKOFF})",
    )

    parser = argparse.ArgumentParser(
        description="Send Yahoo SMTP emails from the drafts/ folder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python yahoo_smtp_send.py concurrent --count 5 --to inbox@example.com
  python yahoo_smtp_send.py batch --batches 4 --to inbox@example.com
""",
    )

    sub = parser.add_subparsers(dest="mode", required=True)

    p_concurrent = sub.add_parser(
        "concurrent",
        parents=[parent],
        help="Send N emails simultaneously",
    )
    p_concurrent.add_argument(
        "--count",
        type=int,
        default=5,
        metavar="N",
        help="Number of emails to send in parallel (default: 5)",
    )
    p_concurrent.add_argument(
        "--max-connections",
        type=int,
        default=MAX_CONNECTIONS,
        metavar="N",
        dest="max_connections",
        help=f"Max simultaneous SMTP connections (default: {MAX_CONNECTIONS})",
    )
    p_concurrent.add_argument(
        "--delay",
        type=float,
        default=MAX_SEND_DELAY,
        metavar="SECONDS",
        help=f"Seconds to wait after each send before releasing the connection slot (default: {MAX_SEND_DELAY})",
    )

    p_batch = sub.add_parser(
        "batch",
        parents=[parent],
        help="Send batches of 1-5 emails with random delays between batches",
    )
    p_batch.add_argument(
        "--batches",
        type=int,
        default=3,
        metavar="N",
        help="Number of batches to send (default: 3)",
    )

    return parser


def main() -> None:
    load_env()

    smtp_email = os.environ.get("SMTP_EMAIL", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")

    missing = [v for v in ("SMTP_EMAIL", "SMTP_PASSWORD") if not os.environ.get(v)]
    if missing:
        print(
            f"Error: {' and '.join(missing)} not set in .env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    drafts = load_drafts()
    args = build_parser().parse_args()

    if args.mode == "concurrent":
        sent, failed = mode_concurrent(
            smtp_email,
            smtp_password,
            args.to,
            drafts,
            args.count,
            args.max_connections,
            args.delay,
            args.retries,
            args.retry_backoff,
        )
    else:
        sent, failed = mode_batch(
            smtp_email,
            smtp_password,
            args.to,
            drafts,
            args.batches,
            args.retries,
            args.retry_backoff,
        )

    print(f"Total emails sent: {sent} / {sent + failed}")


if __name__ == "__main__":
    main()
