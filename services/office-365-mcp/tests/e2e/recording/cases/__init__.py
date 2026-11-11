from collections.abc import Iterator
from pathlib import Path

from tests.e2e.test_scenarios import Json, mapping, parsed

CASES = Path(__file__).parent


def case_entries(directory: Path = CASES) -> Iterator[tuple[str, Json]]:
    seen: set[str] = set()
    for file in sorted(directory.glob("*.yaml")):
        loaded = parsed(file, file.stat().st_mtime_ns)
        for case_id, entry in loaded.items():
            if case_id in seen:
                raise ValueError(f"case {case_id} is defined twice (again in {file.name})")
            seen.add(case_id)
            yield case_id, mapping(entry)
