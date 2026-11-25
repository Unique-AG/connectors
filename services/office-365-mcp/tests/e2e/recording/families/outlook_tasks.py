from collections.abc import Mapping

_LISTS = "/v1.0/me/todo/lists"
_LIST = f"{_LISTS}/*"
_TASK = f"{_LIST}/tasks/*"

READ_TOOLS = frozenset(
    {
        "outlook_list_task_lists",
        "outlook_list_tasks",
        "outlook_read_task",
        "outlook_read_task_attachment",
    }
)
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "outlook_create_task_list": (f"POST {_LISTS}",),
    "outlook_rename_task_list": (f"PATCH {_LIST}",),
    "outlook_delete_task_list": (f"DELETE {_LIST}",),
    "outlook_create_task": (f"POST {_LIST}/tasks",),
    "outlook_update_task": (f"PATCH {_TASK}",),
    "outlook_set_task_status": (f"PATCH {_TASK}",),
    "outlook_delete_task": (f"DELETE {_TASK}",),
    "outlook_add_task_step": (f"POST {_TASK}/checklistItems",),
    "outlook_update_task_step": (f"PATCH {_TASK}/checklistItems/*",),
    "outlook_delete_task_step": (f"DELETE {_TASK}/checklistItems/*",),
    "outlook_add_task_link": (f"POST {_TASK}/linkedResources",),
    "outlook_delete_task_link": (f"DELETE {_TASK}/linkedResources/*",),
    "outlook_delete_task_attachment": (f"DELETE {_TASK}/attachments/*",),
}
CREATED_ONLY: Mapping[str, int] = {
    "outlook_rename_task_list": 0,
    "outlook_delete_task_list": 0,
    "outlook_update_task": 1,
    "outlook_set_task_status": 1,
    "outlook_delete_task": 1,
    "outlook_add_task_step": 1,
    "outlook_add_task_link": 1,
    "outlook_update_task_step": 2,
    "outlook_delete_task_step": 2,
    "outlook_delete_task_link": 2,
}
SCHEMA: Mapping[str, str] = {
    **dict.fromkeys(("applicationName", "contentBytes"), "text"),
    "externalId": "id",
    **dict.fromkeys(
        ("bodyLastModifiedDateTime", "checkedDateTime", "startDate", "endDate"), "date"
    ),
    **dict.fromkeys(
        ("wellknownListName", "status", "type", "daysOfWeek", "firstDayOfWeek", "index")
        + ("recurrenceTimeZone",),
        "enum",
    ),
    **dict.fromkeys(
        ("isOwner", "isShared", "isReminderOn", "isChecked", "interval", "month", "dayOfMonth")
        + ("numberOfOccurrences",),
        "number",
    ),
    **dict.fromkeys(
        ("reminderDateTime", "recurrence", "pattern", "range", "checklistItems", "linkedResources")
        + ("attachments",),
        "object",
    ),
}
