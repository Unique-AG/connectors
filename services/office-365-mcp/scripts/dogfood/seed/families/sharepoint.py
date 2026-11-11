import datetime as dt
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docgen
import yaml
from model import ConfigError, Context, Step, site_id

from families.onenote import ASSETS, team_id
from families.teams import TEAM_NAME

if TYPE_CHECKING:
    from seed import Graph

type Spec = Mapping[str, Any]

TAG = "seed-v1"
LIST_PHASE = "lists"
PHASES: tuple[str, ...] = ("sharepoint", "files-tree", "files-big", "team-files", LIST_PHASE)
OPT_IN = (LIST_PHASE,)
MOVE_TARGET = "seed-v1 Move Target"
CASE_TAG = "seed-v1 case-"
CORPUS = Path(__file__).resolve().parents[1] / "corpus"
INLINE_MAX = 3 * 1024 * 1024
TYPES = {
    "txt": "text/plain",
    "filler-text": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "png": "image/png",
}
FAIL = {"@microsoft.graph.conflictBehavior": "fail"}
LISTING = (("$select", "id,name"), ("$top", "200"))
CHILDREN = {"$select": "id,name,folder", "$top": "200"}
TEAM_PHASE = "team-files"
TEAM = f"{{{TEAM_PHASE}:{TEAM_NAME}}}"
TEAM_DRIVE = f"{TEAM_PHASE}:drive"
CHANNEL_FOLDER = f"{TEAM_PHASE}:channel folder"
ABSENT = (400, 403, 404)
SITE = f"{LIST_PHASE}:site"
ROWS = (("$select", "id"), ("$expand", "fields($select=Title)"))


def _named(name: str) -> str:
    return f"{TAG} {name}"


def _key(name: str) -> str:
    return f"file:{_named(name)}"


def _corpus() -> Spec:
    return yaml.safe_load((CORPUS / "files-tree.yaml").read_text(encoding="utf-8"))


def _seed_folder() -> str:
    files = yaml.safe_load((CORPUS / "files.yaml").read_text(encoding="utf-8"))
    return _named(files["drive_folder"])


def _bytes(spec: Spec, ctx: Context) -> bytes:
    props = {
        name: ctx.display_name(value) if name in ("creator", "last_modified_by") else value
        for name, value in spec.get("properties", {}).items()
    }
    match spec["kind"]:
        case "txt":
            return str(spec["text"]).encode()
        case "docx":
            return docgen.docx(spec["paragraphs"], props)
        case "xlsx":
            return docgen.xlsx(spec["rows"], props)
        case "png":
            return ASSETS[f"{TAG} Gallery picture.png"]
        case kind if kind in docgen.GENERATORS:
            return docgen.generate(kind, spec["size"], spec["label"])
    raise ConfigError(f"{spec['name']}: unknown file kind {spec['kind']}")


def _written(ctx: Context, spec: Spec, drive: str, parent: str, phase: str) -> Step:
    name, data = _named(spec["name"]), _bytes(spec, ctx)
    at = f"{drive}/items/{{{parent}}}:/{name}:"
    generated = (spec["kind"], spec["size"], spec["label"]) if "size" in spec else None
    hours = spec.get("age_hours")
    if len(data) <= INLINE_MAX and hours is None:
        return Step(
            spec.get("phase", phase),
            "create",
            "PUT",
            f"{at}/content",
            body=data,
            content_type=TYPES[spec["kind"]],
            key=f"file:{name}",
            generated=generated,
        )
    item: dict[str, Any] = dict(FAIL)
    if hours is not None:
        changed = dt.datetime.combine(ctx.anchor, dt.time.min, dt.UTC) - dt.timedelta(hours=hours)
        item["fileSystemInfo"] = {"lastModifiedDateTime": f"{changed:%Y-%m-%dT%H:%M:%SZ}"}
    return Step(
        spec.get("phase", phase),
        "upload",
        "POST",
        f"{at}/createUploadSession",
        body={"item": item},
        key=f"file:{name}",
        payload=data,
        generated=generated,
    )


def _invite(ctx: Context, spec: Spec, phase: str) -> Step:
    address = ctx.address(spec["share_with"])["emailAddress"]["address"]
    body = {
        "recipients": [{"email": address}],
        "roles": ["read"],
        "requireSignIn": True,
        "sendInvitation": False,
    }
    path = f"/me/drive/items/{{{_key(spec['name'])}}}/invite"
    return Step(phase, "create", "POST", path, body=body, key=f"invite:{_named(spec['name'])}")


def _listing(drive: str, parent: str, phase: str) -> Step:
    path = f"{drive}/items/{{{parent}}}/children"
    return Step(phase, "lookup", "GET", path, LISTING, lookup="drive-children")


def _folder(drive: str, parent: str, name: str, phase: str) -> Step:
    body = {"name": _named(name), "folder": {}} | FAIL
    path = f"{drive}/items/{{{parent}}}/children"
    return Step(phase, "create", "POST", path, body=body, key=_key(name))


def _tree(
    ctx: Context, drive: str, root: str, folders: list[Spec], files: list[Spec], phase: str
) -> list[Step]:
    found = [_listing(drive, root, phase)]
    for folder in folders:
        parent = _key(folder["parent"]) if "parent" in folder else root
        found += [_folder(drive, parent, folder["name"], phase)]
        found += [_listing(drive, _key(folder["name"]), phase)]
    for spec in files:
        parent = _key(spec["folder"]) if "folder" in spec else root
        found += [_written(ctx, spec, drive, parent, phase)]
        found += [_invite(ctx, spec, phase)] if "share_with" in spec else []
    return found


def _drive(ctx: Context, owner: str, phases: set[str], corpus: Spec) -> list[Step]:
    files = [
        f
        for f in corpus["files"]
        if f.get("owner", "mia") == owner and f.get("phase", "files-tree") in phases
    ]
    if not files:
        return []
    phase = "files-tree" if "files-tree" in phases else "files-big"
    folders = corpus["folders"] if owner == "mia" and phase == "files-tree" else []
    root, name = "drive:folder", _seed_folder()
    lookup = Step(
        phase,
        "lookup",
        "GET",
        f"/me/drive/root:/{name}",
        (("$select", "id,name,folder"),),
        lookup="drive-folder",
    )
    body = {"name": name, "folder": {}} | FAIL
    made = Step(phase, "create", "POST", "/me/drive/root/children", body=body, key=root)
    return [lookup, made, *_tree(ctx, "/me/drive", root, folders, files, phase)]


def _team(ctx: Context, corpus: Spec) -> list[Step]:
    team, phase = corpus["team"], TEAM_PHASE
    channel, drive = _named(team["channel"]), f"/drives/{{{TEAM_DRIVE}}}"
    channels, top = f"/teams/{{{phase}:{TEAM_NAME}}}/channels", team["folders"][0]["name"]
    name = (("$select", "id,displayName"),)
    return [
        Step(phase, "lookup", "GET", "/me/joinedTeams", name, lookup="named", learns="team"),
        Step(
            phase,
            "lookup",
            "GET",
            f"/groups/{{{phase}:{TEAM_NAME}}}/drive",
            (("$select", "id"),),
            key=TEAM_DRIVE,
            lookup="single",
            learns="drive",
        ),
        Step(phase, "lookup", "GET", channels, name, lookup="named"),
        Step(
            phase,
            "create",
            "POST",
            channels,
            body={"displayName": channel, "membershipType": "standard"},
            key=f"{phase}:{channel}",
        ),
        Step(
            phase,
            "lookup",
            "GET",
            f"{channels}/{{{phase}:{channel}}}/filesFolder",
            key=CHANNEL_FOLDER,
            lookup="single",
        ),
        *_tree(ctx, drive, CHANNEL_FOLDER, [], team["channel_files"], phase),
        Step(phase, "lookup", "GET", f"{drive}/root/children", LISTING, lookup="drive-children"),
        Step(
            phase,
            "create",
            "POST",
            f"{drive}/root/children",
            body={"name": _named(top), "folder": {}} | FAIL,
            key=_key(top),
        ),
        *_tree(ctx, drive, _key(top), team["folders"][1:], team["files"], phase),
    ]


def _lists(corpus: Spec) -> list[Step]:
    spec, phase = corpus["lists"], LIST_PHASE
    folder, lists = _named(spec["folder"]), f"/sites/{{{SITE}}}/lists"
    name = (("$select", "id,displayName"),)
    found = [
        Step(
            phase,
            "lookup",
            "GET",
            "/me/drive/items/root/children",
            LISTING,
            lookup="drive-children",
        ),
        Step(
            phase,
            "create",
            "POST",
            "/me/drive/root/children",
            body={"name": folder, "folder": {}} | FAIL,
            key=f"file:{folder}",
        ),
        Step(phase, "lookup", "GET", "/me/joinedTeams", name, lookup="named", learns="team"),
        Step(
            phase,
            "lookup",
            "GET",
            f"/groups/{{{phase}:{TEAM_NAME}}}/drive",
            (("$select", "id,sharepointIds"),),
            key=SITE,
            lookup="site",
            learns="site",
        ),
        Step(phase, "lookup", "GET", lists, name, lookup="named"),
    ]
    for one in spec["lists"]:
        key = f"{phase}:{_named(one['name'])}"
        at = f"{lists}/{{{key}}}"
        body = {"displayName": _named(one["name"]), "list": {"template": "genericList"}}
        found += [Step(phase, "create", "POST", lists, body=body, key=key)]
        if columns := one.get("columns", []):
            params = (("$select", "id,name"),)
            found += [
                Step(phase, "lookup", "GET", f"{at}/columns", params, key=key, lookup="columns")
            ]
        found += [
            Step(phase, "create", "POST", f"{at}/columns", body=c, key=f"column:{key}:{c['name']}")
            for c in columns
        ]
        if rows := one.get("rows", []):
            found += [Step(phase, "lookup", "GET", f"{at}/items", ROWS, lookup="named")]
        for row in rows:
            fields = row | {"Title": _named(row["Title"])}
            key = f"{phase}:{fields['Title']}"
            found += [
                Step(phase, "create", "POST", f"{at}/items", body={"fields": fields}, key=key)
            ]
    return found


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    corpus, found = _corpus(), []
    if "sharepoint" in phases and owner == ctx.persona(1):
        found += [
            Step(
                "sharepoint",
                "lookup",
                "GET",
                "/me/drive/items/root/children",
                LISTING,
                lookup="drive-children",
            ),
            Step(
                "sharepoint",
                "create",
                "POST",
                "/me/drive/root/children",
                body={"name": MOVE_TARGET, "folder": {}} | FAIL,
                key=f"file:{MOVE_TARGET}",
            ),
        ]
    found += _drive(ctx, owner, phases & {"files-tree", "files-big"}, corpus)
    if TEAM_PHASE in phases and owner == ctx.persona(1):
        found += _team(ctx, corpus)
    if LIST_PHASE in phases and owner == ctx.persona(1):
        found += _lists(corpus)
    return found


def _children(graph: Graph, path: str) -> list[dict[str, Any]]:
    return list(graph.get_all(path, CHILDREN))


def _id_at(graph: Graph, path: str) -> str | None:
    found = graph.request("GET", path, params={"$select": "id"}, ok_statuses=ABSENT)
    return str(found.json()["id"]) if found.status_code == 200 else None


def _team_drive(graph: Graph) -> dict[str, Any] | None:
    team = team_id(graph)
    params = {"$select": "id,sharepointIds"}
    found = (
        None
        if team is None
        else graph.request("GET", f"/groups/{team}/drive", params=params, ok_statuses=ABSENT)
    )
    if found is None or found.status_code != 200:
        return None
    drive = found.json()
    graph.learn("drive", str(drive["id"]))
    if (site := site_id(drive)) is not None:
        graph.learn("site", site)
    return drive


def _case_rows(graph: Graph, drive: Spec) -> Iterator[tuple[str, str]]:
    if (site := site_id(drive)) is None:
        return
    names = {_named(one["name"]) for one in _corpus()["lists"]["lists"]}
    lists = f"/sites/{site}/lists"
    for found in graph.get_all(lists, {"$select": "id,displayName"}):
        if found.get("displayName") not in names:
            continue
        for row in graph.get_all(f"{lists}/{found['id']}/items", dict(ROWS)):
            if str((row.get("fields") or {}).get("Title", "")).startswith(CASE_TAG):
                yield "DELETE", f"{lists}/{found['id']}/items/{row['id']}"


def _cases_below(
    graph: Graph, drive: str, folder: str, depth: int = 3
) -> Iterator[tuple[str, str]]:
    for child in _children(graph, f"{drive}/items/{folder}/children"):
        name = str(child.get("name"))
        if CASE_TAG in name:
            yield "DELETE", f"{drive}/items/{child['id']}"
        elif depth and child.get("folder") is not None and name.startswith(f"{TAG} "):
            yield from _cases_below(graph, drive, str(child["id"]), depth - 1)


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    for name in (_seed_folder(), MOVE_TARGET):
        if (folder := _id_at(graph, f"/me/drive/root:/{name}")) is not None:
            yield from _cases_below(graph, "/me/drive", folder)
    team = _team_drive(graph) if owner == "mia" else None
    if team is None:
        return
    drive, top = team["id"], _named(_corpus()["team"]["folders"][0]["name"])
    for child in _children(graph, f"/drives/{drive}/root/children"):
        if child.get("name") == top:
            yield from _cases_below(graph, f"/drives/{drive}", str(child["id"]))
    yield from _case_rows(graph, team)


def cleanup(
    graph: Graph, ctx: Context, owner: str, phases: set[str]
) -> Iterator[tuple[str, str, None]]:
    corpus = _corpus()
    names = {
        _named(f["name"])
        for f in corpus["files"]
        if f.get("owner", "mia") == owner and f.get("phase", "files-tree") in phases
    }
    if owner == "mia" and "files-tree" in phases:
        names |= {_named(f["name"]) for f in corpus["folders"] if "parent" not in f}
    if names and (folder := _id_at(graph, f"/me/drive/root:/{_seed_folder()}")) is not None:
        for child in _children(graph, f"/me/drive/items/{folder}/children"):
            if child.get("name") in names:
                yield "DELETE", f"/me/drive/items/{child['id']}", None
    if (
        not phases & {TEAM_PHASE, LIST_PHASE}
        or owner != "mia"
        or (found := _team_drive(graph)) is None
    ):
        return
    if LIST_PHASE in phases:
        yield from ((method, path, None) for method, path in _case_rows(graph, found))
    if TEAM_PHASE not in phases:
        return
    drive, team = found["id"], corpus["team"]
    top, channel = _named(team["folders"][0]["name"]), _named(team["channel"])
    notes = {_named(f["name"]) for f in team["channel_files"]}
    for child in _children(graph, f"/drives/{drive}/root/children"):
        if child.get("name") == top:
            yield "DELETE", f"/drives/{drive}/items/{child['id']}", None
        elif child.get("name") == channel:
            for note in _children(graph, f"/drives/{drive}/items/{child['id']}/children"):
                if note.get("name") in notes:
                    yield "DELETE", f"/drives/{drive}/items/{note['id']}", None
