"""What a Teams message is: who sent one, out of every shape Graph names a sender in.

A message has to mean the same thing whichever Graph API produced it, and that is a property of
there being one definition rather than of several agreeing. So it lives here rather than in the tool
file that reports one, because the disagreement it prevents is caller-visible: the same message,
found by a search and read in full, described with two different senders.

What the sender has to survive is documented and not optional:

* **It arrives in three shapes.** Every Teams read API answers with `teamworkUserIdentity`
  (https://learn.microsoft.com/en-us/graph/api/resources/teamworkuseridentity): an id, an
  *optional* display name, and **no email property at all**. Search answers with a mailbox-shaped
  `emailAddress`, because Teams messages are indexed out of the substrate mailbox. A bot, a
  connector or an outgoing webhook arrives as an application identity
  (https://learn.microsoft.com/en-us/graph/api/resources/teamworkapplicationidentity), whose
  display name is again *optional* and whose id is not. All three go through `sender_of`, which is
  why a sender is the same four fields whichever shape Graph used, with different ones filled in —
  and why which fields are populated says which shape Graph answered with rather than saying the
  sender has no name, no address or no id.
* **Every field of a sender is optional; the identity Graph named is not.** So `sender_of` decides
  on what the identity holds rather than on the fields it produced: an identity carrying an id or a
  name is a sender, whatever else it left blank. Deciding on the output instead discards every
  actor Graph names in a field this projection does not read — an application whose display name is
  blank loses its id and its message together. Deciding on the identity object's mere presence is
  the opposite error: Graph sends empty ones, and reading those as senders answers with a hit whose
  every field is null.
* **Some messages have no sender.** Microsoft documents the identity set as null "for a message
  that has been deleted or sent by the Microsoft Teams internal system; for example, event messages
  for addition of members" — "Ada joined the chat", a call ending, a channel being renamed. Such a
  message also has a body of the literal `<systemEventMessage/>`, and the sentence Teams displays
  is rendered by its client and never sent
  (https://learn.microsoft.com/en-us/graph/system-messages). So `sender_of` answering None is a
  fact about the message rather than a failure to read one, and it is the signal a search filters
  those hits out by: the `messageType` and `eventDetail` properties that would name the event are
  not in the search projection, which leaves the missing sender as the only thing that says so.
"""

from typing import cast

from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from msgraph.generated.models.identity import Identity
from pydantic import BaseModel, Field


class MessageSender(BaseModel):
    """Who sent a message, from whichever identity shape Graph used.

    Three shapes. Teams messages are indexed out of the substrate mailbox, so a search hit carries
    an Exchange-style `emailAddress` (a name and an address), while every Teams read API returns a
    `teamworkUserIdentity` (an id and an optional display name, and no email at all); a bot, a
    connector or an outgoing webhook is an application identity (an id and an optional display
    name). Which fields are populated therefore says which shape Graph answered with, and a null is
    not evidence that the sender has no name, no address or no id.
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
    application_id: str | None = Field(
        description=(
            "The id of the application that sent the message — a bot, a connector or an outgoing "
            + "webhook. Microsoft documents this id as always present on an application identity, "
            + "where the display name is optional, so it is the one field that names such a sender "
            + "in every case. Null for a message a person sent. It is not interchangeable with "
            + "`user_id`, and the `mentions` search parameter does not accept it: that parameter "
            + "matches on user ids alone."
        )
    )


def sender_of(identity: ChatMessageFromIdentitySet | None) -> MessageSender | None:
    """The sender, or None when Graph named no sender at all.

    One function over all three identity shapes, because a search hit and a read of the same
    message must report the same sender.

    The decision is made on the identity Graph named rather than on the fields below, because every
    one of those is optional: an identity carrying an id or a name is a sender, whatever else it
    left blank. What the presence of the identity *object* says is nothing — Graph sends an empty
    one — so a sender is only as real as what is inside it. A null `from`, and an identity set
    naming nobody, is how Graph sends a deleted message and a Teams internal system message, so
    None is also the signal a search filters those hits out by.
    """
    if identity is None:
        return None
    user = identity.user
    application = identity.application
    mailbox_name, mailbox_address = _mailbox_identity(identity)
    named = _names_anybody(user) or _names_anybody(application)
    if not named and mailbox_name is None and mailbox_address is None:
        return None
    display_name = user.display_name if user is not None else None
    if display_name is None and application is not None:
        display_name = application.display_name
    return MessageSender(
        # Empty strings are collapsed to null: `displayName` is documented Optional and Graph does
        # send it blank, and a name that is present-but-empty reads as an unnamed sender rather
        # than as the "Graph did not say" that the id fields are there to work around.
        display_name=_present(display_name) or mailbox_name,
        email=mailbox_address,
        user_id=user.id if user is not None else None,
        application_id=application.id if application is not None else None,
    )


def _names_anybody(identity: Identity | None) -> bool:
    """Whether Graph put anything identifying in this identity.

    An id or a name is somebody. An identity holding neither is not a sender Graph declined to
    name; it is Graph sending the object and naming nobody in it, which reads the same as the
    property being absent.
    """
    return identity is not None and (
        identity.id is not None or _present(identity.display_name) is not None
    )


def _mailbox_identity(identity: ChatMessageFromIdentitySet) -> tuple[str | None, str | None]:
    """The `emailAddress` a search hit carries instead of a Teams identity, as (name, address).

    Search reads Teams messages out of the substrate mailbox, so `POST /search/query` answers with
    `from: {"emailAddress": {"name": ..., "address": ...}}` where the Teams APIs answer with
    `from: {"user": {...}}`. The SDK's identity set has no field for the mailbox shape, so it
    arrives in `additional_data` — untyped by construction, hence the narrowing here.

    Either half is None unless it says something, so that a mailbox object holding nothing but
    blanks names nobody here too.
    """
    extra = cast("dict[str, object]", identity.additional_data)
    mailbox = extra.get("emailAddress")
    if not isinstance(mailbox, dict):
        return (None, None)
    fields_ = cast("dict[str, object]", mailbox)
    return (_string(fields_.get("name")), _string(fields_.get("address")))


def _string(value: object) -> str | None:
    """`value` when it is a string that says something, else None."""
    return _present(value) if isinstance(value, str) else None


def _present(value: str | None) -> str | None:
    """`value` if it says anything, else None."""
    return value if value is not None and value.strip() else None
