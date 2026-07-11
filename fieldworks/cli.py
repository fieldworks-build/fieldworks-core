"""fieldworks CLI

fieldworks validate topology.yaml [--aggregator aggregator.json] [--seed]
fieldworks test-adapter --command "<binary> [args...]" [--host HOST] [--port PORT]
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _usage()

    subcommand, rest = args[0], args[1:]
    if subcommand == "validate":
        _main_validate(rest)
    elif subcommand == "test-adapter":
        _main_test_adapter(rest)
    else:
        _usage()


def _main_validate(args: list[str]) -> None:
    topology_path: Path | None = None
    aggregator_path: Path | None = None
    seed = False
    i = 0
    while i < len(args):
        if args[i] == "--aggregator" and i + 1 < len(args):
            aggregator_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--seed":
            seed = True
            i += 1
        else:
            topology_path = Path(args[i])
            i += 1

    if topology_path is None:
        _usage()

    _run_validate(topology_path, aggregator_path, seed)


def _run_validate(
    topology_path: Path, aggregator_path: Path | None, seed: bool
) -> None:
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
        warn_str = (
            f" ({warning_count} warning{'s' if warning_count != 1 else ''})"
            if warning_count
            else ""
        )
        print(
            f"{topology_path}: valid — {area_count} process areas,"
            f" {type_count} equipment types, {inst_count} instances{warn_str}"
        )
    else:
        sys.exit(1)

    if seed:
        _run_seed(topology)


def _run_seed(topology) -> None:
    try:
        import tempfile

        from fieldworks.memory.graph import GraphClient, GraphConfig
        from fieldworks.topology.seeder import seed_topology
    except ImportError:
        print(
            "error: --seed requires the memory extra: pip install fieldworks-core[memory]",
            file=sys.stderr,
        )
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        client = GraphClient(GraphConfig(db_path=Path(tmp) / "seed-check.db"))
        try:
            counts = seed_topology(topology, client)
        except Exception as exc:
            print(f"error: seeding failed: {exc}", file=sys.stderr)
            sys.exit(1)

    print(
        "seed check ok — "
        f"{counts['process_areas']} process areas, "
        f"{counts['equipment_types']} equipment types, "
        f"{counts['attributes']} attributes, "
        f"{counts['fault_modes']} fault modes, "
        f"{counts['equipment_instances']} equipment instances, "
        f"{counts['tag_bindings']} tag bindings"
    )


def _main_test_adapter(args: list[str]) -> None:
    command: str | None = None
    host: str | None = None
    port: int | None = None
    i = 0
    while i < len(args):
        if args[i] == "--command" and i + 1 < len(args):
            command = args[i + 1]
            i += 2
        elif args[i] == "--host" and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1

    if command is None:
        _usage()

    _run_test_adapter(command, host, port)


def _run_test_adapter(command: str, host: str | None, port: int | None) -> None:
    try:
        import asyncio
        import shlex

        from fieldworks.adapters.conformance import run_conformance
    except ImportError:
        print(
            "error: test-adapter requires the adapters extra:"
            " pip install fieldworks-core[adapters]",
            file=sys.stderr,
        )
        sys.exit(1)

    parts = shlex.split(command)
    binary, binary_args = parts[0], parts[1:]

    report = asyncio.run(
        run_conformance(binary, binary_args, connect_host=host, connect_port=port)
    )

    for check in report.checks:
        status = "SKIP" if check.skipped else ("PASS" if check.passed else "FAIL")
        suffix = f" — {check.message}" if check.message else ""
        print(f"[{status}] {check.name}{suffix}")

    if not report.passed:
        sys.exit(1)


def _usage() -> None:
    print(
        "usage: fieldworks validate topology.yaml [--aggregator aggregator.json] [--seed]\n"
        '       fieldworks test-adapter --command "<binary> [args...]"'
        " [--host HOST] [--port PORT]",
        file=sys.stderr,
    )
    sys.exit(1)
