"""Sets up the local Confluence Data Center and fills it with test content.

Runs on every `docker compose up`. A fresh volume gets the setup wizard; a set-up
instance gets its timebomb license applied again, which restarts the 3 hours.
Content is only created when missing, so running it again is safe.
"""

import base64
import html
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

BASE_URL = os.environ.get("CONFLUENCE_URL", "http://confluence:8090").rstrip("/")
ADMIN_USER = "admin"
ADMIN_PASSWORD = os.environ["CONFLUENCE_ADMIN_PASSWORD"]
with open(
    os.path.join(os.path.dirname(__file__), "timebomb-license.txt")
) as license_file:
    LICENSE_KEY = (
        os.environ.get("CONFLUENCE_LICENSE_KEY") or license_file.read()
    ).strip()
SPACE_KEY = "TEST"

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

PAGES = [
    {
        "title": "Single ingest page",
        "labels": ["ai-ingest"],
        "body": "<p>Has the <code>ai-ingest</code> label, so only this page is ingested.</p>",
        "attachments": [("notes.txt", "text/plain", b"Plain text attachment.\n")],
    },
    {
        "title": "Ingest all root",
        "labels": ["ai-ingest-all"],
        "body": "<p>Has the <code>ai-ingest-all</code> label, so this page and every page below it are ingested.</p>",
        "attachments": [("report.csv", "text/csv", b"name,value\nalpha,1\nbeta,2\n")],
    },
    {
        "title": "Child page",
        "parent": "Ingest all root",
        "body": "<p>No label of its own. Ingested through its parent.</p>",
    },
    {
        "title": "Grandchild page",
        "parent": "Child page",
        "body": "<p>Two levels below the <code>ai-ingest-all</code> page.</p>",
        "attachments": [("pixel.png", "image/png", PNG_BYTES)],
    },
    {
        "title": "Second child page",
        "parent": "Ingest all root",
        "body": "<p>A second child, to check siblings.</p>",
    },
    {
        "title": "Not ingested page",
        "body": "<p>No label and no labeled parent. Must never be ingested.</p>",
    },
]

jar = http.cookiejar.CookieJar()
browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
auth_header = (
    "Basic " + base64.b64encode(f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()).decode()
)


def log(message):
    print(f"[seed] {message}", flush=True)


def form_post(path, fields):
    body = urllib.parse.urlencode(fields).encode()
    with browser.open(BASE_URL + path, body, timeout=900) as response:
        return response.geturl(), response.read().decode("utf-8", "replace")


def page_get(path):
    with browser.open(BASE_URL + path, timeout=120) as response:
        return response.geturl(), response.read().decode("utf-8", "replace")


def atl_token(page):
    match = re.search(r'name="atl_token" value="([^"]+)"', page)
    return match.group(1) if match else ""


def status():
    try:
        with urllib.request.urlopen(BASE_URL + "/status", timeout=10) as response:
            return json.load(response).get("state")
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None


def wait_for_confluence():
    for _ in range(120):
        state = status()
        if state in ("FIRST_RUN", "RUNNING"):
            return state
        log(f"waiting for Confluence (state: {state})")
        time.sleep(10)
    sys.exit("[seed] Confluence did not start within 20 minutes")


def run_setup_wizard():
    # The user management choice is only kept in the session, so each step
    # continues from the page the previous one returned, not from "/".
    url, page = page_get("/")
    previous_step = None
    for _ in range(60):
        step = urllib.parse.urlparse(url).path
        if step == previous_step:
            log(f"still at {step}, waiting for Confluence to finish the last step")
            time.sleep(10)
            url, page = page_get("/")
            step = urllib.parse.urlparse(url).path
        previous_step = step
        log(f"setup step {step}")
        token = atl_token(page)
        if "setuplicense" in step:
            field = re.search(r'<textarea[^>]*name="([^"]+)"', page)
            url, page = form_post(
                "/setup/dosetuplicense.action",
                {
                    "atl_token": token,
                    (field.group(1) if field else "confLicenseString"): LICENSE_KEY,
                },
            )
        elif "setupcluster" in step:
            url, page = form_post(
                "/setup/setupcluster.action",
                {
                    "atl_token": token,
                    "newCluster": "skipCluster",
                    "isClusteringEnabled": "true",
                },
            )
        elif "setupdata" in step:
            log("creating the empty site, this takes a minute")
            url, page = form_post(
                "/setup/setupdata.action",
                {
                    "atl_token": token,
                    "contentChoice": "blank",
                    "dbchoiceSelect": "Empty Site",
                },
            )
        elif "setupusermanagementchoice" in step:
            url, page = form_post(
                "/setup/setupusermanagementchoice.action",
                {
                    "atl_token": token,
                    "userManagementChoice": "internal",
                    "internal": "Manage users and groups within Confluence",
                },
            )
        elif "setupadministrator" in step:
            url, page = form_post(
                "/setup/setupadministrator.action",
                {
                    "atl_token": token,
                    "username": ADMIN_USER,
                    "fullName": "Local Admin",
                    "email": "admin@example.com",
                    "password": ADMIN_PASSWORD,
                    "confirm": ADMIN_PASSWORD,
                    "setup-next-button": "Next",
                },
            )
        elif "finishsetup" in step or not step.startswith("/setup"):
            log("setup finished")
            return
        else:
            sys.exit(f"[seed] unexpected setup step {step}")
    sys.exit("[seed] setup did not finish")


def renew_license():
    _, login_page = page_get("/login.action")
    form_post(
        "/dologin.action",
        {
            "os_username": ADMIN_USER,
            "os_password": ADMIN_PASSWORD,
            "login": "Log in",
            "atl_token": atl_token(login_page),
        },
    )
    form_post(
        "/doauthenticate.action",
        {
            "password": ADMIN_PASSWORD,
            "authenticate": "Confirm",
            "destination": "/admin/license.action",
        },
    )
    _, license_page = page_get("/admin/license.action")
    _, result = form_post(
        "/admin/doupdatelicense.action",
        {
            "atl_token": atl_token(license_page),
            "licenseString": LICENSE_KEY,
            "update": "Save",
        },
    )
    if "aui-message-error" in result:
        sys.exit(f"[seed] license update failed, check {BASE_URL}/admin/license.action")
    log("license applied again, valid for the next 3 hours")


def api(method, path, payload=None, headers=None):
    request = urllib.request.Request(BASE_URL + "/rest/api" + path, method=method)
    request.add_header("Authorization", auth_header)
    request.add_header("Accept", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    data = None
    if isinstance(payload, bytes):
        data = payload
    elif payload is not None:
        data = json.dumps(payload).encode()
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, data, timeout=60) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def ensure_space():
    try:
        api("GET", f"/space/{SPACE_KEY}")
        return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    api("POST", "/space", {"key": SPACE_KEY, "name": "Connector Test"})
    log(f"created space {SPACE_KEY}")


def find_page(title):
    query = urllib.parse.urlencode(
        {"spaceKey": SPACE_KEY, "title": title, "type": "page"}
    )
    results = api("GET", f"/content?{query}")["results"]
    return results[0]["id"] if results else None


def ensure_page(spec, ids):
    page_id = find_page(spec["title"])
    if not page_id:
        payload = {
            "type": "page",
            "title": spec["title"],
            "space": {"key": SPACE_KEY},
            "body": {"storage": {"value": spec["body"], "representation": "storage"}},
        }
        if spec.get("parent"):
            payload["ancestors"] = [{"id": ids[spec["parent"]]}]
        page_id = api("POST", "/content", payload)["id"]
        log(f"created page {spec['title']}")
    ids[spec["title"]] = page_id

    if spec.get("labels"):
        api(
            "POST",
            f"/content/{page_id}/label",
            [{"prefix": "global", "name": label} for label in spec["labels"]],
        )

    for filename, mime_type, content in spec.get("attachments", []):
        query = urllib.parse.urlencode({"filename": filename})
        if api("GET", f"/content/{page_id}/child/attachment?{query}")["results"]:
            continue
        boundary = uuid.uuid4().hex
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
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
        renew_license()

    for _ in range(30):
        if status() == "RUNNING":
            break
        time.sleep(10)

    ensure_space()
    ids = {}
    for spec in PAGES:
        ensure_page(spec, ids)
    log(f"done: {BASE_URL.replace('confluence:', 'localhost:')}/display/{SPACE_KEY}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit(
            f"[seed] {error.code} {error.reason} on {error.url}: {html.unescape(error.read().decode('utf-8', 'replace'))[:300]}"
        )
