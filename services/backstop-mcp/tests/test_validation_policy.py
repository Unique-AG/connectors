"""Attributes models stay permissive: no required fields, junk scalars become None."""

import importlib
import pkgutil
from types import ModuleType

from pydantic import BaseModel

from backstop_mcp import features


def _api_responses_modules() -> list[ModuleType]:
    found: list[ModuleType] = []
    for module in pkgutil.walk_packages(features.__path__, prefix=f"{features.__name__}."):
        if module.ispkg:
            continue
        name = module.name.rsplit(".", 1)[-1]
        if name.startswith("api_responses"):
            found.append(importlib.import_module(module.name))
    return found


def _attributes_models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    for module in _api_responses_modules():
        for raw in vars(module).values():  # pyright: ignore[reportAny]
            if (
                isinstance(raw, type)
                and issubclass(raw, BaseModel)
                and raw is not BaseModel
                and raw.__name__.endswith("Attributes")
            ):
                models.append(raw)
    return models


def test_every_attributes_field_is_optional() -> None:
    required = [
        f"{model.__module__}.{model.__name__}.{name}"
        for model in _attributes_models()
        for name, field in model.model_fields.items()
        if field.is_required()
    ]

    assert required == []
    assert _attributes_models(), "no *Attributes models found under features/"
