# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""YAML 1.2 core schema loading with the optional merge-key schema.

The loader comparison behind this choice is recorded in `doc/yaml-parser.md`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, override

import yaml
import yamlcore
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, SequenceNode

if TYPE_CHECKING:
    from yaml.nodes import Node

_MERGE_TAG = "tag:yaml.org,2002:merge"
Yaml12Error = yaml.YAMLError
_MAPPING_CONTEXT = "while constructing a mapping"


def _split_merge_sources(node: MappingNode) -> tuple[list[MappingNode], list[tuple[Node, Node]]]:
    sources: list[MappingNode] = []
    own: list[tuple[Node, Node]] = []
    for key_node, value_node in node.value:
        if key_node.tag != _MERGE_TAG:
            own.append((key_node, value_node))
        elif isinstance(value_node, MappingNode):
            sources.append(value_node)
        elif isinstance(value_node, SequenceNode):
            sources.extend(_sequence_sources(value_node))
        else:
            msg = f"expected a mapping or list of mappings for merging, but found {value_node.id}"
            raise ConstructorError(_MAPPING_CONTEXT, node.start_mark, msg, value_node.start_mark)
    return sources, own


def _sequence_sources(value_node: SequenceNode) -> list[MappingNode]:
    sources = []
    for subnode in value_node.value:
        if not isinstance(subnode, MappingNode):
            msg = f"expected a mapping for merging, but found {subnode.id}"
            raise ConstructorError(_MAPPING_CONTEXT, value_node.start_mark, msg, subnode.start_mark)
        sources.append(subnode)
    return sources


class Yaml12Loader(yamlcore.CCoreLoader):
    """Loader for YAML 1.2 core documents that also resolves `<<` merge keys.

    Merge keys are a YAML 1.1 type outside the 1.2 core schema; `OpenQA::YAML` enables them as an
    additional schema on top of the core schema in the same way.
    """

    @override
    def construct_mapping(self, node: Node, deep: bool = False) -> dict[object, object]:
        if isinstance(node, MappingNode):
            self._flatten_merge_keys(node)
        return super().construct_mapping(node, deep)

    def _flatten_merge_keys(self, node: MappingNode) -> None:
        """Inline the pairs of every `<<` source ahead of the mapping's own pairs.

        PyYAML's `flatten_mapping` does the same. Reading a source's constructed object instead
        would see an empty mapping whenever the source has not been filled yet: a mapping node is
        filled by a state generator that runs after `construct_object` returns it.
        """
        sources, own = _split_merge_sources(node)
        if len(own) == len(node.value):
            return
        # Dropping the merge pairs before the sources are visited terminates a self-merge, which
        # resolves to the mapping's own keys the way PyYAML's flatten_mapping resolves it.
        node.value = own
        # A key already seen wins, so the mapping's own keys beat every source, an earlier source
        # beats a later one, and yamlcore's duplicate check keeps seeing only the own keys.
        keys = [self.construct_object(key_node) for key_node, _ in own]
        kept: list[tuple[Node, Node]] = []
        for source in sources:
            self._flatten_merge_keys(source)
            taken: list[object] = []
            for key_node, value_node in source.value:
                key = self.construct_object(key_node)
                if key in taken:
                    msg = "found duplicate key"
                    raise ConstructorError(_MAPPING_CONTEXT, source.start_mark, msg, key_node.start_mark)
                taken.append(key)
                if key not in keys:
                    keys.append(key)
                    kept.append((key_node, value_node))
        node.value = kept + own


Yaml12Loader.add_implicit_resolver(_MERGE_TAG, re.compile(r"^<<$"), ["<"])


def load(content: str) -> object:
    """Parse one YAML document with the 1.2 core schema, resolving `<<` merge keys."""
    loader = Yaml12Loader(content)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
