"""fieldworks CLI — fieldworks validate topology.yaml [--aggregator aggregator.json]"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] != "validate":
        _usage()

    topology_path: Path | None = None
    aggregator_path: Path | None = None
    i = 1
    while i < len(args):
        if args[i] == "--aggregator" and i + 1 < len(args):
            aggregator_path = Path(args[i + 1])
            i += 2
        else:
            topology_path = Path(args[i])
            i += 1

    if topology_path is None:
        _usage()

    _run_validate(topology_path, aggregator_path)


def _run_validate(topology_path: Path, aggregator_path: Path | None) -> None:
    from fieldworks.topology.loader import load
    from fieldworks.topology.validator import validate

    try:
        topology = load(topology_path)
    except FileNotFoundError:
        print(f"error: file not found: {topology_path}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    aggregator_names: set[str] | None = None
    if aggregator_path is not None:
        from fieldworks.aggregator.config import load_aggregator_config
        try:
            agg = load_aggregator_config(aggregator_path)
            aggregator_names = agg.server_names()
        except (FileNotFoundError, ValueError) as exc:
            print(f"error loading aggregator: {exc}", file=sys.stderr)
            sys.exit(1)

    result = validate(topology, aggregator_server_names=aggregator_names)

    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}", file=sys.stderr)

    if result.valid:
        area_count = len(topology.process_areas)
        type_count = len(topology.equipment_types)
        inst_count = len(topology.equipment_instances)
        warning_count = len(result.warnings)
        warn_str = f" ({warning_count} warning{'s' if warning_count != 1 else ''})" if warning_count else ""
        print(
            f"{topology_path}: valid — {area_count} process areas,"
            f" {type_count} equipment types, {inst_count} instances{warn_str}"
        )
    else:
        sys.exit(1)


def _usage() -> None:
    print(
        "usage: fieldworks validate topology.yaml [--aggregator aggregator.json]",
        file=sys.stderr,
    )
    sys.exit(1)
