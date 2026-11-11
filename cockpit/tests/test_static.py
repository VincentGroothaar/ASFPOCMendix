"""The app serves docs/ui/tokens.css as a static file; the copy must never drift from it."""

from pathlib import Path

from django.conf import settings


def test_served_tokens_are_identical_to_the_ui_spec_tokens() -> None:
    source = Path(settings.BASE_DIR, "docs", "ui", "tokens.css").read_text()
    served = Path(settings.BASE_DIR, "static", "cockpit", "tokens.css").read_text()

    assert served == source, "copy docs/ui/tokens.css to static/cockpit/tokens.css"
