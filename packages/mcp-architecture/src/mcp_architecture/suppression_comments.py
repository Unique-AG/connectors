"""The comments that turn a check off for more than their own line: a `# pyright:` comment that
changes a file's type check, which basedpyright honours whatever the shared config says, and a
`# ruff: noqa` or `# ruff: disable` that turns a rule off for the rest of the file, as a
`per-file-ignores` entry would."""

import re
import tokenize
from pathlib import Path

# An ignore that names its rules only ignores them on its line, so it is the one form left.
_CHANGES_THE_TYPE_CHECK = re.compile(r"#\s*pyright:(?!\s*ignore\[)")
# ruff reads flake8's spelling too. A `disable` without its `enable` lasts to the end of the file.
_TURNS_A_RULE_OFF = re.compile(r"#\s*(?:ruff|flake8)\s*:\s*(?:noqa|disable)", re.IGNORECASE)
_FOLDERS = ("src", "tests")


def files_changing_their_type_check(root: Path) -> list[str]:
    """Each `# pyright:` comment in `root`'s `src` and `tests` other than `ignore[rule]`, as
    `path:line`."""
    return _comments_matching(root, _CHANGES_THE_TYPE_CHECK)


def files_turning_rules_off(root: Path, package: str) -> list[str]:
    """Each `# ruff: noqa` or `# ruff: disable` comment in `root`'s `src` and `tests`, as
    `path:line`, outside `src/<package>/upstream/generated/`, where the codegen writes one."""
    generated = root / "src" / package / "upstream" / "generated"
    return _comments_matching(root, _TURNS_A_RULE_OFF, skipped=generated)


def _comments_matching(
    root: Path, pattern: re.Pattern[str], *, skipped: Path | None = None
) -> list[str]:
    return [
        f"{path.relative_to(root)}:{comment.start[0]}"
        for folder in _FOLDERS
        for path in sorted((root / folder).rglob("*.py"))
        if skipped is None or not path.is_relative_to(skipped)
        for comment in _comments(path)
        if pattern.search(comment.string)
    ]


def _comments(path: Path) -> list[tokenize.TokenInfo]:
    with path.open("rb") as file:
        return [
            token for token in tokenize.tokenize(file.readline) if token.type == tokenize.COMMENT
        ]
