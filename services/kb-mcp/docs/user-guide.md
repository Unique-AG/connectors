<!-- confluence-page-id: 2744221761 -->
<!-- confluence-space-key: PUBDOC -->

## What it does

The Knowledge Base MCP server lets an AI assistant, such as Unique AI or Claude, search and read
your organisation's Unique knowledge base while you talk to it. You ask a question in plain
language, the assistant searches, opens the files it needs, and answers with citations back to the
source documents.

It is read-only. Nothing you or the assistant does through it changes or adds to the knowledge
base.

## Connecting

The first time your assistant uses the knowledge base, it asks you to sign in. Sign in with your
normal company account, the same one you use for the Unique web app, and approve the connection
once. Exactly how long you stay connected depends on your client, anywhere from a few hours to
several days; you'll be asked to sign in again once it lapses.

If you get signed out, the assistant will say the knowledge base is unavailable and ask you to
connect again.

Don't see the knowledge base as an option at all? Someone has to turn it on first: an admin adds
the connector (an org admin, for Claude; whoever manages your Unique AI setup, for Unique AI), it
needs to be enabled for the space you're using, and the individual tool can be switched off
separately from the rest. Ask your IT admin if it's missing.

Using a different assistant, such as Claude or Cursor, instead of Unique AI? See
[Connecting Clients](./connecting.md).

## Disconnecting

Remove the connector from your client's own settings (for Unique AI, ask your tenant admin) to
end the session. There's nothing left behind afterwards: kb-mcp never stored what you searched or
read, so disconnecting doesn't "clean up" anything, it just ends access.

## What you can see

You can only see what you could already open yourself. Your own permissions apply to every search
and every file, so connecting the assistant doesn't give it, or you, access to anything new. Two
colleagues asking the same question can correctly get different answers, because they don't have
access to the same documents.

Your administrator may also restrict the connector to part of the knowledge base. If they have,
that restriction sits on top of your own permissions. It doesn't replace them.

## Getting better answers

Narrow your question to a folder when you can. "Search the Legal folder for the 2026 vendor terms"
works far better than the same question with no location. Subfolders are included by default.

If you're not sure where something lives, ask what folders you can see first. That gives the
assistant the layout, so its next search lands closer to what you need.

Answers come with citations. If you want to read the full document rather than the summary, just
ask to see the source.

!!! note "If you get nothing back"
    An empty result usually means one of three things: the content isn't in the knowledge base, you
    don't have access to it, or the search was scoped too narrowly. Ask the assistant to try again
    without the folder restriction. It will tell you if a filter was the cause.

## Limits worth knowing

Large documents come back in pieces. The assistant reads a portion at a time and asks for more if
it needs it, so a very long document can take several reads to get through.

A newly added file or folder can take a few minutes to show up, but only if you already asked
about that folder earlier in the conversation: the listing you got back was cached before the
file existed. Ask the assistant to refresh and it will re-fetch the current listing.

Very broad questions tend to work poorly. "Summarise everything about the merger" across a large
knowledge base comes back weak. You'll get more out of it by narrowing to a folder or topic.

## Related documentation

- [Overview](./README.md): what kb-mcp is and how it fits together
