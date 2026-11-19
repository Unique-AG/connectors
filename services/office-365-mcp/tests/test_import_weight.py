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


_MODULES_LOADED_ON_2026_11_18 = 3946
_MODULE_CEILING = 4340


def test_importing_the_app_loads_no_more_modules_than_the_ceiling() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import sys, office_365_mcp.app; print(len(sys.modules))"],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = int(result.stdout)

    assert loaded <= _MODULE_CEILING, (
        f"importing office_365_mcp.app loads {loaded} modules, above the ceiling of "
        + f"{_MODULE_CEILING}. It loaded {_MODULES_LOADED_ON_2026_11_18} on 2026-11-18. Find the "
        + "new import that pulls in the extra modules before you raise the ceiling."
    )
