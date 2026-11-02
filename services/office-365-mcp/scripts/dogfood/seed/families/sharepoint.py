from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph

PHASES: tuple[str, ...] = ("sharepoint",)
MOVE_TARGET = "seed-v1 Move Target"
CASE_TAG = "seed-v1 case-"
FILES = Path(__file__).resolve().parents[1] / "corpus" / "files.yaml"


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    if "sharepoint" not in phases or owner != ctx.persona(1):
        return []
    return [
        Step(
            "sharepoint",
            "lookup",
            "GET",
            "/me/drive/items/root/children",
            params=(("$select", "id,name"), ("$top", "200")),
            lookup="drive-children",
        ),
        Step(
            "sharepoint",
            "create",
            "POST",
            "/me/drive/root/children",
            body={"name": MOVE_TARGET, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
            key=f"file:{MOVE_TARGET}",
        ),
    ]


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    seed_folder = f"seed-v1 {yaml.safe_load(FILES.read_text())['drive_folder']}"
    for folder in (seed_folder, MOVE_TARGET):
        found = graph.request(
            "GET", f"/me/drive/root:/{folder}", params={"$select": "id"}, ok_statuses=(404,)
        )
        if found.status_code != 200:
            continue
        children = list(
            graph.get_all(
                f"/me/drive/items/{found.json()['id']}/children",
                {"$select": "id,name", "$top": "200"},
            )
        )
        for child in children:
            if CASE_TAG in str(child.get("name")):
                yield "DELETE", f"/me/drive/items/{child['id']}"
