"""Onboarding state.

The welcome banner on the home page is a two-step checklist: verify
your email, upload a profile photo. Both bits are already tracked on
the User row, so this module just projects them into a small view-
shape the template can iterate over. No dismissal flag and no extra
column - when both steps complete, `is_complete` flips and the banner
hides itself.

Keeping the projection here (not inline in the route) means the home
template's `{% if onboarding.steps %}` stays readable and the same
shape is available to anywhere else that wants to nudge a partial
user (a future "Welcome" email, an admin dashboard, etc.)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.user import User


@dataclass(frozen=True, slots=True)
class OnboardingStep:
    """One row in the checklist. `done` drives the strikethrough/check
    in the template; `href` is the link the user follows to finish it."""

    key: str
    title: str
    body: str
    href: str
    done: bool


@dataclass(frozen=True, slots=True)
class OnboardingState:
    steps: tuple[OnboardingStep, ...]

    @property
    def is_complete(self) -> bool:
        return all(s.done for s in self.steps)

    @property
    def remaining(self) -> int:
        return sum(1 for s in self.steps if not s.done)


def state_for(user: User) -> OnboardingState:
    """Build the checklist for a logged-in user. Anonymous visitors never
    see this - the route only calls in when `user is not None` - so the
    function takes a non-optional User and the template never branches on
    None inside the banner."""
    return OnboardingState(
        steps=(
            OnboardingStep(
                key="verify_email",
                title="Verify your email",
                body=(
                    "We sent a confirmation link to the address you signed "
                    "up with. Verifying unlocks password reset and the "
                    "transactional email demo."
                ),
                href="/auth/verify-needed",
                done=user.email_verified_at is not None,
            ),
            OnboardingStep(
                key="add_avatar",
                title="Add a profile photo",
                body=(
                    "The header chip and sessions list look better with a "
                    "face on them. PNG, JPEG, or WEBP up to 4 MB."
                ),
                href="/account",
                done=user.avatar_url is not None,
            ),
        ),
    )
