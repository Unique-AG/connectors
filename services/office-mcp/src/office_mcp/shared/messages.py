"""What a Teams message is: who sent one, out of either shape Graph names a sender in.

A message has to mean the same thing whichever Graph API produced it, and that is a property of
there being one definition rather than of several agreeing. So it lives here rather than in the tool
file that reports one, because the disagreement it prevents is caller-visible: the same message,
found by a search and read in full, described with two different senders.

What the sender has to survive is documented and not optional:

* **It arrives in two shapes.** Every Teams read API answers with `teamworkUserIdentity`
  (https://learn.microsoft.com/en-us/graph/api/resources/teamworkuseridentity): an id, an
  *optional* display name, and **no email property at all**. Search answers with a mailbox-shaped
  `emailAddress`, because Teams messages are indexed out of the substrate mailbox. Both go through
  `sender_of`, which is why a sender is the same three fields either way, with different ones
  filled in — and why which fields are populated says which shape Graph answered with rather than
  saying the sender has no name or no address.
* **Some messages have no author at all.** For a system event message — "Ada joined the chat", a
  call ending, a channel being renamed — Graph sends `from: null` and a body of the literal
  `<systemEventMessage/>`; the sentence Teams displays is rendered by its client and never sent
  (https://learn.microsoft.com/en-us/graph/system-messages). So `sender_of` answering None is a
  fact about the message rather than a failure to read one, and it is the signal a search filters
  those hits out by: the `messageType` and `eventDetail` properties that would name the event are
  not in the search projection, which leaves the missing author as the only thing that says so.
"""

from typing import cast

from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from pydantic import BaseModel, Field


class MessageSender(BaseModel):
    """Who sent a message, from whichever identity shape Graph used.

    Two shapes, because Teams messages are indexed out of the substrate mailbox: a search hit
    carries an Exchange-style `emailAddress` (a name and an address), while every Teams read API
    returns a `teamworkUserIdentity` (an id and an optional display name, and no email at all).
    Which fields are populated therefore says which shape Graph answered with, and a null is not
    evidence that the sender has no name or no address.
    """

    display_name: str | None = Field(
        description=(
            "The sender's name as Teams shows it. Microsoft documents this as optional and it is "
            + "genuinely absent on some messages, including messages from external and federated "
            + "users — a null is not an anonymous sender."
        )
    )
    email: str | None = Field(
        description=(
            "The sender's email address. Present when Graph answered with the mailbox-shaped "
            + "identity that search hits normally carry, and null otherwise; the Teams identity "
            + "has no email property at all, so compare `user_id` when this is null."
        )
    )
    user_id: str | None = Field(
        description=(
            "The sender's Microsoft Entra object id, when Graph answered with the Teams-shaped "
            + "identity. This is the value the `mentions` search parameter takes, and the only "
            + "sender field safe to compare against ids from other tools. Null for a message sent "
            + "by an application (a bot or a connector), and null when Graph gave an email "
            + "address instead."
        )
    )


def sender_of(identity: ChatMessageFromIdentitySet | None) -> MessageSender | None:
    """The sender, or None when the identity set names nobody at all.

    One function over both identity shapes, because a search hit and a read of the same message
    must report the same sender.

    A null `from` — and an identity set that named nobody — is how Graph sends a system event
    message, so None is also the signal a search filters those hits out by.
    """
    if identity is None:
        return None
    mailbox_name, mailbox_address = _mailbox_identity(identity)
    user = identity.user
    application = identity.application
    display_name = user.display_name if user is not None else None
    if display_name is None and application is not None:
        display_name = application.display_name
    sender = MessageSender(
        # Empty strings are collapsed to null: `displayName` is documented Optional and Graph does
        # send it blank, and a name that is present-but-empty reads as an unnamed sender rather
        # than as the "Graph did not say" that `user_id` is there to work around.
        display_name=_present(display_name) or _present(mailbox_name),
        email=_present(mailbox_address),
        user_id=user.id if user is not None else None,
    )
    if (sender.display_name, sender.email, sender.user_id) == (None, None, None):
        return None
    return sender


def _mailbox_identity(identity: ChatMessageFromIdentitySet) -> tuple[str | None, str | None]:
    """The `emailAddress` a search hit carries instead of a Teams identity, as (name, address).

    Search reads Teams messages out of the substrate mailbox, so `POST /search/query` answers with
    `from: {"emailAddress": {"name": ..., "address": ...}}` where the Teams APIs answer with
    `from: {"user": {...}}`. The SDK's identity set has no field for the mailbox shape, so it
    arrives in `additional_data` — untyped by construction, hence the narrowing here.
    """
    extra = cast("dict[str, object]", identity.additional_data)
    mailbox = extra.get("emailAddress")
    if not isinstance(mailbox, dict):
        return (None, None)
    fields_ = cast("dict[str, object]", mailbox)
    return (_string(fields_.get("name")), _string(fields_.get("address")))


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _present(value: str | None) -> str | None:
    """`value` if it says anything, else None."""
    return value if value is not None and value.strip() else None
