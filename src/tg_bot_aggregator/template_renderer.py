import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


class TemplateRenderError(ValueError):
    pass


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
INVALID_PLACEHOLDER_MESSAGE = "invalid template placeholder syntax; use {{name}}"


@dataclass(frozen=True)
class TemplateValidationResult:
    ok: bool
    variables: list[str]
    missing_variables: list[str]
    rendered_text: str | None
    error_message: str | None


def _template_values(variables: dict[str, Any] | None = None) -> dict[str, str]:
    values = {key: str(value) for key, value in (variables or {}).items()}
    now = datetime.now(UTC)
    values.setdefault("date", now.date().isoformat())
    values.setdefault("time", now.time().replace(microsecond=0).isoformat())
    values.setdefault("datetime", now.replace(microsecond=0).isoformat())
    return values


def _assert_valid_placeholder_syntax(template: str) -> None:
    remainder = PLACEHOLDER_PATTERN.sub("", template)
    if "{{" in remainder or "}}" in remainder:
        raise TemplateRenderError(INVALID_PLACEHOLDER_MESSAGE)


def extract_template_variables(template: str) -> list[str]:
    _assert_valid_placeholder_syntax(template)
    return sorted({match.group(1) for match in PLACEHOLDER_PATTERN.finditer(template)})


def validate_template_text(
    template: str, variables: dict[str, Any] | None = None
) -> TemplateValidationResult:
    try:
        variable_names = extract_template_variables(template)
    except TemplateRenderError as exc:
        return TemplateValidationResult(
            ok=False,
            variables=[],
            missing_variables=[],
            rendered_text=None,
            error_message=str(exc),
        )

    provided_values = _template_values(variables)
    missing_variables = [name for name in variable_names if name not in provided_values]
    if missing_variables:
        return TemplateValidationResult(
            ok=False,
            variables=variable_names,
            missing_variables=missing_variables,
            rendered_text=None,
            error_message=f"missing template variables: {', '.join(missing_variables)}",
        )

    try:
        rendered_text = render_template_text(template, variables)
    except TemplateRenderError as exc:
        return TemplateValidationResult(
            ok=False,
            variables=variable_names,
            missing_variables=[],
            rendered_text=None,
            error_message=str(exc),
        )

    return TemplateValidationResult(
        ok=True,
        variables=variable_names,
        missing_variables=[],
        rendered_text=rendered_text,
        error_message=None,
    )


def render_template_text(template: str, variables: dict[str, Any] | None = None) -> str:
    _assert_valid_placeholder_syntax(template)
    values = _template_values(variables)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise TemplateRenderError(f"missing template variable: {name}")
        return values[name]

    return PLACEHOLDER_PATTERN.sub(replace, template)
