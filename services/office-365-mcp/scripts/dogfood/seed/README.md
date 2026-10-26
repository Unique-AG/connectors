# Seed for the dogfood test tenant

`seed.py` puts synthetic mail, folders, events and OneDrive files into three test mailboxes. Every
string and every file comes from `corpus/`. The seed tags each item. Because of the tag, a second
`apply` creates nothing, and `cleanup` deletes only the items the seed made.

The recorder in `tests/e2e/recording/` records scenarios against Mia's mailbox. It keeps only text
that is in this corpus.

## Personas

Mia Keller (main persona), Anna Meier and Tom Berger. The tenant addresses are in no file. You give
them in `SEED_UPNS`, in the order Mia, Anna, Tom. Use a mailbox with little other mail for Mia. The
recorder replaces any text that is not seed text, but unknown mail still changes counts and order.

## Files

| File | Job |
| --- | --- |
| `corpus/*.yaml` | The only source of the strings the seed creates |
| `seed.py` | `plan` (default), `apply`, `cleanup`, `corpus` |
| `verify.py` | Read-only summary of one mailbox: counts, threads, folders, events, OneDrive root |
| `docgen.py` | Makes the docx, xlsx and PDF bytes with the standard library (fixed bytes, stable SHA-256) |
| `test_seed.py` | Offline tests against a fake Graph |
| `../get_token.py` | Device-code sign-in. The sign-in text goes to stderr and the token to stdout only |
| `../run_all.sh` | `verify`, `apply`, `cleanup-dry` or `cleanup` for the three personas in one command |

## Before you run

1. The Entra app registration has "Allow public client flows" = Yes. The device-code flow needs it.
2. The app has these delegated permissions with consent: Mail.ReadWrite, Calendars.ReadWrite,
   Contacts.ReadWrite, Files.ReadWrite, Files.Read.All, Sites.Read.All and User.Read.
3. `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` and `SEED_UPNS` are set in your shell. Do not put a client
   secret in the environment.

## Run

Run from `services/office-365-mcp`.

```sh
export SEED_UPNS="<Mia UPN>,<Anna UPN>,<Tom UPN>"
.venv/bin/python scripts/dogfood/seed/seed.py plan      # sends no request
scripts/dogfood/run_all.sh apply
scripts/dogfood/run_all.sh verify
scripts/dogfood/run_all.sh cleanup-dry
scripts/dogfood/run_all.sh cleanup
```

Each persona signs in once. `get_token.py` keeps a refresh token in
`~/.cache/dogfood-graph/msal.json` (mode 600), and later runs ask for no sign-in. Delete that
folder when you finish. `get_token.py <upn>` refuses a sign-in as another user. Use a private
browser window for the device-code page.

If a run stops, run the same command again. It creates only what is missing. To seed again with new
dates, run `cleanup` and then `apply`.

`cleanup` deletes an item only when it has the category `seed-v1` and a seed key that is in the
corpus. A folder or file is deleted only when its name has the `seed-v1` prefix. Items with the tag
but no known key are listed as "orphan kept". Mail and events are deleted for good.

## Corpus

| Item | Count |
| --- | --- |
| Mails | 47 (Mia 43, Anna 2, Tom 2) |
| Mia's Inbox | 29 mails, 17 unread |
| Threads | 2: "Website relaunch: launch checklist" with 12 messages, "Q3 budget review" with 5 |
| Mail folders | 4, one inside another |
| Events | 9 (Mia 8, Tom 1), no attendees |
| OneDrive files | 5 (Mia 4, Anna 1) |
| Mail attachments | 3 |

The corpus has these quirks on purpose: a mail with no subject, an empty body, an HTML-only body,
flags, attachments, a draft, mail received yesterday, events in Windows time zones, one all-day
event, one weekly series, and Office files whose properties name the personas.

## How the mail gets its date

`POST /me/mailFolders/{id}/messages` makes a draft with today's date. The seed adds MAPI extended
properties to the same request: the message flags (read or unread, no "unsent" bit), the delivery
and submit times, the conversation topic and the conversation index. Exchange Online accepts them.
The mail is not a draft, it shows the planned date, and a thread groups. `--mail-mode draft` is
the fallback that makes plain drafts.

## Safety rules in the code

- The token comes from `GRAPH_TOKEN` only and goes only into the Authorization header. Error text
  is redacted.
- Every address in every request must be in `SEED_UPNS`. The check runs before the first request.
- `GET /me` must answer the address at position `--as`, before any other request.
- Requests go only to `https://graph.microsoft.com/v1.0/me`, one at a time, at most 300 per run.
- The checks use `if` and exceptions, not `assert`, so `python -O` keeps them.

## Tests

```sh
.venv/bin/python -m pytest scripts/dogfood/seed/test_seed.py -q -p no:cacheprovider
```

The tests cover: the plan is the same every time, and a second `apply` creates nothing; a run that
stopped continues; `cleanup` keeps items that are not the seed's; an address, user, path or host
outside the allowed set is refused before the request; the request cap; Retry-After; no retry of
a write after a 503; and no token in any output.
