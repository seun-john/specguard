"""Safe YAML loading for specifications."""

from __future__ import annotations

from typing import Any

import yaml


class YamlLoadError(ValueError):
    """The YAML is malformed or uses a feature SpecGuard refuses to load."""


def load_yaml_text(text: str) -> Any:
    """Parse YAML with the safe loader and reject anchors/aliases.

    `safe_load` cannot construct arbitrary Python objects. Aliases are refused as well
    because nested aliases ("billion laughs") can expand a tiny file into an enormous
    structure when it is later walked.
    """
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent):
                raise YamlLoadError("YAML anchors and aliases are not supported in specifications")
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or "malformed YAML"
        raise YamlLoadError(f"{problem}{where}") from exc
