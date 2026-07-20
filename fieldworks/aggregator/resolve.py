"""Runtime enforcement of ServerDef's scoping declarations.

config.py's ServerDef/AggregatorConfig only declare include_tools/default_args
— they don't apply them. Live tool introspection and dispatch stay the host
aggregator's job (this module has no I/O), but the actual filter/merge logic
is a handful of pure lines every host would otherwise reimplement identically.
See fieldworks-examples/05_scoped_tools, which used to hand-roll exactly this.
"""

from __future__ import annotations

from .config import ServerDef


def resolve_tools(server: ServerDef, available_tools: list[str]) -> list[str]:
    """What a specialist actually gets handed for this server: available_tools
    filtered by include_tools if set, otherwise everything."""
    if server.include_tools is None:
        return list(available_tools)
    return [t for t in available_tools if t in server.include_tools]


def merge_call_args(server: ServerDef, explicit_args: dict) -> dict:
    """default_args merged in under whatever the caller passes explicitly —
    explicit args always win."""
    return {**(server.default_args or {}), **explicit_args}
