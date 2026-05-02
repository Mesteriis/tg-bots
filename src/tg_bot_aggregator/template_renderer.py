import re
from datetime import UTC, datetime
from typing import Any


class TemplateRenderError(ValueError):
    pass


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def render_template_text(template: str, variables: dict[str, Any] | None = None) -> str:
    values = {key: str(value) for key, value in (variables or {}).items()}
    now = datetime.now(UTC)
    values.setdefault("date", now.date().isoformat())
    values.setdefault("time", now.time().replace(microsecond=0).isoformat())
    values.setdefault("datetime", now.replace(microsecond=0).isoformat())

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise TemplateRenderError(f"missing template variable: {name}")
        return values[name]

    return PLACEHOLDER_PATTERN.sub(replace, template)
