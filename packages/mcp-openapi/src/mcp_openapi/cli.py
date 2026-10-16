import argparse
import tomllib
from importlib import import_module
from pathlib import Path
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, field_validator

from mcp_openapi.codegen import generate_operations, generate_response_models


def _kebab(name: str) -> str:
    return name.replace("_", "-")


class CodegenConfig(BaseModel):
    """The `[tool.mcp-openapi]` table. Paths are relative to the pyproject.toml.

    `operation_ids`, `response_operation_ids` and `fields` are either written out or a
    `"module:NAME"` reference to a value in code.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", alias_generator=_kebab, populate_by_name=True
    )

    spec: Path | None = None
    spec_url: str | None = None
    operation_ids: list[str]
    response_operation_ids: list[str] | None = None
    fields: dict[str, tuple[str, ...]] = {}
    allow_extra_fields: bool = False
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate response models and Operation constants from [tool.mcp-openapi]."
    )
    parser.add_argument(
        "project", nargs="?", type=Path, default=Path(), help="folder of the pyproject.toml"
    )
    root = cast(Path, parser.parse_args(argv).project)
    with (root / "pyproject.toml").open("rb") as file:
        table = cast(dict[str, object], tomllib.load(file)["tool"]["mcp-openapi"])
    config = CodegenConfig.model_validate(table)

    spec_path = root / config.spec if config.spec else None
    generate_response_models(
        spec_path=spec_path,
        spec_url=config.spec_url,
        operation_ids=config.response_operation_ids or config.operation_ids,
        fields=config.fields,
        allow_extra_fields=config.allow_extra_fields,
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
