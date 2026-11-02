from collections.abc import Mapping

_CALENDARS = "/v1.0/me/calendars/*"
_EVENT = f"{_CALENDARS}/events/*"

READ_TOOLS = frozenset(
    {
        "outlook_check_availability",
        "outlook_find_recipient",
        "outlook_find_rooms",
        "outlook_list_calendar_groups",
        "outlook_list_calendar_shares",
        "outlook_list_calendars",
        "outlook_list_contacts",
        "outlook_list_event_attachments",
        "outlook_list_event_instances",
        "outlook_list_events",
        "outlook_list_group_events",
        "outlook_list_reminders",
        "outlook_list_time_zones",
        "outlook_read_contact",
        "outlook_read_event",
        "outlook_read_event_attachment",
        "outlook_suggest_meeting_times",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "outlook_check_availability": ("POST /v1.0/me/calendar/getSchedule",),
    "outlook_suggest_meeting_times": ("POST /v1.0/me/findMeetingTimes",),
}
READ_GETS: Mapping[str, tuple[str, ...]] = {
    "outlook_list_group_events": ("GET /v1.0/groups/*/calendarView",),
}
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "outlook_cancel_event": (f"POST {_EVENT}/cancel",),
    "outlook_create_contact": ("POST /v1.0/me/contacts",),
    "outlook_create_event": ("POST /v1.0/me/events",),
    "outlook_create_event_on_behalf": (f"POST {_CALENDARS}/events",),
    "outlook_delete_calendar": (f"DELETE {_CALENDARS}",),
    "outlook_delete_event": (f"DELETE {_EVENT}",),
    "outlook_forward_event": (f"POST {_EVENT}/forward",),
    "outlook_respond_to_invite": tuple(
        f"POST {_EVENT}/{action}" for action in ("accept", "decline", "tentativelyAccept")
    ),
    "outlook_share_calendar": (f"POST {_CALENDARS}/calendarPermissions",),
    "outlook_unshare_calendar": (f"DELETE {_CALENDARS}/calendarPermissions/*",),
    "outlook_update_contact": ("PATCH /v1.0/me/contacts/*",),
    "outlook_update_event": (f"PATCH {_EVENT}",),
}
EXTERNAL = frozenset(
    {
        "outlook_cancel_event",
        "outlook_forward_event",
        "outlook_respond_to_invite",
        "outlook_share_calendar",
        "outlook_unshare_calendar",
    }
)
INVITERS = frozenset(
    {"outlook_create_event", "outlook_update_event", "outlook_cancel_event", "outlook_delete_event"}
)
_DIRECTORY = frozenset(
    {"outlook_find_recipient", "outlook_check_availability", "outlook_suggest_meeting_times"}
)
ADDRESSES: Mapping[str, frozenset[str]] = {
    "SEED_DIRECTORY_UPN": _DIRECTORY,
    "SEED_GUEST_UPN": _DIRECTORY,
    "SEED_ROOM_UPN": frozenset(
        {"outlook_create_event", "outlook_update_event", "outlook_check_availability"}
        | {"outlook_suggest_meeting_times"}
    ),
}
PREFIXES = ("/v1.0/places/",)
SCHEMA: Mapping[str, str] = {
    **dict.fromkeys(
        ("givenName", "surname", "middleName", "nickName", "companyName", "jobTitle", "department")
        + ("officeLocation", "profession", "manager", "assistantName", "spouseName", "children")
        + ("personalNotes", "businessPhones", "homePhones", "mobilePhone", "imAddresses")
        + ("contentBytes", "eventSubject", "uniqueId", "suggestionReason", "nickname", "building")
        + ("label", "floorLabel", "phone", "tags", "audioDeviceName", "videoDeviceName")
        + ("displayDeviceName", "street", "city", "state", "countryOrRegion", "postalCode")
        + ("eventWebLink",),
        "text",
    ),
    **dict.fromkeys(("eventId", "classId", "occurrenceId", "transactionId"), "id"),
    **dict.fromkeys(("mail", "userPrincipalName", "scheduleId"), "address"),
    **dict.fromkeys(("time", "startDate", "endDate", "birthday"), "date"),
    **dict.fromkeys(
        ("type", "response", "status", "role", "allowedRoles", "allowedOnlineMeetingProviders")
        + ("defaultOnlineMeetingProvider", "color", "hexColor", "locationType", "uniqueIdType")
        + ("originalStartTimeZone", "originalEndTimeZone", "recurrenceTimeZone", "alias")
        + ("onlineMeetingProvider", "class", "subclass", "availability", "daysOfWeek", "index")
        + ("organizerAvailability", "emptySuggestionsReason", "bookingType", "firstDayOfWeek"),
        "enum",
    ),
    **dict.fromkeys(
        ("isOnlineMeeting", "isOrganizer", "hasAttachments", "responseRequested", "isInline")
        + ("allowNewTimeProposals", "hideAttendees", "isReminderOn", "reminderMinutesBeforeStart")
        + ("isCancelled", "isDefaultCalendar", "canEdit", "canShare", "canViewPrivateItems")
        + ("isTallyingResponses", "isRemovable", "isInsideOrganization", "isPrivate", "capacity")
        + ("isWheelChairAccessible", "floorNumber", "relevanceScore", "confidence", "interval")
        + ("numberOfOccurrences", "month", "dayOfMonth", "availabilityView"),
        "number",
    ),
    **dict.fromkeys(("startTime", "endTime"), "time"),
    **dict.fromkeys(("onlineMeetingUrl", "joinUrl"), "url"),
    **dict.fromkeys(
        ("owner", "onlineMeeting", "responseStatus", "attendees", "recurrence", "pattern", "range")
        + ("locations", "eventStartTime", "eventEndTime", "eventLocation", "reminderFireTime")
        + ("scoredEmailAddresses", "personType", "meetingTimeSuggestions", "meetingTimeSlot")
        + ("attendeeAvailability", "attendee", "scheduleItems", "emailAddresses", "businessAddress")
        + ("homeAddress", "otherAddress", "workingHours"),
        "object",
    ),
}
NEEDS: Mapping[str, str] = {
    "rooms": (
        "Ask a Microsoft 365 administrator to create one room mailbox: in the Exchange admin "
        "center, open Recipients, then Resources, then Add resource, and choose Room. Then ask "
        "the administrator to grant the Place.Read.All permission to the app. Then run "
        "record_all.sh login and record_all.sh discover again."
    ),
    "group_calendar": (
        "Run run_all.sh apply --phases cal-group 1. The team seed-v1 team must exist first. "
        "Then run record_all.sh discover again."
    ),
    "shared_calendars": (
        "Run run_all.sh apply --phases cal-shared 2 3. Then Mia opens the two sharing mails "
        "from Anna and Tom in Outlook on the web and chooses Accept in each mail. Then run "
        "record_all.sh discover again."
    ),
    "answers": (
        "Run run_all.sh apply --phases cal-answers 1 2 3. Then wait five minutes, so that the "
        "answers reach the copy of Mia. Then run record_all.sh discover again."
    ),
}
_ANSWERED = "/me/events?$filter=responseStatus/response eq 'tentativelyAccepted'&$select=id"
PROBES: Mapping[str, tuple[int, str, int]] = {
    "rooms": (1, "/places/microsoft.graph.room", 1),
    "group_calendar": (1, "/me/joinedTeams#seed", 1),
    "shared_calendars": (1, "/me/calendars?$select=id,name", 5),
    "answers": (2, _ANSWERED, 1),
}
