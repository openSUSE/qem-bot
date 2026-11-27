# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Channel families: a frozen ``ChannelKind`` per family of channel strings.

A kind knows its prefixes, how a channel string becomes a repository, which product an OBS
project belongs to and how that family's repository URLs are laid out. The registry selects
the kind for a channel string; the configured prefixes of ``settings.channel_kinds`` override
the built-in ones.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import TYPE_CHECKING, NamedTuple

from openqabot.config import settings

if TYPE_CHECKING:
    from collections.abc import Callable


class ChannelType(Enum):
    """Enumeration of channel types."""

    UPDATES = auto()
    SLFO = auto()
    OPENSUSE = auto()


def no_product(_project: str) -> str:
    """Return no product for the families that do not select their repositories by product."""
    return ""


class Repos(NamedTuple):
    """Product and version information for a repository."""

    product: str
    version: str  # for SLFO it is the OBS project name; for others it is the product version
    arch: str
    product_version: str = ""  # if non-empty, "version" is the codestream version or OBS project

    def compute_url(
        self,
        base: str,
        product_name: str | None = None,
        arch: str | None = None,
        path: str = "repodata/repomd.xml",
        project: str | None = None,
    ) -> str:
        """Construct the repository URL."""
        return channel_kind(self.product).repo_url(self, base, product_name, arch or self.arch, path, project)


@dataclass(frozen=True)
class ChannelKind:
    """One family of channel strings and the rules that apply to it."""

    name: str
    channel_type: ChannelType
    prefixes: tuple[str, ...]
    parse: Callable[[str], Repos | None]
    repo_url: Callable[[Repos, str, str | None, str, str, str | None], str]
    product_of: Callable[[str], str] = no_product
    filters_by_product: bool = False


_KINDS: dict[str, ChannelKind] = {}


def register(kind: ChannelKind) -> ChannelKind:
    """Register a channel family and return it for the module-level binding."""
    _KINDS[kind.name] = kind
    return kind


def kinds() -> tuple[ChannelKind, ...]:
    """Return the registered channel families with their configured prefixes."""
    configured = settings.channel_kinds
    return tuple(replace(kind, prefixes=tuple(configured.get(kind.name, kind.prefixes))) for kind in _KINDS.values())


def channel_kind(channel: str) -> ChannelKind:
    """Return the channel family a channel string belongs to, defaulting to updates."""
    families = kinds()
    matched = [kind for kind in families if any(_is_prefixed(channel, prefix) for prefix in kind.prefixes)]
    return matched[0] if matched else next(kind for kind in families if kind.channel_type is ChannelType.UPDATES)


def get_channel_type(channel: str) -> ChannelType:
    """Determine the channel type of a channel or product string."""
    return channel_kind(channel).channel_type


def _is_prefixed(channel: str, prefix: str) -> bool:
    """Match a channel against a configured prefix, anchored at a family separator."""
    return channel == prefix or channel.startswith((f"{prefix}:", f"{prefix}-"))
