"""Tests for the payment gate in ClubSparkBooker._handle_payment.

These exercise the payment decision logic with fake page/frame objects, so no
real browser is needed.
"""
import pytest

from tennis_booking.clubspark import ClubSparkBooker, PaymentError
from tennis_booking.config import Settings


def _settings(**over) -> Settings:
    base = dict(clubspark_username="u", clubspark_password="p")
    base.update(over)
    return Settings(_env_file=None, **base)


class FakeLocator:
    def __init__(self, count):
        self._count = count
        self.filled = None

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    def fill(self, value, timeout=None):
        self.filled = value


class FakePage:
    """A fake page/frame. `has_payment` controls whether a card form is 'present'."""

    def __init__(self, has_payment):
        self.has_payment = has_payment
        self.frames = []  # no sub-frames; itself is the only context
        self.clicked = []

    def locator(self, selector):
        # The pay-page marker + any card field 'exists' only if has_payment.
        return FakeLocator(1 if self.has_payment else 0)

    def click(self, selector, timeout=None):
        self.clicked.append(selector)

    def wait_for_load_state(self, *a, **k):
        pass

    def screenshot(self, *a, **k):
        pass


def _booker(settings):
    b = ClubSparkBooker(settings)
    # Neutralise screenshot writing.
    b._screenshot = lambda page, label: None
    return b


def test_no_payment_step_is_noop():
    page = FakePage(has_payment=False)
    # frames must include page for _payment_target iteration
    page.frames = [page]
    _booker(_settings())._handle_payment(page)  # should not raise
    assert page.clicked == []


def test_payment_without_card_raises():
    page = FakePage(has_payment=True)
    page.frames = [page]
    with pytest.raises(PaymentError, match="no card details"):
        _booker(_settings())._handle_payment(page)


def test_payment_dryrun_fills_but_does_not_pay():
    page = FakePage(has_payment=True)
    page.frames = [page]
    s = _settings(
        card_number="4111111111111111", card_expiry="12/30", card_cvv="123",
        confirm_payment=False,
    )
    with pytest.raises(PaymentError, match="CONFIRM_PAYMENT"):
        _booker(s)._handle_payment(page)
    # Never clicked the pay button in dry run.
    assert page.clicked == []


def test_payment_confirmed_clicks_pay():
    page = FakePage(has_payment=True)
    page.frames = [page]
    s = _settings(
        card_number="4111111111111111", card_expiry="12/30", card_cvv="123",
        confirm_payment=True,
    )
    _booker(s)._handle_payment(page)
    # Pay button was clicked exactly once.
    assert len(page.clicked) == 1
