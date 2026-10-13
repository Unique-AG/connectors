from typing import cast
from urllib.request import urlopen

import yaml


def load_spec(url: str) -> dict[str, object]:
    with urlopen(url, timeout=30) as response:
        spec = yaml.safe_load(response.read())
    if not isinstance(spec, dict):
        raise ValueError("Kyckr OpenAPI URL did not return an object")
    return cast(dict[str, object], spec)
