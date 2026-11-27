# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Channel families: the channel string families openQA jobs read.

Importing this package registers the families, so a channel string resolves to its kind.
"""

from . import opensuse, slfo, updates
from .base import ChannelKind, ChannelType, Repos, channel_kind, filters_by_product, get_channel_type, kinds

__all__ = [
    "ChannelKind",
    "ChannelType",
    "Repos",
    "channel_kind",
    "filters_by_product",
    "get_channel_type",
    "kinds",
    "opensuse",
    "slfo",
    "updates",
]
