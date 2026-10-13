import subprocess
import sys

_UNUSED_SDKS = ("openai", "pandas", "numpy", "unique_sdk", "tokenizers", "PIL")


def test_importing_the_app_loads_none_of_the_unique_sdks_it_never_uses() -> None:
    script = (
        "import sys, office_365_mcp.app;"
        f"print(sorted({{m.split('.')[0] for m in sys.modules}} & set({_UNUSED_SDKS!r})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", result.stdout
