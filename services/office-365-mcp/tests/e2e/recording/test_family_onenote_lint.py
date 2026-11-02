import json

import pytest

from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.scrub import Corpus, normalized

NOTEBOOK = "seed-v1 Zephyr Notes"
STRINGS = frozenset({NOTEBOOK, "seed-v1 Zephyr Labs notes", "Plain words"})
CORPUS = Corpus(
    "seed-v1", STRINGS, frozenset(), (), "\x00".join(normalized(one) for one in sorted(STRINGS))
)
FILE = "bodies/x.01.json"
SHORT = f"{FILE} at note: identity #1 (plain, a short form)"


def found(text: str, identity: str = "Zephyr Labs") -> list[str]:
    files = {FILE: json.dumps({"note": text}).encode()}
    return lint_files(files, {identity}, CORPUS)


@pytest.mark.parametrize(
    "text",
    [
        NOTEBOOK,
        "contains(tolower(displayName),'seed-v1 zephyr')",
        "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents/x/seed-v1%20Zephyr%20Notes",
        "see seed-v1 Zephyr Notes.",
    ],
)
def test_a_short_form_inside_corpus_text_does_not_count(text: str) -> None:
    assert found(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "the zephyr tenant",
        "Zephyr Notes",
        "seed-v1 zephyr tenant",
        "seed-v1 Zephyrs",
        "xseed-v1 Zephyr Notes",
        f"{NOTEBOOK} and zephyr",
        "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents/zephyr",
    ],
)
def test_the_same_word_outside_corpus_text_still_counts(text: str) -> None:
    assert found(text) == [SHORT]


def test_a_full_identity_counts_even_inside_corpus_text() -> None:
    assert found("seed-v1 Zephyr Labs notes") == [f"{FILE} at note: identity #1 (plain)"]


def test_a_short_form_hidden_by_url_encoding_still_counts() -> None:
    assert found("%7a%65phyr tenant") == [
        f"{FILE} at note: identity #1 (URL-decoded x1, a short form)"
    ]
