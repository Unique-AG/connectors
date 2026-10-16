import subprocess
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
PACKAGE = SERVICE / "src" / "kyckr_mcp"


def test_the_generated_models_match_the_vendored_spec(tmp_path: Path) -> None:
    copy = tmp_path / "service"
    (copy / "src").mkdir(parents=True)
    (copy / "scripts").mkdir()
    (copy / "pyproject.toml").write_text((SERVICE / "pyproject.toml").read_text())
    subprocess.run(["cp", "-R", str(PACKAGE), str(copy / "src")], check=True)
    for name in ("vendor_responses.py", "operations.py"):
        (copy / "src" / "kyckr_mcp" / "models" / name).unlink()
    (copy / "scripts" / "generate_response_models.py").write_text(
        (SERVICE / "scripts" / "generate_response_models.py").read_text()
    )

    subprocess.run(
        [sys.executable, str(copy / "scripts" / "generate_response_models.py")],
        check=True,
        cwd=copy,
        env={"PYTHONPATH": str(copy / "src")},
    )

    for name in ("vendor_responses.py", "operations.py"):
        assert (copy / "src" / "kyckr_mcp" / "models" / name).read_text() == (
            PACKAGE / "models" / name
        ).read_text(), name
