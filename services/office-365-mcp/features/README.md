# office-365-mcp use cases

This folder states what people do with office-365-mcp. One Gherkin feature file states one
capability, in business words. A sidecar file beside it states which tools the assistant calls.

The list feeds two later tasks. UN-27226 turns the scenarios into tests. UN-27222 changes the tools,
the parameters, and the docs to match. For the tool reference, read `../docs/README.md`.

## Files

| File | What it holds |
| --- | --- |
| `NN-name.feature` | The capability, as scenarios. It names no tool and no argument. |
| `NN-name.calls.yaml` | For each scenario, the chain of tools that the assistant calls. |
| `../tests/test_use_cases.py` | The check that the two files agree, and that the chains use real tools and real arguments. |

The number `NN` is a name and not a rank. The rank is in the table below.

## Tags

| Tag | Meaning |
| --- | --- |
| `@uc-NN-MM` | The permanent id of a scenario. The sidecar uses it as a key. Never reuse an id. |
| `@outlook-mail`, `@outlook-calendar`, `@outlook-contacts`, `@teams`, `@sharepoint`, `@onenote` | The Microsoft 365 area of the feature. |
| `@working` | A person ran this by hand in a real mailbox, and it did what the scenario says. No recorded run exists. |
| `@known-gap` | A tool description or the code already states a limit that blocks the scenario. Nobody ran it. |
| `@seen-failing` | The prod logs show this kind of task failing. The cause is not always known. |

A scenario with none of the last three tags is untested.

## The sidecar

Each entry has these keys:

| Key | Meaning |
| --- | --- |
| `provenance` | `observed` when the chain is a pattern in the prod logs. `drafted` when it comes from the tool descriptions. |
| `evidence` | For an observed chain, what the logs show. |
| `asks_user` | True when a tool in the chain asks the user to approve. |
| `chain` | The steps, in order. A step has `tool`, or `any_of` for a choice. It can have `optional`, `repeat: many`, `args`, and `uses`. |
| `must_not` | Tools that the assistant must not call. |
| `note` | A limit or an open point. |

The key `uses` maps an argument to the earlier step that gives its value. This records a data
dependency. For example, `outlook_move_mail` takes its `message_refs` from a listing. The 17 failed
moves in prod broke this dependency.

A chain does not fix one path. Two tools can both be right, and `any_of` says so. A test can check
the required tools, the forbidden tools, the approval, and the data dependencies.

A known gap has an empty chain, because no chain meets the scenario today.

The check runs with the other tests:

```bash
cd services/office-365-mcp
uv run pytest tests/test_use_cases.py
```

## Evidence for the order

The logs are the prod logs of office-365-mcp, from 2026-09-23 (go-live) to 2026-10-16. A call is one
tool call. The logs hold no user identity, so the numbers count calls and sessions, not people. An
earlier count on 2026-10-07 found 12 users in one company.

Two sessions made 171 and 164 calls within one minute on 2026-10-14. Both repeat the same loop of
`outlook_list_mail`, `outlook_search_mail`, `outlook_read_event`, and `outlook_list_events`. They
hold 363 of the 1,591 events. They probably come from a script or a test, but the logs do not say.
The second column leaves them out, and the rank follows that column.

| File | Calls | Share | Calls without the 2 sessions | Share | Sessions |
| --- | --- | --- | --- | --- | --- |
| `01-find-and-read-files` | 437 | 28% | 437 | 36% | 115 |
| `02-find-and-read-mail` | 409 | 26% | 340 | 28% | 129 |
| `05-organize-the-mailbox` | 109 | 7% | 109 | 9% | 44 |
| `04-draft-and-send-mail` | 109 | 7% | 109 | 9% | 43 |
| `06-catch-up-on-teams` | 107 | 7% | 107 | 9% | 52 |
| `03-read-the-calendar` | 327 | 21% | 61 | 5% | 44 |
| `08-work-with-notes` | 39 | 3% | 39 | 3% | 14 |
| `07-schedule-and-answer-meetings` | 12 | 1% | 12 | 1% | 8 |
| `14-share-and-delegate-calendars` | 2 | 0% | 2 | 0% | 2 |
| Files `09` to `13` | 0 | 0% | 0 | 0% | 0 |

The file `15-work-across-mail-calendar-and-files` has no row. Its calls count in the files that
hold the same tools. Three real sessions show its scenarios (see the evidence in its sidecar).

A call count of zero does not show that nobody wants the capability. Prod may not turn on every
tool. Check the deployed tool list before you drop one of these files.

The QA logs hold 65 events in 24 sessions, all test traffic. They do not set the order.

## What the usage shows

The facts:

- 331 sessions made at least one tool call. 126 of them made exactly one.
- `sharepoint_read_file` is the most used tool, with 251 calls. 18 runs of 5 to 14 consecutive reads
  show that people ask about many files at once.
- People made 79 draft calls, for new mail and for replies, and 12 send calls.
- OneNote has 39 calls. 18 of them come from one session that made a notebook with 15 section
  groups. The epic UN-21037 puts OneNote on hold until a client asks for it.

The failures. The sample is the 4 newest lines for each tool. It does not prove that the other
failures have the same cause.

| Tool | Failures | Sessions | What the sample shows |
| --- | --- | --- | --- |
| `outlook_move_mail` | 17 | 15 | The assistant gave a value that is not a message handle. The tool moved nothing. |
| `sharepoint_read_file` | 16 | 9 | Microsoft answered 406 when the tool asked for the file content. |
| `outlook_read_event` | 11 | 2 | Microsoft answered 404, item not found. All 11 are in the 2 sessions above. |

The real flows that the sidecars use:

- Read files: search, then many reads in a row.
- Read a meeting: `outlook_list_events`, then `outlook_read_event` for each event.
- Triage the mailbox: `outlook_list_mail`, `outlook_mark_mail`, and `outlook_move_mail`, in a loop.
- Read a meeting transcript: `teams_list_chats`, `teams_list_meeting_transcripts`, and
  `teams_read_transcript`, in 7 sessions.
- Work across sources: one session of 22 calls read mail and files, drafted a reply, and filed mail.

## Known gaps

| Scenario | Id | Cause |
| --- | --- | --- |
| The next meeting with a given person is found | `uc-03-05` | parameter: no attendee filter, and no attendees in a listing |
| A new file is attached to a draft | `uc-04-11` | tool: the draft tools write text only |
| An invitation is drafted before it goes out | `uc-07-08` | graph: a calendar event has no draft state |
| A meeting is booked on a second calendar | `uc-07-09` | parameter: `outlook_create_event` writes to the default calendar only |
| A page is found by a word in its body | `uc-08-02` | graph: OneNote has no full-text search |
| The content of an existing file is replaced | `uc-10-05` | tool: the tool creates new text files only |
| Access is taken back | `uc-10-08` | tool: no tool removes a permission |
| A person only in the company directory is found | `uc-12-02` | tool: `outlook_find_recipient` gives an address and no telephone number |

Two scenarios need tools that no preset holds together. `uc-05-10` needs `outlook_create_category`
and `outlook_mark_mail`. `uc-05-11` needs `outlook_browse_folders` and `outlook_create_mail_rule`.
The cause is preset.

UN-27222 can fix a cause of the kind tool, parameter, or preset. It cannot fix a cause of the kind
graph.

## Open questions

- Which tools does prod turn on? The answer decides what the zero counts mean.
- Does `sharepoint_read_file` give the assistant text that it can read for each file type? The
  scenario outline in `01` lists the types to test.
- Why does `outlook_move_mail` get a value that is not a handle? The server logs hold no arguments,
  so the cause is not known. Does the assistant send one message in each call? 20 consecutive calls
  in one session suggest it.
- Do `outlook_update_event` and `outlook_cancel_event` ask Mia to approve when attendees exist? The
  sidecars say no, and mark it as not verified.
