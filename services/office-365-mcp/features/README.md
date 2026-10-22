# office-365-mcp use cases

This folder states what people do with office-365-mcp. One Gherkin feature file states one
capability, in business words. A sidecar file beside it states which tools the assistant calls.

The list feeds two later tasks. UN-27226 turns the scenarios into tests. UN-27222 changes the tools,
the parameters, and the docs to match. For the tool reference, read `../docs/README.md`.

## Files

| File | What it holds |
| --- | --- |
| `NN-name.feature` | The capability, as scenarios. It names no tool and no argument. |
| `NN-name.calls.yaml` | For each scenario, the status, the prompt, the limit, and the chain of tools that the assistant calls. |
| `STATUS.md` | The status of every scenario, by surface. It lists the work for UN-27222. A script writes it. |
| `../tests/test_use_cases.py` | The check that the files agree, that the chains use real tools, arguments, and values, and that the two generated pages are current. |
| `../docs/use-cases.md` | The guide for readers. The text between its two markers comes from the features and the sidecars. A person writes the rest. |
| `../scripts/render-use-cases.py` | Writes the guide and `STATUS.md`. Run `uv run python scripts/render-use-cases.py`, or add `--check` to find drift. |

The number `NN` is a name and not a rank. The rank is in the table below.

The guide shows no tool and no status. It shows the prompt and the result of each scenario. It
shows the limit of a scenario with status `partly`. It lists a scenario with status `gap` as "Not
supported yet". `../docs/.mdignore` keeps the guide out of the Confluence publish until the guide
has a Confluence page id.

## Surfaces

The feature tag sets the surface. A feature with tags of two surfaces is in "Across sources".

| Tag | Surface |
| --- | --- |
| `@outlook-mail`, `@outlook-calendar`, `@outlook-contacts` | Outlook |
| `@teams` | Teams |
| `@sharepoint` | SharePoint |
| `@onenote` | OneNote |

The tag `@uc-NN-MM` is the permanent id of a scenario. The sidecar uses it as a key. Never reuse an id.

## The sidecar

Each entry has these keys:

| Key | Meaning |
| --- | --- |
| `status` | `untested`, `working`, `partly`, or `gap`. See below. |
| `ask` | What Mia types to the assistant, in her words. It names no tool. |
| `blocker` | The limit. It is there when the status is `partly` or `gap`, and only then. See below. |
| `provenance` | `observed` when the chain is a pattern in the prod logs. `drafted` when it comes from the tool descriptions. |
| `evidence` | What the logs show. A drafted chain keeps it when the logs show only a part of the chain. |
| `asks_user` | True when a tool in the chain asks the user to approve. |
| `chain` | The steps, in order. A step has `tool`, or `any_of` for a choice. It can have `optional`, `repeat: many`, `args`, and `uses`. |
| `must_not` | Tools that the assistant must not call. |
| `note` | An extra fact or an open point. |

The status:

| Status | Meaning |
| --- | --- |
| `untested` | Nobody ran the scenario. |
| `working` | A person ran it by hand in a real mailbox, and it did what the scenario says. No recorded run exists. |
| `partly` | A limit blocks a part of it, or the prod logs show this kind of task failing. |
| `gap` | Nothing meets the scenario today. The chain is empty. |

The blocker has these keys: `kind`, `tool` (optional), `text` (the cause, for a developer), and
`user` (what the user is told, with no tool name).

| Kind | Meaning |
| --- | --- |
| `tool` | No tool does it. |
| `parameter` | A tool lacks a parameter that the scenario needs. |
| `description` | The tool can do it, but its description steers the assistant away or hides an input. |
| `preset` | The tools that the scenario needs sit in different presets. |
| `graph` | Microsoft Graph cannot do it. |
| `unknown` | It fails in prod and the cause is not known. |

UN-27222 can fix a cause of the kind `tool`, `parameter`, `description`, or `preset`. It cannot fix a
cause of the kind `graph`. `STATUS.md` lists them.

The key `uses` maps an argument to the earlier step that gives its value. This records a data
dependency. For example, `outlook_move_mail` takes its `message_refs` from a listing. The 17 failed
moves in prod broke this dependency.

A chain does not fix one path. Two tools can both be right, and `any_of` says so. A test can check
the required tools, the forbidden tools, the approval, and the data dependencies.

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

Prod turned on 60 of the 121 tools until 2026-10-14 (monorepo PR 32074), and all 121 after that
date. Most of the window above ran with 60 tools. In that period, 3 of the 6 tools of `01`, 2 of 10
in `10`, 1 of 3 in `11`, 0 of 4 in `12`, and 2 of 8 in `13` were on. A zero count for these files
does not show that nobody wants the capability.

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

## Known gaps and work for UN-27222

`STATUS.md` lists every scenario with status `partly` or `gap`, with its blocker. It is the work
list for UN-27222.

## Open questions

- Does Microsoft convert each file type to a PDF that `sharepoint_read_file` can give the assistant?
  The assistant must set `convert_to` to `pdf` to read an Office file as text. The scenario outline
  in `01` lists the types to test.
- Why does `outlook_move_mail` get a value that is not a handle? The server logs hold no arguments,
  so the cause is not known. Does the assistant send one message in each call? 20 consecutive calls
  in one session suggest it.
- Does `outlook_create_event_on_behalf` work on a second calendar of Mia in a real mailbox? The
  source allows it. Nobody ran it. If it works, change the description and set `uc-07-09` to
  `untested`.
