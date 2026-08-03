"""Retry request fixture. PUBLIC_DOCSTRING_CANARY."""

from __future__ import annotations

import urllib3
from private_adapter.client import deliver_internal

from parcel_sync.models import Parcel

PUBLIC_STRING = "PUBLIC_STRING_CANARY"


def retry_request(parcel: Parcel) -> object:
    # PUBLIC_COMMENT_CANARY
    PUBLIC_SOURCE_BODY_CANARY = urllib3.Retry(total=2)
    deliver_internal(parcel)
    return PUBLIC_SOURCE_BODY_CANARY
