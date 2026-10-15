# office-365-mcp use cases

This folder lists what people do with office-365-mcp. Each file is one capability, written as a
Gherkin feature. The files are in order of real use: the capability that people use most is first.

The list feeds two later tasks. UN-27226 turns the scenarios into tests. UN-27222 changes the tools,
the parameters, and the docs to match. For the tool reference, read `../README.md`.

## How to read a scenario

A scenario says what Mia expects from her assistant, in business words. It names no tool and no
argument. The `When` step is the task that Mia gives. The `Then` steps are what Mia sees.

A later step maps each scenario to the tool calls that the assistant makes. That step takes the
real calls from the QA and prod logs and does not guess them.

## Tags

| Tag | Meaning |
| --- | --- |
| `@outlook-mail`, `@outlook-calendar`, `@outlook-contacts`, `@teams`, `@sharepoint`, `@onenote` | The Microsoft 365 area of the feature. |
| `@working` | A person ran this by hand in a real mailbox and it did what the scenario says. No recorded run exists. |
| `@known-gap` | A tool description or the code already states a limit that blocks the scenario. Nobody ran it. |
| `@seen-failing` | The prod logs show this kind of task failing. The cause is not always known. |

A scenario with none of the last three tags is untested.

## Evidence for the order

The count below is the number of tool calls in the prod logs, from 2026-09-15 to 2026-10-15. The
service went live in prod on 2026-09-23. The count is calls, not users. The logs hold no user
identity. An earlier count on 2026-10-07 found 12 users in one company.

| File | Calls | Share |
| --- | --- | --- |
| `01-find-and-read-files` | 437 | 29% |
| `02-find-and-read-mail` | 372 | 25% |
| `03-read-the-calendar` | 323 | 22% |
| `05-organize-the-mailbox` | 109 | 7% |
| `04-draft-and-send-mail` | 105 | 7% |
| `06-catch-up-on-teams` | 100 | 7% |
| `08-work-with-notes` | 39 | 3% |
| `07-schedule-and-answer-meetings` | 13 | 1% |
| Files 09 to 14 | 0 | 0% |

The files 09 to 14 have no call in prod. A call count of zero does not show that nobody wants the
capability. Prod may not turn on every tool. Check the deployed tool list before you drop one of
these files.

The QA logs hold 76 calls, all test traffic. They do not set the order.

## What the usage shows

The facts:

- `sharepoint_read_file` is the most used tool, with 251 calls. It failed 16 times.
- `outlook_read_event` is the second most used tool, with 244 calls. `outlook_list_events` has 65.
- `outlook_move_mail` failed 17 of 77 times.
- The assistant made 78 draft calls, for new mail and for replies, and 12 send calls.
- OneNote has 39 calls. The epic UN-21037 puts OneNote on hold until a client asks for it.

What the failure lines say. Each sample is the 4 newest lines. The sample does not prove that the
other failures have the same cause.

| Tool | Failures | What the sample shows |
| --- | --- | --- |
| `outlook_move_mail` | 17 | All 4 samples: the assistant gave a value that is not a message handle. The tool moved nothing. |
| `sharepoint_read_file` | 16 | All 4 samples: Microsoft answered 406 when the tool asked for the file content. |
| `outlook_read_event` | 11 | All 4 samples: Microsoft answered 404, item not found. The 4 lines came in 8 seconds, in 2 sessions. |

What the code shows, with a guess about the cause:

- `outlook_list_events` has no attendee filter, and a row has no attendee list. To see who comes,
  the assistant must open each event. This can explain why there are 4 reads for each listing.
  Nobody checked this.

## Known gaps

| Scenario | File | Cause |
| --- | --- | --- |
| The next meeting with a given person is found | `03` | parameter: no attendee filter, and no attendees in a listing |
| A new file is attached to a draft | `04` | tool: the draft tools write text only |
| An invitation is drafted before it goes out | `07` | graph: a calendar event has no draft state |
| A meeting is booked on a second calendar | `07` | parameter: `outlook_create_event` writes to the default calendar only |
| A page is found by a word in its body | `08` | graph: OneNote has no full-text search |
| The content of an existing file is replaced | `10` | tool: the tool creates new text files only |
| Access is taken back | `10` | tool: no tool removes a permission |
| A person only in the company directory is found | `12` | tool: `outlook_find_recipient` gives an address and no telephone number |

UN-27222 can fix a cause of the kind tool or parameter. It cannot fix a cause of the kind graph.

## Open questions

- Which tools does prod turn on? The answer decides what the zero counts mean.
- Does the tool `sharepoint_read_file` give the assistant text that it can read for each file type?
  The scenario outline in `01` lists the types to test.
- Why does `outlook_read_event` answer 404 for events that a listing showed?
