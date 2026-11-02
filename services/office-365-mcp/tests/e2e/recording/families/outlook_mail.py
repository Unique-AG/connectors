from collections.abc import Mapping

READ_TOOLS = frozenset(
    {
        "outlook_get_mail_tips",
        "outlook_list_attachments",
        "outlook_list_mail",
        "outlook_read_attachment",
        "outlook_read_mail",
        "outlook_read_thread",
        "outlook_search_mail",
    }
)
READ_POSTS: Mapping[str, tuple[str, ...]] = {
    "outlook_get_mail_tips": ("POST /v1.0/me/getMailTips",),
    "outlook_search_mail": ("POST /v1.0/me/translateExchangeIds",),
}
_MESSAGES = "/v1.0/me/messages"
_FOLDERS = "/v1.0/me/mailFolders"
_RULES = f"{_FOLDERS}/inbox/messageRules"
_OVERRIDES = "/v1.0/me/inferenceClassification/overrides"
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "outlook_browse_folders": (),
    "outlook_get_mailbox_settings": (),
    "outlook_list_categories": (),
    "outlook_list_focused_overrides": (),
    "outlook_copy_mail": (f"POST {_MESSAGES}/*/copy",),
    "outlook_create_category": ("POST /v1.0/me/outlook/masterCategories",),
    "outlook_create_folder": (f"POST {_FOLDERS}", f"POST {_FOLDERS}/*/childFolders"),
    "outlook_create_mail_rule": (f"POST {_RULES}",),
    "outlook_delete_folder": (f"POST {_FOLDERS}/*/move",),
    "outlook_delete_mail_rule": (f"DELETE {_RULES}/*",),
    "outlook_disable_mail_rule": (f"PATCH {_RULES}/*",),
    "outlook_draft_mail": (f"POST {_MESSAGES}",),
    "outlook_draft_reply": (
        f"POST {_MESSAGES}/*/createReply",
        f"POST {_MESSAGES}/*/createForward",
        f"PATCH {_MESSAGES}/*",
    ),
    "outlook_draft_reply_all": (f"POST {_MESSAGES}/*/createReplyAll", f"PATCH {_MESSAGES}/*"),
    "outlook_mark_mail": (f"PATCH {_MESSAGES}/*",),
    "outlook_move_mail": (f"POST {_MESSAGES}/*/move",),
    "outlook_rename_folder": (f"PATCH {_FOLDERS}/*",),
    "outlook_send_draft": (f"POST {_MESSAGES}/*/send",),
    "outlook_set_automatic_reply": ("PATCH /v1.0/me/mailboxSettings",),
    "outlook_set_focused_override": (f"POST {_OVERRIDES}", f"PATCH {_OVERRIDES}/*"),
    "outlook_update_draft": (f"PATCH {_MESSAGES}/*",),
    "outlook_update_mail_rule": (f"PATCH {_RULES}/*",),
}
EXTERNAL = frozenset({"outlook_send_draft"})
DESTINATIONS = frozenset({"actions.moveToFolder", "actions.copyToFolder"})
FORBIDDEN: Mapping[str, frozenset[str]] = {
    "status": frozenset({"alwaysEnabled", "scheduled"}),
}
SCHEMA: Mapping[str, str] = {
    **dict.fromkeys(
        ("isHidden", "isInline", "isEnabled", "isReadOnly", "hasError", "sequence", "markAsRead")
        + ("stopProcessingRules", "deliveryRestricted", "isModerated", "mailboxFull")
        + ("externalMemberCount", "totalMemberCount", "maxMessageSize", "delete"),
        "number",
    ),
    **dict.fromkeys(
        ("classifyAs", "color", "status", "externalAudience", "locale", "recipientScope")
        + ("markImportance",),
        "enum",
    ),
    **dict.fromkeys(("sourceId", "targetId", "moveToFolder", "copyToFolder"), "id"),
    **dict.fromkeys(
        ("subjectContains", "bodyContains", "bodyOrSubjectContains", "senderContains")
        + ("recipientContains", "assignCategories", "customMailTip", "internalReplyMessage")
        + ("externalReplyMessage",),
        "text",
    ),
    **dict.fromkeys(
        ("uniqueBody", "conditions", "exceptions", "actions", "senderEmailAddress")
        + ("automaticRepliesSetting", "scheduledStartDateTime", "scheduledEndDateTime")
        + ("automaticReplies", "messageLanguage", "scheduledStartTime", "scheduledEndTime")
        + ("recipientSuggestions", "fromAddresses", "sentToAddresses", "forwardTo", "redirectTo")
        + ("forwardAsAttachmentTo",),
        "object",
    ),
}
