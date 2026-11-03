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
   Contacts.ReadWrite, Files.ReadWrite, Files.Read.All, Sites.Read.All, Team.Create and User.Read.
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

`--phases a,b` limits `plan`, `apply` and `cleanup` to the named phases. `run_all.sh` takes it before
the indexes: `run_all.sh cleanup --phases cal-invites 2 3`. It runs the indexes in the order that
you give. `cleanup --phases` deletes the items that those phases created. A family does this in its
optional `cleanup(graph, ctx, owner, phases)`. `run_all.sh cleanup-cases` deletes the items that
have `seed-v1 case-` in their name.

A family can list phases in `OPT_IN`. `plan` and `apply` do not run these phases unless `--phases`
names them. `cleanup` without `--phases` includes them. The three phases of the teams family are
opt-in.

Four optional variables name the only extra addresses that a family may use: `SEED_DIRECTORY_UPN`
(a directory user), `SEED_GUEST_UPN` (a guest), `SEED_ROOM_UPN` (a room) and `SEED_SHARED_UPN` (a
shared mailbox). The corpus writes them as `env:<NAME>`. All addresses must differ. A step that
needs a variable that is not set stops the run before the first request. An address that is not
one of `SEED_UPNS` never goes into a `sendMail` request.

A file or an attachment of the kind `filler` or `filler-text` has a `size` and a `label`.
`docgen.generate` makes the bytes. They are the same on every run, and the manifest holds their
size, SHA-256, generator and label, not the bytes. A file above 3 MiB goes through an upload
session: `POST .../createUploadSession`, then one `PUT` for each chunk of 3.75 MiB to the
`uploadUrl` that Graph returned. The `PUT` carries no token.

Each persona signs in once. `get_token.py` keeps a refresh token in
`~/.cache/dogfood-graph/msal.json` (mode 600), and later runs ask for no sign-in. Delete that
folder when you finish. `get_token.py <upn>` refuses a sign-in as another user. Use a private
browser window for the device-code page.

If a run stops, run the same command again. It creates only what is missing. To seed again with new
dates, run `cleanup` and then `apply`.

`cleanup` deletes an item only when it has the category `seed-v1` and a seed key that is in the
corpus. A folder or file is deleted only when its name has the `seed-v1` prefix. Items with the tag
but no known key are listed as "orphan kept". Mail and events are deleted for good.

The phase `teams` runs as Mia only. It creates the team `seed-v1 team` with Mia as owner and Anna
and Tom as members, unless Mia has joined a team with that name. It needs the permission
Team.Create. Graph answers with 202, and the seed waits at most two minutes for the operation to
succeed. `cleanup` never deletes a team, and lists it as "kept". Graph cannot delete a chat, so
every chat with `seed-v1 case-` in its topic stays.

Some tenants refuse to create a private channel. Set `SEED_TEAMS_PRIVATE=0` to skip the private
channel and its two posts. The three recorder cases that need it then stay blocked.

A user without a Teams licence cannot post. Set `SEED_TEAMS_ANNA_AS=tom` and the posts of Anna
become posts of Tom. Then run the phases for the indexes 1 and 3 only.

The teams family has two more phases: `teams-posts` and `teams-chats`. They post about 76
messages. Graph does not delete a message for good. `cleanup --phases teams-posts,teams-chats`
soft-deletes the seed messages of the signed-in user only. Nobody opens the chat
`seed-v1 case-teams-unread chat` in the Teams client, so it stays unread.

A reply needs the post of an earlier user, and Mia creates the chats. Run the three phases in the
order Mia, Anna, Tom: `run_all.sh apply --phases teams,teams-posts,teams-chats 1 2 3`.
`record_all.sh seed` first runs `apply 2 3 1` with the default phases. It then runs this command.
On an empty tenant, run `run_all.sh apply --phases teams 1` before `apply 2 3 1`. The phases
`onenote-group` and `team-files` need the team.

The calendar family has ten phases. Its data is in `corpus/outlook-calendar.yaml`. Run them in
this order:

1. `cal-calendars`, `cal-events`, `cal-contacts`, `cal-series`, `cal-bulk` and `cal-settings`
   make the data of each user that owns some. Mia's events send invitations to Anna and Tom.
2. `cal-answers` runs for Anna and Tom. Each user accepts, declines or tentatively accepts the
   invitation of Mia, or leaves it open. Mia's copy of an invitation must exist first.
3. `cal-invites` runs for Anna and Tom, who invite Mia. It then runs for Mia, who adds the
   category `seed-v1` to her copies. Run it for Mia last, after Anna and Tom.
4. `cal-shared` shares calendars. A person must accept each sharing invitation in Outlook on the
   web. Graph has no call for this step. Until then the shared calendar is not in `/me/calendars`.
5. `cal-group` runs as Mia. It needs the team.

A default `apply` skips `cal-group` and the step of `cal-answers` that tags Mia's copies. They
run only when `--phases` names phases and does not name all four of the phases `folders`, `mail`,
`events` and `files`.

The sharepoint family has four phases. Its data is in `corpus/files-tree.yaml`. Each phase is
idempotent: a file or folder that is already there is not made again.

- `sharepoint` makes the folder `seed-v1 Move Target` for Mia.
- `files-tree` makes the folder `seed-v1 Seed Files` if the folder is missing. It makes
  folders in folders, files in them, a text of 2000 characters and a picture. The three files
  `Order A`, `Order B` and `Order C` get their change time from the upload session. Anna makes
  `Order D` in her own folder and invites Mia to read it, without mail. This invitation runs again
  on each `apply`, and Graph keeps one permission for one person. Run Mia first, then Anna.
- `files-big` makes two files of 10,485,760 and 10,485,761 bytes through upload sessions.
- `team-files` runs as Mia. It needs the team and its SharePoint site. It makes the channel
  `seed-v1 Long channel` when the channel is missing, the folder `seed-v1 Team Files` with two
  folders and three files in the library of the team, and one note in the folder of the channel.
  The site can need some minutes. If the library is not ready, the run stops. Run it again later.
  It needs the permission Channel.Create. `cleanup` keeps the channel.

The onenote family has two more phases. `onenote-group` runs as Mia. It makes the notebook
`seed-v1 Shared Notes` for the team, with one section and one page. `onenote-big` makes the page
`seed-v1 Big page` of 900,000 bytes in the section `seed-v1 Planning`, so it needs the phase
`onenote` first. `cleanup --phases` deletes the pages of these two phases. Graph cannot delete a
notebook or a section, so they stay.

The mail family has three more phases. Its data is in `corpus/mail-extra.yaml`. All three run in
the default of `apply`, and none of them needs the earlier phases of the family.

- `mail-attach` runs as Mia. It makes four Inbox mails from the corpus: a mail with an xlsx
  workbook, a mail with a file of 10 MiB (10,485,760 bytes), a mail with a file of one byte more
  and a mail with a file of 10,484,595 bytes. Graph adds a few hundred bytes to the size of an
  attachment, and the amount is different for each file. The last file has 1,000 bytes of margin,
  so the size that Graph reports stays below the size limit of `outlook_read_attachment`
  (10,485,760 bytes). A file above 3 MiB goes through an upload session. A second run adds
  nothing: it looks for each file by name, so a file of an old size stays. To change the size of
  a file, run `cleanup --phases mail-attach` first.
- `mail-people` sends real mail with `POST /me/sendMail`: nine mails, three from each test user,
  to the other two. Only a delivered mail puts a person into the people list of Exchange. The
  sent copy has no category. A second run sends nothing when Sent Items already holds the subject.
  The list of Exchange needs one to 24 hours before it names the other test users.
- `mail-prefs` runs as Anna. It sets a scheduled automatic reply for the senders inside the
  organization, from one day before the anchor date to three days after it. The text of the reply
  holds an instruction for a model. A second run sets the same reply again.

Run `mail-people` for all three users before `mail-prefs`: `run_all.sh apply --phases mail-people 1 2 3`,
then `run_all.sh apply --phases mail-prefs 2`. When Anna has the reply on, each mail that reaches
Anna from a new sender makes her send one automatic reply, and that reply lands in the Inbox of
the sender. The default order of `record_all.sh seed` (2, 3, 1) puts the sends of Mia after the
reply of Anna.

`cleanup --phases mail-attach`, `mail-people` or `mail-prefs` deletes the messages of the phase
for good, and the last one switches the reply off. A mail of `mail-people` is deleted only when
its subject is one of the nine and its sender is a test user. The case sweep also deletes, from an
Inbox, the copy that a recorded case sent to a test user and the automatic reply of Anna to it. It
switches off an automatic reply whose text holds `seed-v1 case-`.

## Corpus

| Item | Count |
| --- | --- |
| Mails | 69 (Mia 65, Anna 2, Tom 2), and 4 more in the phase `mail-attach` |
| Mia's Inbox | 45 mails, 28 unread |
| Threads | 3: "Website relaunch: launch checklist" with 12 messages, "Q3 budget review" with 5, "Printer replacement" with 3 |
| Junk Email and Deleted Items | 3 and 2 mails |
| Newsletters | 8 unread mails with the category Newsletter |
| Mail folders | 6, one inside another, and two named Archive at two levels |
| Events | 9 (Mia 8, Tom 1), no attendees |
| OneDrive files | 5 (Mia 4, Anna 1) |
| Mail attachments | 3, and 4 more in the phase `mail-attach` |

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
- Requests go only to `https://graph.microsoft.com/v1.0/me`, one at a time, at most 600 for each
  phase (`--phase-cap`). These are the exceptions:
  - `POST /v1.0/teams`, and `GET` of the operation that it returns.
  - `POST /v1.0/chats`. No other method and no other path of `chats` is open until a step learns
    the chat id.
  - The paths of `teams/<id>/channels`, `groups/<id>/events|calendar|drive|onenote`, `drives/<id>`
    and `chats/<id>/messages`, and only for an id that an earlier step of the same run found or
    created for this user (`Step.learns`: `team`, `drive` or `chat`).
  - `GET /v1.0/groups/<id>/members` and `POST /v1.0/groups/<id>/members/$ref`, for the team id
    that an earlier step found or created. They add Anna and Tom to the team of the seed.
  - `/v1.0/users/<SEED_SHARED_UPN>/mailFolders`, when the variable is set.
  - `POST /v1.0/me/sendMail`, in the phase `mail-people` only, 12 at most.
  - `PUT` of one chunk to the `uploadUrl` of the session that is open, with no token.
- The checks use `if` and exceptions, not `assert`, so `python -O` keeps them.

## Tests

```sh
.venv/bin/python -m pytest scripts/dogfood/seed -q -p no:cacheprovider
```

The tests cover: the plan is the same every time, and a second `apply` creates nothing; a run that
stopped continues; `cleanup` keeps items that are not the seed's; an address, user, path or host
outside the allowed set is refused before the request; the request cap; Retry-After; no retry of
a write after a 503; and no token in any output.
