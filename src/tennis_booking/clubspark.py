"""Playwright-driven ClubSpark booking flow.

ClubSpark renders the booking grid **inside an iframe** and requires login to
book, so we drive a real Chromium/Chrome browser. Grid selectors are resolved
against that iframe (see :meth:`ClubSparkBooker._grid_frame`), not the top-level
page. The selector constants below were verified against the live DOM (2026-07);
if the layout changes, re-check them with
``playwright codegen https://clubspark.lta.org.uk/ClaphamCommon/Booking/BookByDate``.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from pathlib import Path
from time import sleep as _sleep

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Frame,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .config import LoginMethod, Settings
from .logging_config import get_logger
from .models import BookingRequest, BookingResult, Slot

log = get_logger(__name__)


class PaymentError(RuntimeError):
    """Raised when a paid checkout is reached but payment cannot be completed."""

# --- Selectors (verified against the live ClubSpark DOM, 2026-07). -----------
# NB: the booking grid renders inside an <iframe>; grid selectors are resolved
# against that frame (see _grid_frame), not the top-level page.
# Header "Sign in" link on the venue page -> redirects to auth.clubspark.uk.
SEL_LOGIN_LINK = "a:has-text('Sign in')"
SEL_LOGGED_IN = "text=Sign out"
# On auth.clubspark.uk there are two login paths:
#  - LTA (default): the primary visible "Login" button submits a WS-Fed Home
#    Realm Discovery form and redirects to the LTA identity provider
#    (mylta.my.site.com, a Salesforce Experience site). Use this for accounts
#    migrated to an LTA username/password.
#  - ClubSpark: the email/password form hidden inside the #alt-login-options
#    modal, revealed by the "Login with another method" link.
SEL_LTA_LOGIN_BUTTON = "button.cs-btn.primary.med.fw"
SEL_ALT_LOGIN_LINK = ".js-alt-options-modal"
SEL_CLUBSPARK_EMAIL = "#EmailAddress"
SEL_CLUBSPARK_PASSWORD = "#Password"
SEL_CLUBSPARK_SUBMIT = "#signin-btn"
# LTA identity-provider (Salesforce) login page. Fields have dynamic ids, so we
# select by placeholder / type / accessible name.
SEL_LTA_USERNAME = "input[placeholder='Username']"
SEL_LTA_PASSWORD = "input[type='password']"
SEL_LTA_SUBMIT = "button:has-text('Log in')"
# The booking grid container. Present once the grid has rendered, whether or not
# any slots are free -- use this to detect "grid ready" rather than free slots.
SEL_GRID_READY = ".booking-sheet"
# A resource (court) column on the BookByDate grid.
SEL_RESOURCE = ".resource"
# A bookable (free) slot cell. Free cells carry the "not-booked" class.
SEL_FREE_SLOT = "a.book-interval.not-booked"
# Within a free slot: the "Book at HH:MM - HH:MM" label and the price.
SEL_SLOT_LABEL = ".available-booking-slot"
SEL_SLOT_COST = ".cost"
# The confirm/continue button on the booking dialog.
SEL_CONFIRM_BUTTON = "button:has-text('Confirm'), button:has-text('Continue')"
# Confirmation reference text after a successful booking.
SEL_CONFIRMATION = ".booking-confirmation, .confirmation-reference"
# --- Payment checkout selectors -------------------------------------------
# NB: These are BEST-GUESS defaults and MUST be verified against the live paid
# checkout (see the Phase-0 investigation in the deploy runbook). Paid ClubSpark
# checkouts are commonly a third-party (Stripe/Opayo) form, often inside an
# iframe -- if so these top-level selectors will not match and the flow will
# stop safely rather than mis-pay. Card fields are matched broadly by
# name/placeholder/autocomplete.
SEL_PAY_PAGE_MARKER = (
    "input[autocomplete='cc-number'], input[name*='card' i], "
    "iframe[name*='card' i], iframe[title*='card' i], iframe[src*='stripe' i]"
)
SEL_CARD_NUMBER = "input[autocomplete='cc-number'], input[name*='number' i], input[name*='cardnumber' i]"
SEL_CARD_EXPIRY = "input[autocomplete='cc-exp'], input[name*='exp' i], input[placeholder*='MM' i]"
SEL_CARD_CVV = "input[autocomplete='cc-csc'], input[name*='cvc' i], input[name*='cvv' i], input[name*='security' i]"
SEL_CARD_NAME = "input[autocomplete='cc-name'], input[name*='cardholder' i], input[name*='nameoncard' i]"
SEL_CARD_POSTCODE = "input[autocomplete='postal-code'], input[name*='postcode' i], input[name*='zip' i]"
SEL_PAY_BUTTON = "button:has-text('Pay'), button:has-text('Pay now'), button:has-text('Confirm payment')"
# -----------------------------------------------------------------------------

# Where error/dry-run screenshots are written. Overridable via SCREENSHOT_DIR so
# cloud runs can point it at a writable path (e.g. /tmp/screenshots).
SCREENSHOT_DIR = Path(os.environ.get("SCREENSHOT_DIR", "screenshots"))


class ClubSparkBooker:
    """Logs into ClubSpark and books a court for a :class:`BookingRequest`."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- public API -----------------------------------------------------------

    def book(self, request: BookingRequest) -> BookingResult:
        """Attempt the booking, always returning a :class:`BookingResult`."""
        with sync_playwright() as pw:
            browser = self._launch_browser(pw)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(self.settings.slot_timeout_seconds * 1000)
            try:
                self._ensure_logged_in(page)
                self._save_storage_state(context)
                slot = self._find_slot(page, request)
                if slot is None:
                    return BookingResult(
                        success=False,
                        request=request,
                        error="No matching available slot found for requested/fallback times.",
                    )
                confirmation = self._book_slot(page, slot)
                return BookingResult(
                    success=True,
                    request=request,
                    slot=slot,
                    confirmation=confirmation,
                )
            except Exception as exc:  # noqa: BLE001 - report any failure cleanly
                shot = self._screenshot(page, "error")
                log.exception("Booking failed")
                self._pause_on_error()
                return BookingResult(
                    success=False,
                    request=request,
                    error=str(exc),
                    screenshot_path=shot,
                )
            finally:
                context.close()
                browser.close()

    def list_available_slots(self, day: date_cls) -> list[Slot]:
        """Return every available (bookable) slot on ``day``.

        Logs in if needed, navigates to that date's booking grid, and returns the
        free slots sorted by start time then court. ``end_time`` is left unset
        because the duration is chosen at booking time, not listing time.
        """
        with sync_playwright() as pw:
            browser = self._launch_browser(pw)
            context = self._new_context(browser)
            page = context.new_page()
            page.set_default_timeout(self.settings.slot_timeout_seconds * 1000)
            try:
                self._ensure_logged_in(page)
                self._save_storage_state(context)
                self._goto_date(page, day)
                slots = self._collect_free_slots(page)
                log.info("Found %d available slot(s) on %s", len(slots), day)
                return slots
            except Exception:
                self._screenshot(page, "error")
                log.exception("Listing available slots failed")
                self._pause_on_error()
                raise
            finally:
                context.close()
                browser.close()

    # -- browser launch -------------------------------------------------------

    def _launch_browser(self, pw) -> Browser:
        """Launch Chrome (visible by default) so the flow can be watched.

        Falls back to Playwright's bundled Chromium if Google Chrome is not
        installed on the machine.
        """
        launch_kwargs = {
            "headless": self.settings.headless,
            "slow_mo": self.settings.slow_mo_ms,
        }
        # In a sandboxed container (Cloud Run) headless Chromium needs these flags
        # or it crashes on startup / runs out of /dev/shm.
        if self.settings.headless:
            launch_kwargs["args"] = ["--no-sandbox", "--disable-dev-shm-usage"]
        if self.settings.use_chrome:
            try:
                log.info(
                    "Launching Google Chrome (headless=%s, slow_mo=%dms)",
                    self.settings.headless, self.settings.slow_mo_ms,
                )
                return pw.chromium.launch(channel="chrome", **launch_kwargs)
            except Exception as exc:  # noqa: BLE001 - Chrome may not be installed
                log.warning("Could not launch Google Chrome (%s); using bundled Chromium.", exc)
        log.info(
            "Launching Chromium (headless=%s, slow_mo=%dms)",
            self.settings.headless, self.settings.slow_mo_ms,
        )
        return pw.chromium.launch(**launch_kwargs)

    # -- context / session ----------------------------------------------------

    def _new_context(self, browser: Browser) -> BrowserContext:
        """Create a context, reusing a saved login session if one exists."""
        state = self.settings.storage_state_path
        if state and os.path.exists(state):
            log.info("Reusing saved session from %s", state)
            return browser.new_context(storage_state=state)
        return browser.new_context()

    def _save_storage_state(self, context: BrowserContext) -> None:
        if self.settings.storage_state_path:
            context.storage_state(path=self.settings.storage_state_path)

    # -- login ----------------------------------------------------------------

    def _ensure_logged_in(self, page: Page) -> None:
        """Navigate to the booking page and log in if we are not already.

        The venue page's "Sign in" link redirects to ``auth.clubspark.uk``, which
        offers two paths (see :data:`SEL_LTA_LOGIN_BUTTON`). Which one to use is
        controlled by ``LOGIN_METHOD`` (default: ``lta``).
        """
        page.goto(self.settings.booking_url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        if self._is_logged_in(page):
            log.info("Already logged in (saved session valid).")
            return

        log.info("Logging in as %s via %s",
                 self.settings.clubspark_username, self.settings.login_method.value)
        page.click(SEL_LOGIN_LINK)
        page.wait_for_load_state("networkidle")

        if self.settings.login_method is LoginMethod.LTA:
            self._login_via_lta(page)
        else:
            self._login_via_clubspark(page)

        if not self._is_logged_in(page):
            raise RuntimeError(
                "Login did not succeed; check CLUBSPARK_USERNAME / CLUBSPARK_PASSWORD "
                f"and LOGIN_METHOD ({self.settings.login_method.value})."
            )
        log.info("Login successful.")

    def _login_via_lta(self, page: Page) -> None:
        """LTA path: click the primary Login button, then fill the LTA IdP form.

        The primary "Login" button submits a WS-Fed Home Realm Discovery form and
        redirects to the LTA identity provider (Salesforce), where the fields have
        dynamic ids, so we match by placeholder / type / name.
        """
        try:
            with page.expect_navigation(wait_until="domcontentloaded",
                                        timeout=self.settings.slot_timeout_seconds * 1000):
                page.click(SEL_LTA_LOGIN_BUTTON)
        except PlaywrightTimeoutError:
            log.warning("LTA redirect did not fire a navigation; continuing.")
        page.wait_for_selector(SEL_LTA_USERNAME, state="visible",
                               timeout=self.settings.slot_timeout_seconds * 1000)
        page.fill(SEL_LTA_USERNAME, self.settings.clubspark_username)
        page.fill(SEL_LTA_PASSWORD, self.settings.clubspark_password)
        page.click(SEL_LTA_SUBMIT)
        # The LTA IdP bounces through several WS-Fed redirects back to ClubSpark;
        # networkidle can fire on an intermediate hop, so wait for the returned
        # ClubSpark page to actually show the logged-in state.
        self._wait_until_logged_in(page)

    def _wait_until_logged_in(self, page: Page) -> None:
        """Poll for the logged-in indicator after a (possibly multi-hop) redirect."""
        timeout_ms = self.settings.slot_timeout_seconds * 1000
        try:
            page.wait_for_url("**/clubspark.lta.org.uk/**", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass  # fall through to the indicator check below
        waited, step = 0, 500
        while waited < timeout_ms:
            page.wait_for_load_state("networkidle")
            if self._is_logged_in(page):
                return
            page.wait_for_timeout(step)
            waited += step

    def _login_via_clubspark(self, page: Page) -> None:
        """ClubSpark path: reveal the email/password modal and submit it."""
        if not self._email_field_visible(page):
            try:
                page.click(SEL_ALT_LOGIN_LINK, timeout=8000)
            except PlaywrightTimeoutError:
                log.warning("'Login with another method' link not found; "
                            "trying the email form directly.")
            page.wait_for_selector(SEL_CLUBSPARK_EMAIL, state="visible",
                                   timeout=self.settings.slot_timeout_seconds * 1000)

        page.fill(SEL_CLUBSPARK_EMAIL, self.settings.clubspark_username)
        page.fill(SEL_CLUBSPARK_PASSWORD, self.settings.clubspark_password)
        page.click(SEL_CLUBSPARK_SUBMIT)
        page.wait_for_load_state("networkidle")

    def _email_field_visible(self, page: Page) -> bool:
        try:
            loc = page.locator(SEL_CLUBSPARK_EMAIL)
            return loc.count() > 0 and loc.first.is_visible()
        except Exception:  # noqa: BLE001
            return False

    def _is_logged_in(self, page: Page) -> bool:
        """Heuristic: a "Sign out" control is present once authenticated."""
        try:
            return page.locator(SEL_LOGGED_IN).count() > 0
        except Exception:  # noqa: BLE001
            return False

    # -- iframe handling ------------------------------------------------------

    def _grid_frame(self, page: Page) -> Frame:
        """Return the <iframe> that hosts the booking grid.

        ClubSpark renders BookByDate inside an iframe, so every grid selector must
        be resolved against this frame rather than the top-level page. We poll the
        frames until one exposes the booking sheet container. This container is
        present even on fully-booked days (when there are zero free slots), so a
        no-availability day is detected here as "grid ready, no free slots" rather
        than timing out.
        """
        timeout_ms = self.settings.slot_timeout_seconds * 1000
        waited = 0
        step = 500
        while waited < timeout_ms:
            for frame in page.frames:
                try:
                    if frame.locator(SEL_GRID_READY).count() > 0:
                        return frame
                except Exception:  # noqa: BLE001 - frame may be mid-navigation
                    continue
            page.wait_for_timeout(step)
            waited += step
        raise RuntimeError(
            "Booking grid iframe did not appear; the page may not have loaded or "
            "the layout has changed."
        )

    # -- slot discovery -------------------------------------------------------

    def _find_slot(self, page: Page, request: BookingRequest) -> Slot | None:
        """Navigate to the requested date and return the first matching free slot."""
        self._goto_date(page, request.date)
        available = self._collect_free_slots(page)

        for start in request.candidate_start_times:
            for slot in available:
                if slot.start_time != start:
                    continue
                if request.court and request.court.lower() not in slot.court.lower():
                    continue
                # Fill in the end time now that a duration is known.
                slot.end_time = self._add_minutes(start, request.duration_minutes)
                log.info("Found free slot: %s at %s", slot.court, f"{start:%H:%M}")
                return slot
            log.info("No free slot at %s%s", f"{start:%H:%M}",
                     f" on {request.court}" if request.court else "")
        return None

    def _goto_date(self, page: Page, day: date_cls) -> None:
        """ClubSpark BookByDate reads the date from the URL hash fragment.

        Waits for the grid container to render (not for free slots): a fully-booked
        day renders the grid with zero free slots, so waiting on free slots would
        just time out. Once the grid is ready we let the caller read whatever slots
        (if any) are present.
        """
        url = f"{self.settings.booking_url}#?date={day.isoformat()}"
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        # Resolving the grid frame already waits for the booking-sheet container.
        self._grid_frame(page)

    def _collect_free_slots(self, page: Page) -> list[Slot]:
        """Parse every bookable cell in the grid iframe into :class:`Slot` objects.

        Each free cell is ``<a class="book-interval not-booked"
        data-test-id="booking-{courtId}|{date}|{minsSinceMidnight}">`` with a
        ``.available-booking-slot`` label ("Book at 08:00 - 09:00"), a ``.cost``,
        and a court name in the ancestor ``.resource`` header ``<h3>``. We extract
        it all in one in-frame evaluation for speed and robustness.
        """
        frame = self._grid_frame(page)
        raw = frame.evaluate(
            """() => Array.from(document.querySelectorAll('a.book-interval.not-booked'))
                .map(a => {
                    const res = a.closest('.resource');
                    const h3 = res ? res.querySelector('h3') : null;
                    const label = a.querySelector('.available-booking-slot');
                    const cost = a.querySelector('.cost');
                    return {
                        testId: a.getAttribute('data-test-id') || '',
                        court: h3 ? h3.textContent.trim() : '',
                        label: label ? label.textContent.trim() : '',
                        cost: cost ? cost.textContent.trim() : '',
                    };
                })"""
        )

        slots: list[Slot] = []
        for item in raw:
            slot = self._parse_cell(item)
            if slot is not None:
                slots.append(slot)
        slots.sort(key=lambda s: (s.start_time, s.court))
        return slots

    def _parse_cell(self, item: dict) -> Slot | None:
        """Turn one extracted cell dict into a :class:`Slot` (no end_time)."""
        start = self._parse_time(item.get("label", ""))
        if start is None:
            return None
        test_id = item.get("testId", "")
        return Slot(
            court=item.get("court") or "Court",
            start_time=start,
            price=(item.get("cost") or None),
            # Click target within the grid iframe, keyed by the stable data-test-id.
            selector=f'a.book-interval[data-test-id="{test_id}"]' if test_id else None,
        )

    @staticmethod
    def _parse_time(text: str) -> time | None:
        """Extract an HH:MM time from arbitrary cell text/attribute."""
        match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
        if not match:
            return None
        return time(int(match.group(1)), int(match.group(2)))

    # -- booking --------------------------------------------------------------

    def _book_slot(self, page: Page, slot: Slot) -> str | None:
        """Click the slot, confirm, and pay if the venue charges for the slot.

        Raises :class:`PaymentError` if a paid checkout is reached but payment
        cannot be completed (e.g. no card configured, or the payment step is left
        in dry-run because ``CONFIRM_PAYMENT`` is not set).
        """
        if not slot.selector:
            raise RuntimeError("Slot has no selector to click.")
        frame = self._grid_frame(page)
        frame.click(slot.selector)
        page.wait_for_load_state("networkidle")

        # The confirm/continue button may live in the iframe or the top page.
        for target in (frame, page):
            try:
                target.click(SEL_CONFIRM_BUTTON, timeout=8000)
                page.wait_for_load_state("networkidle")
                break
            except PlaywrightTimeoutError:
                continue
        else:
            log.warning("No explicit confirm button found; assuming single-step booking.")

        # If a paid checkout appeared, handle card entry + payment.
        self._handle_payment(page)

        return self._read_confirmation(page)

    def _handle_payment(self, page: Page) -> None:
        """Detect and complete a paid checkout, if one is present.

        Does nothing when no payment form is detected (free / already-confirmed
        booking). When a checkout is detected, fills the card fields and then
        pays -- but ONLY if ``settings.confirm_payment`` is true. Otherwise it
        stops before paying (dry run) and raises :class:`PaymentError` so the run
        is reported as not completed rather than silently spending money.
        """
        target = self._payment_target(page)
        if target is None:
            log.info("No payment step detected; treating as a free/confirmed booking.")
            return

        if not self.settings.has_card_details:
            raise PaymentError(
                "A paid checkout was reached but no card details are configured "
                "(CARD_NUMBER / CARD_EXPIRY / CARD_CVV)."
            )

        log.info("Payment step detected; filling card details.")
        self._fill_card(target)

        if not self.settings.confirm_payment:
            self._screenshot(page, "payment-dryrun")
            raise PaymentError(
                "Reached the payment step and filled the card, but CONFIRM_PAYMENT "
                "is not enabled -- stopping before paying (dry run). Set "
                "CONFIRM_PAYMENT=true to complete real, paid bookings."
            )

        log.warning("CONFIRM_PAYMENT enabled -- submitting payment (this spends money).")
        self._click_first(target, page, SEL_PAY_BUTTON, timeout=10000)
        page.wait_for_load_state("networkidle")

    def _payment_target(self, page: Page):
        """Return the frame/page containing the card form, or None if absent.

        Checks the top page and every frame (paid checkouts are often in a
        third-party iframe). Returns the first context exposing a card field.
        """
        candidates = [page, *page.frames]
        for target in candidates:
            try:
                if target.locator(SEL_PAY_PAGE_MARKER).count() > 0:
                    return target
            except Exception:  # noqa: BLE001 - frame may be mid-navigation
                continue
        return None

    def _fill_card(self, target) -> None:
        """Fill the card fields on the payment target (best-effort per field)."""
        s = self.settings
        self._fill_if_present(target, SEL_CARD_NUMBER, s.card_number)
        self._fill_if_present(target, SEL_CARD_EXPIRY, s.card_expiry)
        self._fill_if_present(target, SEL_CARD_CVV, s.card_cvv)
        if s.card_name:
            self._fill_if_present(target, SEL_CARD_NAME, s.card_name)
        if s.card_postcode:
            self._fill_if_present(target, SEL_CARD_POSTCODE, s.card_postcode)

    @staticmethod
    def _fill_if_present(target, selector: str, value: str) -> None:
        try:
            loc = target.locator(selector).first
            if loc.count() > 0:
                loc.fill(value, timeout=8000)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not fill %r: %s", selector, exc)

    @staticmethod
    def _click_first(*targets_and_selector, timeout: int) -> None:
        *targets, selector = targets_and_selector
        for target in targets:
            try:
                target.click(selector, timeout=timeout)
                return
            except PlaywrightTimeoutError:
                continue
        raise PaymentError(f"Could not find the pay button ({selector}).")

    def _read_confirmation(self, page: Page) -> str | None:
        # Confirmation text may render in the iframe or the top-level page.
        targets = [page]
        try:
            targets.insert(0, self._grid_frame(page))
        except Exception:  # noqa: BLE001 - frame may be gone after redirect
            pass
        for target in targets:
            try:
                loc = target.locator(SEL_CONFIRMATION).first
                if loc.count() > 0:
                    return loc.inner_text(timeout=5000).strip()
            except Exception:  # noqa: BLE001
                continue
        return None

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _add_minutes(t: time, minutes: int) -> time:
        base = datetime(2000, 1, 1, t.hour, t.minute)
        return (base + timedelta(minutes=minutes)).time()

    def _screenshot(self, page: Page, label: str) -> str | None:
        try:
            SCREENSHOT_DIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = SCREENSHOT_DIR / f"{label}-{stamp}.png"
            page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:  # noqa: BLE001
            return None

    def _pause_on_error(self) -> None:
        """Hold the visible browser window open so the failure can be inspected.

        No-op when running headless (nothing to look at) or when disabled. In an
        interactive terminal it blocks until you press Enter; otherwise (e.g. run
        from a scheduler) it waits up to ``keep_open_seconds``.
        """
        if self.settings.headless or not self.settings.keep_open_on_error:
            return
        secs = self.settings.keep_open_seconds
        log.warning(
            "Error occurred - leaving the browser window open for inspection. "
            "Press Enter here to close it (auto-closes in %ds).", secs,
        )
        try:
            if sys.stdin and sys.stdin.isatty():
                input()  # block until the user presses Enter
            else:
                _sleep(secs)  # non-interactive: hold the window open for a while
        except (EOFError, KeyboardInterrupt):
            pass
