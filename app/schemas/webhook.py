import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel

from app.utils.prefixed_id import PrefixedUUID

# `evt_` because "webhook event" is a mouthful and prefixed ids work best
# when they are short.
type WebhookEventID = Annotated[uuid.UUID, PrefixedUUID("evt")]


class WebhookEventPublic(BaseModel):
    """The safe view of a received webhook event for the demo table.

    The raw payload is intentionally not exposed here: the table lists what
    arrived and its status, not its contents.
    """

    id: WebhookEventID
    slug: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
