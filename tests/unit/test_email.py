"""Email message construction: rendering and the provider payload.

No network here. The generic-provider POST and the console fallback are
covered in tests/functional/test_email.py.
"""

from app.email import EmailMessage, build_payload, render_email


def test_render_email_has_html_and_text_parts() -> None:
    msg = render_email(
        "verification",
        subject="Confirm your email",
        to="ada@example.com",
        verify_url="https://app.test/auth/verify?token=abc",
        app_name="Pave",
    )

    assert isinstance(msg, EmailMessage)
    assert msg.to == "ada@example.com"
    assert msg.subject == "Confirm your email"
    assert msg.html.strip() != ""
    assert msg.text.strip() != ""
    # The link must survive into both parts.
    assert "https://app.test/auth/verify?token=abc" in msg.html
    assert "https://app.test/auth/verify?token=abc" in msg.text
    assert "<" in msg.html and "<" not in msg.text  # html vs plain text


def test_render_password_reset_template() -> None:
    msg = render_email(
        "password_reset",
        subject="Reset your password",
        to="grace@example.com",
        reset_url="https://app.test/auth/reset?token=xyz",
        app_name="Pave",
    )

    assert "https://app.test/auth/reset?token=xyz" in msg.html
    assert "https://app.test/auth/reset?token=xyz" in msg.text


def test_build_payload_shape() -> None:
    msg = EmailMessage(
        to="ada@example.com",
        subject="Hi",
        html="<p>hi</p>",
        text="hi",
    )
    payload = build_payload(msg)

    assert set(payload) == {"from", "to", "subject", "html", "text"}
    assert payload["to"] == "ada@example.com"
    assert payload["subject"] == "Hi"
    assert payload["html"] == "<p>hi</p>"
    assert payload["text"] == "hi"
    assert payload["from"]  # taken from settings.email_from
