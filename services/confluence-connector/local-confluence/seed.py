"""Sets up the local Confluence Data Center and fills it with test content.

A fresh volume gets the setup wizard; a set-up instance can get a new license.
In a terminal (`docker compose run --rm seed`) it asks for a license key and
prints where to get one. Without a key, or without a terminal (`up -d`), it uses
Atlassian's 3-hour timebomb license, and never replaces a license you pasted.
Content is only created when missing, so running it again is safe.

What it creates, with the fact each item holds:

    Space TEST "Connector Test"
    ├── Single ingest page        [ai-ingest]      release checklist, sign-off by Priya Nandakumar
    │   └── release-notes.txt                      code word AMBER-FALCON-42
    ├── Ingest all root           [ai-ingest-all]  handbook, Monday 09:30 in the Lindt room
    │   ├── team-budget.csv                        team leads and budgets
    │   ├── Child page                             on-call rotation, weeks 44 and 45
    │   │   └── Grandchild page                    incident runbook, review within 3 days
    │   │       └── incident-flow.png              image text: pager code ORCHID-7
    │   └── Second child page                      glossary: Heron, Nest
    └── Not ingested page         no label         COPPER-LANTERN-99, must never be found

Attachment files live in content/.
"""

import base64
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE_URL = "http://confluence:8090"
ADMIN_USER = "admin"
ADMIN_PASSWORD = os.environ["CONFLUENCE_ADMIN_PASSWORD"]
SPACE_KEY = "TEST"

TIMEBOMB_LICENSE_PATH = os.path.join(os.path.dirname(__file__), "timebomb-license.txt")
CONTENT_DIR = os.path.join(os.path.dirname(__file__), "content")

# Each page and attachment holds a distinct fact, so you can ask Unique about it
# and see where the answer came from.
PAGES = [
    {
        "title": "Single ingest page",
        "labels": ["ai-ingest"],
        "body": (
            "<p>Release checklist for the Heron test project. This page has the "
            "<code>ai-ingest</code> label, so only this page is ingested, not its children.</p>"
            "<ol><li>Freeze the main branch on Wednesday.</li>"
            "<li>Run the regression suite and attach the report.</li>"
            "<li>Get sign-off from the release manager, Priya Nandakumar.</li></ol>"
        ),
        "attachments": [("release-notes.txt", "text/plain")],
    },
    {
        "title": "Ingest all root",
        "labels": ["ai-ingest-all"],
        "body": (
            "<p>Team handbook for the Heron test project. This page has the "
            "<code>ai-ingest-all</code> label, so it and every page below it are ingested.</p>"
            "<p>The Heron teams meet every Monday at 09:30 in the Lindt room. "
            "The yearly offsite is in Lucerne in September.</p>"
        ),
        "attachments": [("team-budget.csv", "text/csv")],
    },
    {
        "title": "Child page",
        "parent": "Ingest all root",
        "body": (
            "<p>On-call rotation. This page has no label and is ingested through its parent.</p>"
            "<table><tbody>"
            "<tr><th>Week</th><th>Primary</th><th>Secondary</th></tr>"
            "<tr><td>44</td><td>Mara Jensen</td><td>Leo Brandt</td></tr>"
            "<tr><td>45</td><td>Tomas Varga</td><td>Ines Okafor</td></tr>"
            "</tbody></table>"
        ),
    },
    {
        "title": "Grandchild page",
        "parent": "Child page",
        "body": (
            "<p>Incident runbook, two levels below the <code>ai-ingest-all</code> page. "
            "The attached diagram shows the incident flow.</p>"
            "<p>Open an incident in the #heron-incidents channel, and write a review "
            "within 3 working days.</p>"
        ),
        "attachments": [("incident-flow.png", "image/png")],
    },
    {
        "title": "Second child page",
        "parent": "Ingest all root",
        "body": (
            "<p>Glossary, a second child page.</p>"
            "<ul><li><strong>Heron</strong>: the code name of the field app.</li>"
            "<li><strong>Nest</strong>: the shared staging environment.</li></ul>"
        ),
    },
    {
        "title": "Not ingested page",
        "body": (
            "<p>This page has no label and no labeled parent, so it must never be ingested. "
            "If Unique can answer what the secret marker is, the label filter is broken. "
            "Secret marker: COPPER-LANTERN-99.</p>"
        ),
    },
]

# Setup wizard: page path -> (form action, fields).
SETUP_STEPS = {
    "/setup/setuplicense.action": ("/setup/dosetuplicense.action", {}),
    "/setup/setupcluster-start.action": (
        "/setup/setupcluster.action",
        {"newCluster": "skipCluster"},
    ),
    "/setup/setupdata-start.action": (
        "/setup/setupdata.action",
        {"contentChoice": "blank"},
    ),
    "/setup/setupusermanagementchoice-start.action": (
        "/setup/setupusermanagementchoice.action",
        {"userManagementChoice": "internal"},
    ),
    "/setup/setupadministrator-start.action": (
        "/setup/setupadministrator.action",
        {
            "username": ADMIN_USER,
            "fullName": "Local Admin",
            "email": "admin@example.com",
            "password": ADMIN_PASSWORD,
            "confirm": ADMIN_PASSWORD,
        },
    ),
}

browser = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)
auth_header = (
    "Basic " + base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()).decode()
)


def log(message):
    print(f"[seed] {message}", flush=True)


def browse(path, fields=None):
    """GET, or POST a form when fields are given. Returns the final URL path and the page."""
    body = urllib.parse.urlencode(fields).encode() if fields is not None else None
    with browser.open(BASE_URL + path, body, timeout=900) as response:
        return urllib.parse.urlparse(response.geturl()).path, response.read().decode()


def atl_token(page):
    match = re.search(r'name="atl_token" value="([^"]+)"', page)
    return match.group(1) if match else ""


def ask_for_license(page, has_license):
    """Returns the key to apply, or "" to keep the current license."""
    if os.environ.get("CONFLUENCE_LICENSE_KEY"):
        return "".join(os.environ["CONFLUENCE_LICENSE_KEY"].split())

    replaceable = not has_license or "Test license" in page
    fallback = (
        "use the 3-hour timebomb license" if replaceable else "keep the current license"
    )
    key = ""
    if sys.stdin.isatty():
        server_id = re.search(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}\b", page)
        url = "https://my.atlassian.com/license/evaluation?product=Confluence"
        if server_id:
            url += f"&sid={server_id.group(0)}"
        print(
            f"\nGet a free 30-day Data Center trial license here:\n  {url}\n"
            "Paste the key, then press Enter on an empty line.\n"
            f"Or press Enter right away to {fallback}.",
            flush=True,
        )
        lines = []
        for line in sys.stdin:
            if not line.strip():
                break
            lines.append(line.strip())
        key = "".join(lines)

    if key or not replaceable:
        return key
    with open(TIMEBOMB_LICENSE_PATH) as file:
        return file.read().strip()


def wait_for_confluence():
    for _ in range(120):
        try:
            with urllib.request.urlopen(BASE_URL + "/status", timeout=10) as response:
                state = json.load(response).get("state")
        except (OSError, ValueError):
            state = None
        if state in ("FIRST_RUN", "RUNNING"):
            return state
        log(f"waiting for Confluence (state: {state})")
        time.sleep(10)
    sys.exit("[seed] Confluence did not start within 20 minutes")


def run_setup_wizard():
    # The user management choice is only kept in the session, so each step
    # continues from the page the previous one returned, not from "/".
    step, page = browse("/")
    for _ in range(60):
        if step not in SETUP_STEPS:
            log("setup finished")
            return
        log(f"setup step {step}")
        action, fields = SETUP_STEPS[step]
        if step == "/setup/setuplicense.action":
            fields = {"confLicenseString": ask_for_license(page, has_license=False)}
        next_step, page = browse(action, {**fields, "atl_token": atl_token(page)})
        if next_step == step:
            log("waiting for Confluence to finish the last step")
            time.sleep(10)
            next_step, page = browse("/")
        step = next_step
    sys.exit("[seed] setup did not finish")


def update_license():
    _, page = browse("/login.action")
    browse(
        "/dologin.action",
        {
            "os_username": ADMIN_USER,
            "os_password": ADMIN_PASSWORD,
            "atl_token": atl_token(page),
        },
    )
    _, page = browse(
        "/doauthenticate.action",
        {"password": ADMIN_PASSWORD, "destination": "/admin/license.action"},
    )
    key = ask_for_license(page, has_license=True)
    if not key:
        log("kept the current license")
        return
    _, page = browse(
        "/admin/doupdatelicense.action",
        {"licenseString": key, "atl_token": atl_token(page)},
    )
    if "aui-message-error" in page:
        sys.exit(
            "[seed] license update failed, check http://localhost:8090/admin/license.action"
        )
    log("license applied")


def api(method, path, payload=None, headers=None):
    if isinstance(payload, bytes):
        data = payload
    else:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        f"{BASE_URL}/rest/api{path}",
        data,
        {"Authorization": auth_header, "Accept": "application/json", **(headers or {})},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def ensure_space():
    try:
        api("GET", f"/space/{SPACE_KEY}")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        api("POST", "/space", {"key": SPACE_KEY, "name": "Connector Test"})
        log(f"created space {SPACE_KEY}")


def ensure_page(spec, ids):
    query = urllib.parse.urlencode({"spaceKey": SPACE_KEY, "title": spec["title"]})
    found = api("GET", f"/content?{query}")["results"]
    if found:
        page_id = found[0]["id"]
    else:
        payload = {
            "type": "page",
            "title": spec["title"],
            "space": {"key": SPACE_KEY},
            "body": {"storage": {"value": spec["body"], "representation": "storage"}},
        }
        if "parent" in spec:
            payload["ancestors"] = [{"id": ids[spec["parent"]]}]
        page_id = api("POST", "/content", payload)["id"]
        log(f"created page {spec['title']}")
    ids[spec["title"]] = page_id

    if "labels" in spec:
        api(
            "POST",
            f"/content/{page_id}/label",
            [{"prefix": "global", "name": label} for label in spec["labels"]],
        )

    for filename, mime_type in spec.get("attachments", []):
        query = urllib.parse.urlencode({"filename": filename})
        if api("GET", f"/content/{page_id}/child/attachment?{query}")["results"]:
            continue
        with open(os.path.join(CONTENT_DIR, filename), "rb") as file:
            content = file.read()
        boundary = uuid.uuid4().hex
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        api(
            "POST",
            f"/content/{page_id}/child/attachment",
            body,
            {
                "X-Atlassian-Token": "no-check",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        log(f"attached {filename} to {spec['title']}")


def main():
    if wait_for_confluence() == "FIRST_RUN":
        run_setup_wizard()
    else:
        update_license()

    ensure_space()
    ids = {}
    for spec in PAGES:
        ensure_page(spec, ids)
    log(f"done: http://localhost:8090/display/{SPACE_KEY}")
    log(
        f"log in as {ADMIN_USER}, password CONFLUENCE_PASSWORD_LOCAL_DC from .env (default: admin)"
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(f"[seed] {error.code} {error.reason} on {error.url}")
