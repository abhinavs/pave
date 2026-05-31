# Import every model here so Alembic's `from app.models import *` sees them
# and autogenerate picks up their tables.
from app.models.session import Session
from app.models.user import User
from app.models.webhook import WebhookEvent

__all__ = ["Session", "User", "WebhookEvent"]
