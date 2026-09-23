---
name: unique-kb-mcp
description: How to drive the Unique knowledge base MCP tools as a set rather than one at a time. Covers choosing between search and content_tree, scoping a call with a folder_id instead of filtering afterwards, checking content_metadata before writing a metadata_filter, and opening a result with read_file. Use whenever you are answering a question against a Unique knowledge base and the kb-mcp tools are connected.
---

# Working with a Unique knowledge base

Four tools. Each one's parameters are documented on the tool itself, so what
follows is the order to call them in and how each one feeds the next.

| Tool | Answers |
| --- | --- |
| `search` | "What does the knowledge base say about X?" |
| `content_tree` | "What files and folders exist here?" |
| `content_metadata` | "Which metadata fields can I filter on?" |
| `read_file` | "Show me this specific document." |

## Pick search or content_tree first

These two get confused constantly. The wrong pick still returns something, so
it looks fine and simply runs slower than it should.

Use `search` for questions about what documents *say*. Use `content_tree`
for questions about which documents *exist*. "What is our parental leave
policy" is a search. "Which policies do we have" is a content tree.

When a request touches both, and names no folder, search first with no
scope: it answers most questions on its own, and an unrestricted search is
the correct default. When the request also names a folder, get its
`folder_id` before searching, so the scope in the `search` call matches the
scope the user actually asked about.

## Scope with a folder_id, do not filter afterwards

When a request concerns one folder rather than the whole knowledge base, root
the walk at that folder. A rooted walk is fast. Retrieving the whole tree and
discarding most of it afterwards is slow.

A folder id is a `scope_` value that appears as a `(folder_id=scope_...)`
annotation in `content_tree(mode='tree')` output. Get it there, then pass
it back, either as `folder_path` on a later `content_tree` call or as
`folder_ids` on a `search`.

Two traps:

- A folder shows no id until the walk reaches a file beneath it. If the
  folder you need has no id, re-run with a larger `max_depth`. Setting
  `folders_only=true` keeps that cheap, because it hides files from the
  rendered output without narrowing the walk that discovers the ids.
- Never assemble a `scope_` value yourself, and never reuse one lifted from
  a citation or document link in an earlier result. Those point at whatever
  leaf folder a file happens to sit in, which is rarely the folder that was
  asked about. With no id in hand, omit the parameter and search everything.

## Call content_metadata before writing a metadata_filter

`content_metadata` returns every field name and every distinct value in
scope, exhaustively rather than as a sample. Read it and you know which
`path` keys exist. Skip it and you are guessing at field names, and a filter
naming a field that does not exist returns nothing, which reads exactly like
a knowledge base with no matching content.

Two things it does not promise. Values describe what filtering is
*possible*, not that this tenant's search accepts any filter you build from
them. And an empty result after filtering is more often a bad filter than an
empty knowledge base, so drop the filter and retry before reporting nothing
found.

## Worked example

"What did we change in the 2031 supplier terms? Only look in Contracts."

```text
1. content_tree(mode='tree', folders_only=true, max_depth=3)
   → locate the Contracts line, copy its (folder_id=scope_...) annotation
     verbatim

2. content_metadata(folder_ids=['scope_...'])
   → returns e.g. [{"documentType": ["Terms", "Amendment"]}]
     now you know documentType exists and what it holds

3. search(search_string='2031 supplier terms changes',
          folder_ids=['scope_...'],
          metadata_filter={"path":["documentType"],
                           "operator":"equals",
                           "value":"Amendment"})

4. read_file(content_id='...') for any hit worth quoting in full
```

Step 2 is skippable when you are not filtering. Step 1 is not skippable if
the user named a folder, because step 3 needs an id that only step 1 can
give you.

## Things that go wrong

- Answering from a folder listing. `content_tree` tells you a file exists.
  It does not tell you what is in it. Open it with `read_file` or search it.
- Setting `include_subfolders=false` by default. Folders usually hold their
  files in subfolders, so this often returns nothing. "In the X folder"
  means X and everything under it. Only the user's own words ("top level
  only", "directly in") justify turning it off.
- Passing a folder name or a path where a `scope_` id is required.
- Calling `read_file` on a large document with no page range. Pass
  `start_page` and `end_page`. The error tells you the total page count when
  you get it wrong, so use that to choose a range.
