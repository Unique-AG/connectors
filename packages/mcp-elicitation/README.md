# mcp-elicitation

How a Python MCP server asks a person something: confirm an action, or pick one or several
options. It speaks both MCP protocol eras and Unique's confirmation protocol, so a tool only
says what to ask.

## The protocol with MCP Hub

| Where | Key | Value | Sent by |
|---|---|---|---|
| Tool definition `_meta` (`tools/list`) | `unique.app/mcp-server/asks-confirmation` | `true` | the server |
| `tools/call` → `params._meta` | `unique.app/mcp-server/skip-confirmation` | `true` | MCP Hub |

A tool with `asks-confirmation` asks unless the call carries `skip-confirmation: true`. A missing
key, `false`, or any other value means it asks, so Claude and other clients keep being asked.
MCP Hub drops its own generic approval for such a tool, so a person confirms once.

With `skip-confirmation`, `confirm` returns `Confirmed(skipped=True)` and the tool goes ahead,
while a choice returns its options to the model (`NeedsChoice`). With a client that cannot elicit,
`confirm` refuses and a choice returns `NeedsChoice`. Neither guesses.

## Wiring, once per server

```python
from functools import lru_cache

from mcp_configs import ElicitationSettings
from mcp_elicitation import Elicitation, create_request_state_security

settings = ElicitationSettings()
mcp = FastMCP("office-365-mcp", request_state_security=create_request_state_security(settings))


@lru_cache(maxsize=1)
def get_elicitation() -> Elicitation:
    return Elicitation(settings, store=persistence.store)
```

`store` is a `py-key-value-aio` store. It holds one marker per open question, so each answer is
used once. A service with Postgres or Redis passes that store, which holds across replicas; a
service without one passes a `MemoryStore`. The store must delete atomically, returning true to
one caller only: memory, Redis and Postgres do, Firestore checks then deletes and does not.

`ELICITATION_REQUEST_STATE_KEYS` lets an answer come back to any replica on 2026-07-28, as long
as every replica shares the store. Without the keys, only the process that asked can take the
answer. A `MemoryStore` is never shared, so a service on one runs a single replica or sticky
sessions: an answer that reaches another replica is refused, even with the keys.

## Confirm

```python
@tool(annotations=WRITE_DESTRUCTIVE_IDEMPOTENT, meta=ASKS_CONFIRMATION)
async def outlook_delete_mail_rule(
    ctx: Context, rule_ref: str, elicitation: Elicitation = Depends(get_elicitation)
) -> DeletedRule | InputRequiredResult:
    rule = await read_rule(rule_ref)
    answer = await elicitation.confirm(
        ctx,
        f'Delete the inbox rule "{rule.name}"? This connector cannot restore it.',
        agree="Delete the rule",
        decline="Keep the rule",
        nothing_happened="The rule was not deleted.",
    )
    if needs_answer(answer):
        return answer
    return await delete(rule)
```

`confirm` returns `Confirmed` only when the person picked `agree`, or when MCP Hub sent
`skip-confirmation` (`Confirmed.skipped`). Anything else, including a form accepted without an
answer, raises `NotConfirmedError`, a `ToolError` whose message tells the model what happened
and not to retry. With `raises=False` it returns that `NotConfirmed` instead.

## Choose

```python
picked = await elicitation.choose_one(
    ctx,
    "Delete all mails in which folder?",
    [Option(ref=folder.ref, label=f"{folder.name} ({folder.count} mails)") for folder in folders],
)
if needs_answer(picked):
    return picked
await empty(picked.ref)
```

`choose_many(..., min_items=1, max_items=None)` returns `ChosenMany.refs`. When nobody picked,
both return `NeedsChoice`: the options, and why nobody picked, for the model. A tool that may
return it lists `NeedsChoice` in its return type.

Label each option with what picking it does, such as a count, and the pick is the confirmation:
the tool goes ahead without a second question.

## What the tool has to keep to

- **Nothing changes before the question.** On 2026-07-28 the client calls the tool again with
  the answer, and the tool runs from the top: everything above the question runs twice.
- **The model's pick is confirmed.** A tool that takes back a `NeedsChoice` ref from the model
  calls `confirm` before acting on it, so the model cannot skip the person by picking itself.
- **One question per call where possible.** Each question on 2026-07-28 is one more round trip.
  A tool may ask several; earlier answers ride along in the sealed state.

## The two protocol eras

| | Up to 2025-11-25 (MCP Hub today) | 2026-07-28 |
|---|---|---|
| How it asks | `elicitation/create` on the open `tools/call`, waited on for `ELICITATION_TIMEOUT_BEFORE_CANCEL_SECONDS` | returns an `InputRequiredResult`; the client calls the tool again with the answer |
| What `confirm` and `choose_*` return | the answer | `InputRequiredResult` on the first call, the answer on the call that brings it |

On 2026-07-28 an answer counts only for the same tool, arguments and signed-in user (the SDK
binds the sealed state to them), only once, and only for the question the person saw: if the
message or options changed in between, the tool asks again. There is no answer timeout on
2026-07-28; a question stays open for the SDK's seal lifetime, 10 minutes.

## Forms

A tool sets text and options, never controls. Each form has one required field and no default:
`confirm` a `oneOf` of `confirm` and `cancel`, titled with `agree` and `decline`; `choose_one` a
`oneOf` of the options; `choose_many` an array with `minItems`, `maxItems` and an `anyOf` of the
options. Every option travels as `{"const": ref, "title": label}`.
