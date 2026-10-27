"""A formatted stack with every exception's message cut out: frames and exception types only."""

import re

CAUSE_MARKERS = (
    "The above exception was the direct cause of the following exception",
    "During handling of the above exception, another exception occurred",
)
_TRACEBACK_HEADER = re.compile(r"^[ +|]*(?:Exception Group )?Traceback \(most recent call last\):$")
_GROUP_MARGIN = re.compile(r"^(?:[ ]*\| )?")
_GROUP_SEPARATOR = re.compile(r"^[ |]*\+[-+ .\d]*$")
_FRAME_PREFIX = '  File "'
_CODE_PREFIX = "    "
_EXCEPTION_TYPE_LINE = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")


def scrub_stacktrace(stacktrace: str) -> str:
    """Keep the frames and each exception's type; drop each message, which can quote a payload."""
    kept: list[str] = []
    state = "expect_type"
    for line in stacktrace.splitlines():
        body = _GROUP_MARGIN.sub("", line, count=1)
        if (
            _TRACEBACK_HEADER.match(line)
            or body.rstrip(":") in CAUSE_MARKERS
            or _GROUP_SEPARATOR.match(line)
        ):
            kept.append(line)
            state = "expect_type"
        elif state == "message":
            continue
        elif not body.strip():
            kept.append(line)
        elif body.startswith(_FRAME_PREFIX) or (state == "frame" and body.startswith(_CODE_PREFIX)):
            kept.append(line)
            state = "frame"
        elif type_line := _EXCEPTION_TYPE_LINE.match(body):
            kept.append(line[: len(line) - len(body)] + type_line.group(1))
            state = "message"
        else:
            state = "message"
    return "\n".join(kept)
