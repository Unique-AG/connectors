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
`retired-ids.txt` lists the ids that were removed. A test fails when a listed id comes back, and when
an id goes missing without a line there.

## Happy and unhappy paths

Every scenario has one tag, `@happy` or `@unhappy`. A test fails when a scenario has none or both.

| Tag | Meaning |
| --- | --- |
| `@happy` | The normal flow. The thing that Mia asks for happens as she asks. A clarifying question or an approval question that Mia accepts is part of the normal flow. A scenario for something that the connector cannot do yet is `@happy`, because the status field says whether it works. |
| `@unhappy` | Something fails, is refused, is limited, or is hostile. Examples: Microsoft fails, is busy, or refuses; the item is gone, not found, or empty; a name is in use; a rule or a limit stops the action; a batch partly fails; Mia declines or does not answer; text from others tells the assistant to act. A busy answer that the assistant waits out is `@unhappy`, because the abnormal condition is the point. |

Tie-break rules:

- A scenario exactly at a limit that succeeds (a file of exactly 10 MB) is `@happy`.
- Wrong input from Mia (a range that runs backwards, a value that is already there) is `@unhappy`,
  whether the assistant repairs it, asks about it, or refuses it.
- A question because the request is vague (no day, no condition, two people with one name) is
  `@happy`. A question because an item cannot be found is `@unhappy`.
- A warning in an approval question makes the scenario `@unhappy` only when the warning names a
  limit or a loss. A notice of a normal fact does not.
- A scenario for something that the connector cannot do yet is `@happy` when its steps describe the
  normal flow, and `@unhappy` when its steps describe the refusal.
`STATUS.md` counts both tags for each surface.

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

`args` names only the arguments that the scenario depends on. A step may leave out other
arguments that the tool requires: about one step in seven does. The runner needs a full call, and
the key `bind` holds it. A test does not check required arguments, so a reader must not take a chain
as a complete call.

A chain does not fix one path. Two tools can both be right, and `any_of` says so. A test can check
the required tools, the forbidden tools, the approval, and the data dependencies.

The check runs with the other tests:

```bash
cd services/office-365-mcp
uv run pytest tests/test_use_cases.py
```

## Running the scenarios

`../tests/e2e/test_scenarios.py` runs each scenario that has a cassette. The run uses the real app,
the real middleware, and the real tools. Microsoft Graph does not answer. A cassette answers. The
run uses no network. It uses the legacy MCP handshake, so a tool asks for approval with an
elicitation request.

```bash
cd services/office-365-mcp
uv run pytest tests/e2e
```

A cassette is a file `../tests/e2e/cassettes/<name>.json`. It is a list of interactions. An
interaction has a request part and an answer part:

- The request part: `method`, `path`, and optionally `host`, `query`, `json` (the body), and
  `headers`. The headers are only `prefer` and `consistencylevel`, and they must be equal.
- The answer part: `status`, and optionally `body`, the name of a file in `../tests/e2e/fixtures/`.

The run is strict. A request that matches no unused interaction fails the step, and the message
shows the request and the interactions that no request reached yet. An interaction that no request
reaches fails the run. A request without the token of the user fails the step.

A date or a time in a request matches only the same text in the cassette, or a symbol.
`~yesterday`, `~today`, and `~tomorrow` match a date whose UTC day is that day, plus or minus one
day. No other value is a wildcard.

The keys of an entry:

| Key | Meaning |
| --- | --- |
| `cassette` | The cassette of the run of the entry. |
| `variants` | More runs. Each variant has a name, an optional `cassette`, and a step number for each step that it changes. |

The keys of a step:

| Key | Meaning |
| --- | --- |
| `pick` | The tool of `any_of` that the run calls. |
| `bind` | The argument values of the run. It replaces `args`. `uses` and some `args` are text for a person, so the run needs real values. |
| `fault` | One fault: `graph` (an answer with `status`, `headers`, `body`), `transport: timeout`, or `input` (wrong argument values). `at` names the request, for example `POST */send`. `times` is the number of requests that get the fault. |
| `approval` | `"yes"`, `"no"`, `silent`, or `unanswered`. Put quotes on yes and no. With `silent`, the user must not be asked. With the other values, the user must be asked. Without the key, the user agrees if asked. |
| `expect` | `result`, `tool_error`, `graph_calls`, and `retry_sleeps`. |

In `expect`:

- `result` maps a selector to a value.
- `tool_error` names a text constant, for example `tools.outlook_move_mail._NOT_A_MESSAGE_HANDLE`.
  It can also call a function of the server, for example
  `{shared.seam._no_answer: [tools.outlook_send_draft._NOTHING_SENT]}`. A list gives the arguments
  in order. A mapping gives them by name. A name that does not exist fails the run.
- `graph_calls` maps `METHOD /path` to a count. A `*` matches any text. The count is exact.
- `retry_sleeps` lists the waits of the retry handler, in seconds.

A selector reads a value from a result. `$prev.messages[*].uri` reads the `uri` of each message of
the previous step. `$1.files[0].uri` reads the first file of step 1. In `result`, the selector has
no `$` and reads the result of the same step.

To add a run:

1. Find the scenario that states the behaviour.
2. Write the cassette. Put each answer body in `fixtures/`, or use a fixture that is there.
3. Add `cassette` or a variant to the entry, and add `bind`, `fault`, `approval`, and `expect` to the
   steps.
4. Run `uv run pytest tests/e2e`. A request that does not match shows the request. Copy its values
   into the cassette.
5. Increase `_MINIMUM_EXECUTABLE` in `test_scenarios.py` to the new number of runs.

`_MINIMUM_EXECUTABLE` is a ratchet. The number of runs must not go below it. Increase it when you
add a run. Decrease it only in a change that says why.

A scenario outline gets a variant for each row. `uc-05-26` has a variant for the subject line. Add
the other rows in the same way, with a different `fault` `input` and the same cassette.

`../tests/test_use_cases.py` checks the shape of the keys, that each argument exists, that each
cassette exists, that a sidecar names each cassette, and that a cassette or a sidecar names each
fixture.

A recorder is not built. It can write a cassette from a run against a test tenant.

## Evidence for the order

The logs are the prod logs of office-365-mcp, from 2026-09-23 (go-live) to 2026-10-16. A call is one
tool call. The logs hold no user identity, so the numbers count calls and sessions, not people. A call line
holds the tool name, the session, and the status, and no arguments. A failure line for a wrong
argument is the exception: it can hold the value that was wrong (see the questions for the code
owners). An earlier count on 2026-10-07 found 12 users in one company.

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

## Since all tools were enabled (2026-10-14 to 2026-10-23)

Prod turned on all 121 tools on 2026-10-14 at 13:25 UTC. The window below is 8.8 days. The numbers
come from the same logs, read on 2026-10-23.

- 11,539 tool calls, 11,466 ok and 73 failed. 14 sessions make 91% of them. They come in 7 pairs
  that start in the same minute, use the same 5 to 9 mail and calendar tools, and call `get_me` every
  5 or 10 minutes. They look like a scheduled agent, but the logs do not say so. The ranking below
  leaves them out.
- Without them: 1,083 calls, 198 sessions, about 123 calls a day. 33 sessions (17%) made one call.
  Before, 38% made one call.
- Share of calls by feature: mail (02) 54%, calendar (03) 14%, Teams (06) 11%, files (01) 9%,
  drafts (04) 5%, organize (05) 3%, notes (08) 0.2%.
- Only 10 of the 61 new tools were used, with 28 calls in all. 81 of the 121 tools were never
  called. The only write to a person in Teams was one chat message. There were 50 draft calls and no
  send.
- The most frequent chain is `outlook_list_mail` then `outlook_search_mail` (25 sessions). Next are
  `teams_list_chats` then `teams_list_meeting_transcripts` (19) and `outlook_browse_folders` then
  `outlook_list_mail` (8).
- Failures: `outlook_respond_to_invite` failed 10 of 14 calls (404 and 400, in 2 sessions).
  `outlook_search_mail` failed 22 times with a Microsoft 500 error, in 12 sessions. 11 of those
  failures fell on the last two days. `outlook_move_mail` and `sharepoint_read_file` had no failure.

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
- Why does `outlook_move_mail` get a value that is not a handle? The call lines hold no arguments,
  so the cause is not known. Does the assistant send one message in each call? 20 consecutive calls
  in one session suggest it.
- Does `outlook_create_event_on_behalf` work on a second calendar of Mia in a real mailbox? The
  source allows it. Nobody ran it. If it works, change the description and set `uc-07-09` to
  `untested`.

### For the code owners

The unhappy-path scenarios state what the code does today. Where the code defines no behaviour, or
where the behaviour looks wrong, there is no scenario. These questions need an owner.

- An answer that cannot be read (a 200 with an HTML page) gets the advice for an unreachable
  service: retry once. Is that wanted for a permanent fault? The outlines named "an answer that
  nobody can read" state today's behaviour and change with the answer.
- A read waits out up to 3 tries of the retry handler, and each try waits the time that Microsoft
  asks. The total is about 90 to 270 seconds. The tool limit of node-chat is 60 seconds, so Mia may
  see a timeout and never the advice. What is the wanted limit?
- A 503 or 504 with a wait time on a write that must not repeat gets "retry after N seconds", although
  Microsoft may have made the change. Should the text say that the change may have happened and name
  the tool that shows it? The same holds for the row of a failed message in a partial batch, for the
  POST and the PATCH of `outlook_set_focused_override`, which can repeat, and for a timeout on a
  copy or a new folder.
- A 403 gets the advice "ask an administrator to grant the permission". That is wrong for a file that
  Mia cannot open, a shared mailbox, a delegated calendar, a channel where only owners post, and a
  meeting participant that Microsoft refuses. Which tools need their own text?
- Some lists have no maximum: `message_refs` of `outlook_move_mail`, the recipients of
  `sharepoint_invite`, the commands of `onenote_edit_page`, and the attachments, mentions, and
  attendees of the Teams tools. What size is wanted, and what is Mia told above it?
- `sharepoint_read_file` has no sentence that file text is data and not an order. Other read tools
  have one. Should it?
- A rename to a name that is in use, a repeated create, and a calendar role that Microsoft refuses
  have no stated answer from Microsoft. Which status does Microsoft send, and what must Mia be told?
- The search for a person stops at its cap and can answer "no match" for a person past the cap.
  `outlook_search_mail` leaves out a match without a stable id and says nothing. Is that wanted?
- `outlook_create_contact` saves a duplicate contact. `outlook_set_automatic_reply` does not check
  that the end is after the start. `outlook_set_focused_override` has no text for the 1001st sender.
- On the older elicitation path, `outlook_delete_mail_rule` reads the rule once, so a rule that
  changed while Mia decided is erased. Should it read again, as `outlook_send_draft` does?
- No tool sends a precondition, so a 412 cannot occur today. This question closes when a tool starts
  to send one.
- When the price list or the link cannot be read or made, does the assistant still create a draft
  without it? Two scenarios of feature 15 end with "nothing is sent", which is true either way.
- The sidecar has no key for an order rule such as "create once, then check". The notes of
  `uc-07-22` and `uc-14-09` state it.
- The log line for a failure with a wrong argument (a validation error) holds an `input_value` field,
  so the logs can hold the value that the model sent. That value can be user content. Is that
  wanted? The call lines hold no arguments.
- The server sets no time limit on the question that asks Mia to agree. A question that nobody
  answers waits until the client cancels the call (node-chat does so at 60 seconds), and a cancelled
  call returns no text. Should the server set a limit, so that the assistant learns that nothing
  happened?
- Three of the four validation failures since 2026-10-14 were `outlook_search_mail`: a folder given as
  an argument and an empty sender. Does the tool schema or the description need a change (UN-27222)?
