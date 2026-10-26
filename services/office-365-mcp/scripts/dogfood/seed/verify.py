"""Read-only summary of what the seed left in one test mailbox. Usage: verify.py --as 1|2|3."""

import argparse
import json
import os
import sys
from collections import Counter

import seed

TAGGED = {"$filter": seed.TAG_FILTER, "$top": "100"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as", dest="index", type=int, choices=(1, 2, 3), required=True)
    index = parser.parse_args().index
    upns = seed.read_upns(os.environ, required=True)
    graph = seed.Graph(os.environ["GRAPH_TOKEN"])
    seed.verify_me(graph, upns, index)
    folders = {
        f["id"]: f["displayName"]
        for f in graph.get_all("/me/mailFolders", {"$top": "100", "$select": "id,displayName"})
    }
    for folder_id in [i for i, name in folders.items() if name.startswith(seed.TAG)]:
        children = graph.get_all(
            f"/me/mailFolders/{folder_id}/childFolders", {"$select": "id,displayName"}
        )
        folders.update({c["id"]: c["displayName"] for c in children})
    inbox = graph.request(
        "GET", "/me/mailFolders/inbox", params={"$select": "totalItemCount,unreadItemCount"}
    ).json()
    mails = list(
        graph.get_all(
            "/me/messages",
            {**TAGGED, "$select": "conversationId,parentFolderId,isDraft,isRead,hasAttachments"},
        )
    )
    threads = Counter(m["conversationId"] for m in mails)
    events = list(
        graph.get_all("/me/events", {**TAGGED, "$select": "type,isAllDay,start,recurrence"})
    )
    files = [f["name"] for f in graph.get_all("/me/drive/root/children", {"$select": "name"})]
    summary = {
        "inbox": {"total": inbox["totalItemCount"], "unread": inbox["unreadItemCount"]},
        "seeded_mails": len(mails),
        "drafts": sum(m["isDraft"] for m in mails),
        "by_folder": dict(Counter(folders.get(m["parentFolderId"], "?") for m in mails)),
        "with_attachments": sum(m["hasAttachments"] for m in mails),
        "threads_by_size": dict(Counter(threads.values())),
        "events": dict(Counter(e["type"] for e in events)),
        "all_day_events": sum(e["isAllDay"] for e in events),
        "event_time_zones": sorted({e["start"]["timeZone"] for e in events}),
        "seeded_folders": sorted(name for name in folders.values() if name.startswith(seed.TAG)),
        "drive_root": sorted(files),
        "requests": graph.count,
    }
    others = [
        m
        for m in graph.get_all(
            "/me/mailFolders/inbox/messages",
            {"$top": "100", "$select": "from,receivedDateTime,categories"},
        )
        if seed.TAG not in m["categories"]
    ]
    domains = Counter(
        m.get("from", {}).get("emailAddress", {}).get("address", "?").rpartition("@")[2]
        for m in others
    )
    received = sorted(m["receivedDateTime"] for m in others)
    summary["other_inbox"] = {
        "count": len(others),
        "top_sender_domains": domains.most_common(8),
        "oldest": received[0] if received else None,
        "newest": received[-1] if received else None,
    }
    summary["requests"] = graph.count
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
