from orchestrator.context import (
    TEMPLATE_CONTEXT_FIELDS,
    TEMPLATE_CONVENTION,
    TEMPLATE_DESCRIPTION,
    TEMPLATE_PREFERRED_MODELS_NOTES,
    TEMPLATE_STACK,
    template_fields,
)


def test_template_fields_reports_each_generated_placeholder():
    raw = {
        "stack": TEMPLATE_STACK,
        "description": TEMPLATE_DESCRIPTION,
        "conventions": [TEMPLATE_CONVENTION],
        "preferred_models": {"notes": TEMPLATE_PREFERRED_MODELS_NOTES},
    }

    assert template_fields(raw) == list(TEMPLATE_CONTEXT_FIELDS)


def test_template_fields_ignores_completed_context():
    raw = {
        "stack": "Python",
        "description": "Synthetic project",
        "conventions": ["Use typed interfaces"],
        "preferred_models": {"notes": "Prefer the small model for formatting."},
    }

    assert template_fields(raw) == []


def test_template_fields_handles_missing_context_values():
    assert template_fields({}) == []
