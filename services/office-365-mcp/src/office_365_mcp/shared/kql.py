"""Keyword Query Language quoting: a caller's words as terms Graph reads as text, never as syntax.

Every full-text search this connector makes is KQL, whatever endpoint carries it. `$search` on a
mail collection and `POST /search/query` over Teams messages read the same operators.

The quoting is shared here rather than copied into each tool, because a copy can drift out of
sync with this one. KQL's boolean operators are ordinary words in uppercase, so a caller's own
`OR` between two words turns a promised AND into an OR. If one tool quotes correctly and another
does not, they answer the same question two different ways, and neither answer looks wrong.

Nothing here builds a term. Which property a value is filtered on, and what that property is
called, is each tool's own knowledge. Microsoft spells the scope terms differently per entity.
"""

import re

# Characters KQL reads as syntax instead of as text: whitespace separates terms, `:` `<` `>` `=`
# introduce a property restriction, `(` `)` group, `"` closes the quoting applied here, and `*` is
# the wildcard. A leading `-` is NOT an operator. `+` is AND, the default anyway, so it needs no
# handling.
_KQL_OPERATORS = re.compile(r'[\s:"<>=()*]')

# KQL's boolean and proximity operators are themselves words, and "the operators are case-sensitive
# (uppercase)", so the comparison below is too: a bare `OR` between two of the caller's words turns
# the promised AND into an OR. `quoted` skips this — `from:OR` names a sender, not an operator.
_KQL_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR", "ONEAR"})

# Quoting a caller's free text like a filter value costs the caller every match whose words are
# not adjacent. KQL documents a quoted phrase as matching only words "located next to each
# other", and it documents unquoted free-text expressions as ANDed together
# (https://learn.microsoft.com/en-us/sharepoint/dev/general-development/keyword-query-language-kql-syntax-reference).
# So free text here is guarded one word at a time. This preserves a caller's own quotes.
_PHRASE = re.compile(r'"([^"]*)"')


def as_search_value(clause: str) -> str:
    """A built KQL clause as the value of an OData `$search`, which is a quoted string.

    Two quoting layers meet here and they are not the same rule. Inside the clause, KQL escapes a
    quote by doubling it, which `phrase` does. Around the clause, `$search` takes a double-quoted
    string, and the only escaping rule Microsoft publishes for it is "if it contains double quotes
    or backslash, escape it with a backslash"
    (https://learn.microsoft.com/en-us/graph/search-query-parameter).

    TRAP: wrapping without escaping is what a naive f-string does. It produces
    `$search="from:"Bob Vance""` for any multi-word value. The result is a string that ends at
    the third quote and leaves the rest as syntax. Every single-word example Microsoft publishes
    for a mail collection hides this, because a single word is never quoted by `phrase`.

    Microsoft states this escaping rule only in the directory-object section. It publishes no
    multi-word example for a mail collection. So this module applies the rule from that one
    document, not from a document about this endpoint. That is the weakest link here, and it is
    worth a live check.
    """
    escaped = clause.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def phrase(text: str) -> str:
    """`text` as a KQL phrase: matched where the words are adjacent, and read as no operator.

    The quoting is the guard as much as the phrase. KQL escapes a quote by doubling it, which keeps
    the count even, so the quoting cannot be closed from inside.
    """
    return '"' + text.replace('"', '""') + '"'


# TRAP: a filter value needs the wildcard rule as much as a word does. KQL documents `<property>:*`
# as matching every item with a value, so a sender of `*` asks for every message that has one.
# That request reaches past the refusal of a search with no criteria, because it still matches
# every message.
def quoted(value: str) -> str:
    """A filter value, safe to put after a scope term. One value, therefore at most one term."""
    if _needs_quoting(value):
        return phrase(value)
    return value


def free_text(query: str) -> str:
    """A caller's own words, as terms Graph will AND. Empty when they typed nothing to look for.

    Double-quoted runs stay one phrase. An unbalanced quote counts as one character in a word.
    """
    terms: list[str] = []
    words_from = 0
    for match in _PHRASE.finditer(query):
        terms.extend(_keywords(query[words_from : match.start()]))
        inside = match.group(1).strip()
        if inside:
            terms.append(phrase(inside))
        words_from = match.end()
    terms.extend(_keywords(query[words_from:]))
    return " ".join(terms)


def flag(value: bool) -> str:
    return "true" if value else "false"


def _needs_quoting(text: str) -> bool:
    return _KQL_OPERATORS.search(text) is not None or text.startswith("-")


def _keywords(text: str) -> list[str]:
    return [_keyword(word) for word in text.split()]


def _keyword(word: str) -> str:
    if _needs_quoting(word) or word in _KQL_KEYWORDS:
        return phrase(word)
    return word
