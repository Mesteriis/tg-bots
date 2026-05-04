import pytest

from tg_bot_aggregator.domain.templates import renderer as template_renderer

TemplateRenderError = template_renderer.TemplateRenderError
render_template_text = template_renderer.render_template_text


def test_template_renderer_replaces_variables_and_builtins() -> None:
    rendered = render_template_text(
        "Deploy {{name}} at {{date}} {{time}} {{datetime}}",
        {"name": "api"},
    )

    assert rendered.startswith("Deploy api at ")
    assert "{{" not in rendered


def test_template_renderer_rejects_missing_variables() -> None:
    with pytest.raises(TemplateRenderError, match="missing template variable: name"):
        render_template_text("Deploy {{name}}", {})


def test_extract_template_variables_returns_unique_placeholder_names() -> None:
    assert template_renderer.extract_template_variables(
        "Deploy {{ name }} to {{env}} at {{date}} / {{name}}"
    ) == ["date", "env", "name"]


def test_validate_template_text_renders_when_variables_are_complete() -> None:
    result = template_renderer.validate_template_text(
        "Deploy {{name}} to {{env}} at {{date}}",
        {
            "name": "api",
            "env": "prod",
        },
    )

    assert result.ok is True
    assert result.variables == ["date", "env", "name"]
    assert result.missing_variables == []
    assert result.rendered_text.startswith("Deploy api to prod at ")
    assert result.error_message is None


def test_validate_template_text_reports_missing_user_variables() -> None:
    result = template_renderer.validate_template_text(
        "Deploy {{name}} to {{env}}", {"name": "api"}
    )

    assert result.ok is False
    assert result.variables == ["env", "name"]
    assert result.missing_variables == ["env"]
    assert result.rendered_text is None
    assert result.error_message == "missing template variables: env"


def test_template_renderer_rejects_invalid_double_brace_syntax() -> None:
    with pytest.raises(TemplateRenderError, match="invalid template placeholder syntax"):
        render_template_text("Deploy {{name", {"name": "api"})
