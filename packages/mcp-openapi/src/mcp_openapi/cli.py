import argparse
import sys
import tomllib
from importlib import import_module
from pathlib import Path
from typing import ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from mcp_openapi.codegen import generate_operations, generate_response_models
from mcp_openapi.vendoring import refresh_spec, stale_outputs


def _kebab(name: str) -> str:
    return name.replace("_", "-")


class CodegenConfig(BaseModel):
    """The `[tool.mcp-openapi]` table. Paths are relative to the pyproject.toml.

    `operation_ids`, `response_operation_ids` and `fields` are either written out or a
    `"module:NAME"` reference to a value in code. `spec_source` is where the vendored `spec` is
    fetched again from by `--refresh-spec`: a URL, or a path.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", alias_generator=_kebab, populate_by_name=True
    )

    spec: Path | None = None
    spec_url: str | None = None
    spec_source: str | None = None
    operation_ids: list[str]
    response_operation_ids: list[str] | None = None
    fields: dict[str, tuple[str, ...]] = {}
    allow_extra_fields: bool = False
    snake_case_fields: bool = True
    operation_module: str
    models_module: str
    models_output: Path
    operations_output: Path

    @field_validator("operation_ids", "response_operation_ids", "fields", mode="before")
    @classmethod
    def _import_reference(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        module, separator, name = value.partition(":")
        if not separator:
            raise ValueError(f'expected "module:NAME", got {value!r}')
        return cast(object, getattr(import_module(module), name))

    @model_validator(mode="after")
    def _source_of_a_vendored_spec(self) -> Self:
        if self.spec_source is not None and self.spec is None:
            raise ValueError("spec-source refreshes a vendored spec, so it needs spec")
        return self


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate response models and Operation constants from [tool.mcp-openapi]."
    )
    parser.add_argument(
        "project", nargs="?", type=Path, default=Path(), help="folder of the pyproject.toml"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail if the generated files are not what the spec and the table generate",
    )
    mode.add_argument(
        "--refresh-spec",
        action="store_true",
        help="fetch the spec again from spec-source, then regenerate",
    )
    arguments = parser.parse_args(argv)
    root = cast(Path, arguments.project)
    with (root / "pyproject.toml").open("rb") as file:
        table = cast(dict[str, object], tomllib.load(file)["tool"]["mcp-openapi"])
    config = CodegenConfig.model_validate(table)

    if cast(bool, arguments.refresh_spec):
        if config.spec is None or config.spec_source is None:
            parser.error("--refresh-spec needs spec and spec-source in [tool.mcp-openapi]")
        source = config.spec_source
        is_url = source.startswith(("http://", "https://"))
        changes = refresh_spec(spec=root / config.spec, source=source if is_url else root / source)
        print(
            "\n".join(["operationIds changed:", *changes]) if changes else "No operationId changed."
        )
    if cast(bool, arguments.check):
        outputs = [root / config.models_output, root / config.operations_output]
        stale = stale_outputs(outputs, lambda: _generate(root, config))
        if stale:
            print("\n\n".join([*stale, "Run `uv run mcp-openapi-codegen` and commit the result."]))
            sys.exit(1)
        return
    _generate(root, config)


def _generate(root: Path, config: CodegenConfig) -> None:
    spec_path = root / config.spec if config.spec else None
    generate_response_models(
        spec_path=spec_path,
        spec_url=config.spec_url,
        operation_ids=config.response_operation_ids or config.operation_ids,
        fields=config.fields,
        allow_extra_fields=config.allow_extra_fields,
        snake_case_fields=config.snake_case_fields,
        output=root / config.models_output,
    )
    generate_operations(
        spec_path=spec_path,
        spec_url=config.spec_url,
        operation_ids=config.operation_ids,
        operation_module=config.operation_module,
        models_module=config.models_module,
        output=root / config.operations_output,
    )


if __name__ == "__main__":
    main()
