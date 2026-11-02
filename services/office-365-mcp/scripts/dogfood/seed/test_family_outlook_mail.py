"""Offline tests for the outlook-mail seed family."""

import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import outlook_mail

CASE = outlook_mail.CASE
SEEDED = {"id": "seeded", "subject": "Q3 budget review", "categories": ["seed-v1", "Finance"]}
SEEDED_FOLDER = {"id": "folder-seed", "displayName": "seed-v1 Archive"}
PERSONAS = "mia@lake.example,anna@lake.example,tom@lake.example"


@pytest.fixture(autouse=True)
def personas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_UPNS", PERSONAS)


def a_message(
    identifier: str, subject: str, categories: list[str] | None = None, sender: str | None = None
) -> dict[str, Any]:
    found: dict[str, Any] = {"id": identifier, "subject": subject, "categories": categories or []}
    return found | ({"from": {"emailAddress": {"address": sender}}} if sender else {})


class FakeGraph:
    def __init__(self, collections: Mapping[str, list[dict[str, Any]]]) -> None:
        self.collections = collections
        self.asked: list[str] = []

    def get_all(self, path: str, params: Mapping[str, str]) -> Iterator[dict[str, Any]]:
        self.asked.append(path)
        yield from self.collections.get(path, [])


def swept(collections: Mapping[str, list[dict[str, Any]]]) -> list[tuple[str, str]]:
    return list(outlook_mail.sweep(FakeGraph(collections), "mia"))


def test_the_family_adds_no_phase_and_no_step() -> None:
    assert outlook_mail in seed.FAMILIES
    assert outlook_mail.PHASES == ()
    assert outlook_mail.steps(None, "mia", set(seed.PHASES)) == []


def test_the_sweep_names_only_the_items_of_a_case() -> None:
    reply = a_message("reply", "RE: Q3", [f"{CASE}outlook_draft_reply-x"], "anna@lake.example")
    draft = a_message("draft", f"{CASE}outlook_draft_mail-basic")
    found = swept(
        {
            "/me/mailFolders/inbox/messages": [SEEDED],
            "/me/mailFolders/drafts/messages": [SEEDED, draft, reply],
            "/me/mailFolders": [SEEDED_FOLDER, {"id": "f1", "displayName": f"{CASE}x"}],
            "/me/mailFolders/deleteditems/childFolders": [{"id": "f2", "displayName": f"{CASE}y"}],
            "/me/mailFolders/inbox/messageRules": [
                {"id": "r1", "displayName": f"{CASE}rule"},
                {"id": "r2", "displayName": "Billing"},
            ],
            "/me/outlook/masterCategories": [
                {"id": "c1", "displayName": f"{CASE}category"},
                {"id": "c2", "displayName": "Website"},
            ],
        }
    )
    assert found == [
        ("DELETE", "/me/messages/draft"),
        ("DELETE", "/me/messages/reply"),
        ("POST", "/me/mailFolders/f1/permanentDelete"),
        ("POST", "/me/mailFolders/f2/permanentDelete"),
        ("DELETE", "/me/mailFolders/inbox/messageRules/r1"),
        ("DELETE", "/me/outlook/masterCategories/c1"),
    ]


def test_the_sweep_keeps_what_only_mentions_the_marker_or_comes_from_outside() -> None:
    mentions = a_message("m1", f"Fwd: {CASE} lunch with Carol", sender="carol@elsewhere.example")
    category = a_message("m2", "Lunch", [f"Work {CASE} stuff"])
    outsider = a_message("m3", f"{CASE}lunch", sender="carol@elsewhere.example")
    found = swept(
        {
            "/me/mailFolders/inbox/messages": [mentions, category, outsider],
            "/me/mailFolders/deleteditems/messages": [mentions],
            "/me/outlook/masterCategories": [{"id": "c1", "displayName": f"Work {CASE} stuff"}],
        }
    )
    assert found == []


def test_the_sweep_drops_an_override_of_a_test_user_only() -> None:
    own = {"id": "o1", "senderEmailAddress": {"address": "anna@LAKE.example"}}
    colleague = {"id": "o2", "senderEmailAddress": {"address": "colleague@lake.example"}}
    outside = {"id": "o3", "senderEmailAddress": {"address": "x@elsewhere.example"}}
    found = swept(
        {"/me/inferenceClassification/overrides": [own, colleague, outside, {"id": "o4"}]}
    )
    assert found == [("DELETE", "/me/inferenceClassification/overrides/o1")]


def test_the_sweep_reads_the_folders_that_always_exist() -> None:
    graph = FakeGraph({})
    assert list(outlook_mail.sweep(graph, "anna")) == []
    assert graph.asked[:4] == [
        f"/me/mailFolders/{f}/messages" for f in outlook_mail.MESSAGE_FOLDERS
    ]
