import pytest

from tg_bot_aggregator.template_renderer import TemplateRenderError, render_template_text


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
