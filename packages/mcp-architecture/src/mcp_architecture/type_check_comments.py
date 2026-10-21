"""The `# pyright:` comments that change a file's type check, which basedpyright honours whatever
the shared config says."""

import re
import tokenize
from pathlib import Path

# An ignore that names its rules only ignores them on its line, so it is the one form left.
_CHANGES_THE_TYPE_CHECK = re.compile(r"#\s*pyright:(?!\s*ignore\[)")
_FOLDERS = ("src", "tests")


def files_changing_their_type_check(root: Path) -> list[str]:
    """Each `# pyright:` comment in `root`'s `src` and `tests` other than `ignore[rule]`, as
    `path:line`."""
    return [
        f"{path.relative_to(root)}:{comment.start[0]}"
        for folder in _FOLDERS
        for path in sorted((root / folder).rglob("*.py"))
        for comment in _comments(path)
        if _CHANGES_THE_TYPE_CHECK.match(comment.string)
    ]


def _comments(path: Path) -> list[tokenize.TokenInfo]:
    with path.open("rb") as file:
        return [
            token for token in tokenize.tokenize(file.readline) if token.type == tokenize.COMMENT
        ]
