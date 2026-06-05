# Send Emails in Batches — SMTP Test Script

Sends randomly selected emails from the `drafts/` folder via Yahoo SMTP. Each email's subject is suffixed with `[runId:<id>] [<uuid>]` so individual sends can be correlated across runs.

## Prerequisites

- Python 3.10+ — no `pip install` required, the script uses only the standard library
- A Yahoo account with SMTP access enabled

## Setup

### 1. Get a Yahoo app password

Yahoo requires an app-specific password for SMTP; your regular account password will not work.

1. Sign in to your Yahoo account and go to **Account Security**: https://login.yahoo.com/account/security
2. Enable **2-Step Verification** if it is not already on (app passwords require it).
3. Scroll down to **Generate app password** (or go to **Manage app passwords**).
4. Choose **Other app**, enter a label (e.g. `smtp-test`), and click **Generate**.
5. Copy the 16-character password shown — you will not be able to view it again.

### 2. Configure credentials

Copy `.env-example` to `.env` and fill in your details:

```bash
cp .env-example .env
```

```dotenv
SMTP_EMAIL="you@yahoo.com"
SMTP_PASSWORD="xxxx xxxx xxxx xxxx"   # the 16-char app password from step 1
```

## Usage

### Mode 1 — concurrent

Sends N emails in parallel, capped at a configurable number of simultaneous SMTP connections.

```bash
python yahoo_smtp_send.py concurrent --count 5 --to recipient@example.com
```

| Flag | Default | Description |
|---|---|---|
| `--count N` | 5 | Total emails to send |
| `--max-connections N` | 3 | Max simultaneous SMTP connections |
| `--delay SECONDS` | 2.0 | Wait after each send before releasing the connection slot |
| `--to EMAIL` | required | Recipient address |
| `--retries N` | 3 | Retry attempts per email after a failure |
| `--retry-backoff SECONDS` | 60 | Base backoff between retries (doubles each attempt) |

### Mode 2 — batch

Sends N batches. Each batch contains 1–5 randomly sized emails, with a random 0.5–30 s delay between batches. Useful for simulating realistic inbox activity over time.

```bash
python yahoo_smtp_send.py batch --batches 4 --to recipient@example.com
```

| Flag | Default | Description |
|---|---|---|
| `--batches N` | 3 | Number of batches to send |
| `--to EMAIL` | required | Recipient address |
| `--retries N` | 3 | Retry attempts per email after a failure |
| `--retry-backoff SECONDS` | 60 | Base backoff between retries (doubles each attempt) |

## Drafts

The `drafts/` folder contains 50 pre-written email templates (`01.json` – `50.json`). Each file is a JSON object with `subject` and `body` fields. The script picks drafts at random and appends run/instance identifiers to the subject line so you can track them in the recipient inbox.

You can add, remove, or edit draft files freely — any `*.json` file in `drafts/` is picked up automatically.
