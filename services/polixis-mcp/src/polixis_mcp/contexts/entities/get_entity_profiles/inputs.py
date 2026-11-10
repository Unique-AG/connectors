from typing import Literal

ProfileSection = Literal[
    "names",
    "name_records",
    "identifiers",
    "countries",
    "dates",
    "gender",
    "legal_forms",
    "economic_activities",
    "addresses",
    "flags",
    "alerts",
    "sanction_statuses",
    "sanctions",
    "positions",
]

# What tells entities apart and screens them, without the long sections.
KEY_SECTIONS: list[ProfileSection] = [
    "name_records",
    "identifiers",
    "countries",
    "dates",
    "flags",
    "alerts",
    "sanction_statuses",
]
