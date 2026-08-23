"""Email delivery and its fallback.

The fallback exists for one failure that matters: Resend refusing an address
because the sending domain is not verified. Discovering that during a demo,
with no invite arriving and no visible reason, is the situation worth
engineering around.
"""

from types import SimpleNamespace

import pytest

from intake import mailer
from intake.mailer import EmailNotSent, Provider


@pytest.fixture
def settings(monkeypatch):
    def apply(provider="resend", **over):
        fields = {
            "email_provider": provider,
            "resend_api_key": "re_real_key",
            "from_email": "onboarding@resend.dev",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "someone@gmail.com",
            "smtp_password": "app-password",
            "smtp_from": None,
        }
        fields.update(over)
        cfg = SimpleNamespace(**fields)
        monkeypatch.setattr(mailer, "get_settings", lambda: cfg)
        return cfg

    return apply


def stub(monkeypatch, *, resend=None, smtp=None):
    """Replace the senders. Pass an Exception to make one fail."""
    calls = []

    def make(name, outcome):
        def fn(to, subject, body):
            calls.append(name)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return fn

    monkeypatch.setattr(
        mailer,
        "_SENDERS",
        {
            Provider.RESEND: make("resend", resend),
            Provider.SMTP: make("smtp", smtp),
        },
    )
    return calls


def test_primary_is_used_when_it_works(monkeypatch, settings):
    settings(provider="resend")
    calls = stub(monkeypatch, resend="id-1", smtp="id-2")
    assert mailer.send("a@b.com", "s", "b") == "id-1"
    assert calls == ["resend"], "the fallback must not fire when nothing failed"


def test_falls_back_when_the_primary_refuses(monkeypatch, settings):
    """The real case: Resend rejecting an address for want of a verified
    domain. The candidate should still get their invite."""
    settings(provider="resend")
    calls = stub(
        monkeypatch,
        resend=RuntimeError("403 domain not verified"),
        smtp="smtp",
    )
    assert mailer.send("judge@example.com", "s", "b") == "smtp"
    assert calls == ["resend", "smtp"]


def test_smtp_can_be_primary(monkeypatch, settings):
    settings(provider="smtp")
    calls = stub(monkeypatch, resend="id-1", smtp="smtp")
    assert mailer.send("a@b.com", "s", "b") == "smtp"
    assert calls == ["smtp"]


def test_falls_back_the_other_way_too(monkeypatch, settings):
    settings(provider="smtp")
    calls = stub(monkeypatch, resend="id-1", smtp=RuntimeError("auth failed"))
    assert mailer.send("a@b.com", "s", "b") == "id-1"
    assert calls == ["smtp", "resend"]


def test_raises_only_when_everything_fails(monkeypatch, settings):
    settings(provider="resend")
    stub(
        monkeypatch,
        resend=RuntimeError("403 domain not verified"),
        smtp=RuntimeError("auth failed"),
    )
    with pytest.raises(EmailNotSent) as exc:
        mailer.send("a@b.com", "s", "b")
    # Both reasons survive: a silent email failure is worse than a loud one,
    # and "it did not send" without saying why is unactionable.
    assert "domain not verified" in str(exc.value)
    assert "auth failed" in str(exc.value)


def test_unconfigured_resend_is_skipped_not_attempted(monkeypatch, settings):
    """A placeholder key would otherwise produce a confusing auth error rather
    than falling through to the provider that actually works."""
    settings(provider="resend", resend_api_key="PLACEHOLDER_resend_key")
    monkeypatch.setattr(mailer, "_send_smtp", lambda to, s, b: "smtp")
    monkeypatch.setattr(
        mailer,
        "_SENDERS",
        {Provider.RESEND: mailer._send_resend, Provider.SMTP: lambda *_: "smtp"},
    )
    assert mailer.send("a@b.com", "s", "b") == "smtp"


def test_unconfigured_smtp_is_skipped(monkeypatch, settings):
    settings(provider="smtp", smtp_host=None)
    monkeypatch.setattr(
        mailer,
        "_SENDERS",
        {Provider.RESEND: lambda *_: "resend-id", Provider.SMTP: mailer._send_smtp},
    )
    assert mailer.send("a@b.com", "s", "b") == "resend-id"
