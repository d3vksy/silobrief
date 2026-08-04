"""Synthetic retry example. VALIDATION_MODULE_CANARY_RETRY."""

from __future__ import annotations

import urllib3
from private_adapter.client import deliver_internal

from parcel_lab.models import Parcel


def retry_request(parcel: Parcel) -> object:
    retry_policy = urllib3.Retry(total=2)
    deliver_internal(parcel, retry_policy)
    return retry_policy
