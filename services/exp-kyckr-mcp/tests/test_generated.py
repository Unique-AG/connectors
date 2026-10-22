import subprocess
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
PACKAGE = SERVICE / "src" / "kyckr_mcp"
GENERATED = ("vendor_responses.py", "operations.py")


def test_the_generated_models_match_the_vendored_spec(tmp_path: Path) -> None:
    copy = tmp_path / "service"
    (copy / "src").mkdir(parents=True)
    (copy / "pyproject.toml").write_text((SERVICE / "pyproject.toml").read_text())
    subprocess.run(["cp", "-R", str(PACKAGE), str(copy / "src")], check=True)
    for name in GENERATED:
        (copy / "src" / "kyckr_mcp" / "models" / name).unlink()

    subprocess.run([sys.executable, "-m", "mcp_openapi.cli", str(copy)], check=True)

    for name in GENERATED:
        assert (copy / "src" / "kyckr_mcp" / "models" / name).read_text() == (
            PACKAGE / "models" / name
        ).read_text(), name
