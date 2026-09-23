# More worked examples

Same four tools as [SKILL.md](../SKILL.md), two more scenarios.

## Relationship management: finding a client's file by rough name

"Pull up Client Zeta's onboarding pack, I need their risk questionnaire."

```text
1. content_tree(mode='tree', folders_only=true, max_depth=2)
   → locate the Clients line, copy its (folder_id=scope_...) annotation

2. content_tree(mode='search', folder_path='scope_...',
                query='Zeta onboarding')
   → fuzzy filename match, no need to know the exact file name;
     returns content_id values, not folder ids

3. read_file(content_id='...')
```

No `content_metadata` step here. The ask is "find this file by what it's
roughly called," not "filter by a field," so `content_tree(mode='search')`
does the whole job. Reach for `search` instead only if the ask were about
the questionnaire's *content* ("what risk factors did Client Zeta flag"),
not the file itself.

## Fund reporting: a scoped search with no metadata_filter

"What did the Fund Alpha commentary say about the Q2 drawdown?"

```text
1. content_tree(mode='tree', folders_only=true, max_depth=2)
   → locate the Fund Alpha line, copy its (folder_id=scope_...) annotation

2. search(search_string='Q2 drawdown commentary',
          folder_ids=['scope_...'])

3. read_file(content_id='...', start_page=1, end_page=5)
```

No `content_metadata` step, and no `metadata_filter`, either. The folder
scope alone narrows this enough — most fund-reporting folders don't hold
thousands of files, so an unfiltered search inside the right folder is
already precise. Reach for a filter only when the folder is large enough
that an unfiltered search comes back noisy, and prefer a stable key like
`mimeType` over a custom field when one will do: "only the PDFs" needs no
`content_metadata` call at all.
