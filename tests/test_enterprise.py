"""Tests for fieldworks.enterprise — registry, validation, federated read (spec Part V)."""

import asyncio
import shutil
from pathlib import Path

import pytest
import yaml

from fieldworks.enterprise import (
    SiteUnavailable,
    UnknownSiteError,
    federated_read,
    load,
    validate,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _site(site_id: str, topology_file: str = "riverside.yaml", **extra) -> dict:
    return {
        "site_id": site_id,
        "name": site_id.title(),
        "topology_file": topology_file,
        "chat_ui_url": f"http://{site_id}.internal",
        **extra,
    }


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "enterprise.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


@pytest.fixture
def enterprise_dir(tmp_path):
    """A directory with enterprise.yaml beside a real topology (site_id
    wtp-riverside-01), as Part V's relative topology_file paths expect."""
    shutil.copy(FIXTURES / "wtp_topology.yaml", tmp_path / "riverside.yaml")
    return tmp_path


def _valid(**overrides) -> dict:
    data = {
        "enterprise": {"name": "Metro Water"},
        "regions": [
            {
                "id": "metro",
                "name": "Metro Region",
                "sites": [
                    _site("wtp-riverside-01", aggregator_url="http://r/sse"),
                ],
            },
            {"id": "valley", "name": "Valley Region", "sites": []},
        ],
    }
    data.update(overrides)
    return data


# ── load: structural rules ───────────────────────────────────────────────────


def test_load_valid_file_flattens_sites_with_region(enterprise_dir):
    config = load(_write(enterprise_dir, _valid()))
    sites = config.sites()
    assert list(sites) == ["wtp-riverside-01"]
    site = sites["wtp-riverside-01"]
    assert site.region_id == "metro"
    assert site.region_name == "Metro Region"
    assert site.aggregator_url == "http://r/sse"
    assert config.get_site("nope") is None


def test_empty_region_is_allowed(enterprise_dir):
    config = load(_write(enterprise_dir, _valid()))
    assert config.regions[1].sites == []


@pytest.mark.parametrize("field", ["site_id", "name", "topology_file", "chat_ui_url"])
def test_site_missing_required_field_is_an_error_not_skipped(enterprise_dir, field):
    data = _valid()
    del data["regions"][0]["sites"][0][field]
    with pytest.raises(ValueError, match=field):
        load(_write(enterprise_dir, data))


def test_aggregator_url_is_optional(enterprise_dir):
    data = _valid()
    del data["regions"][0]["sites"][0]["aggregator_url"]
    assert (
        load(_write(enterprise_dir, data)).get_site("wtp-riverside-01").aggregator_url
        is None
    )


def test_duplicate_site_id_across_regions_is_rejected(enterprise_dir):
    data = _valid()
    data["regions"][1]["sites"] = [_site("wtp-riverside-01")]
    with pytest.raises(ValueError, match="duplicate site_id 'wtp-riverside-01'"):
        load(_write(enterprise_dir, data))


def test_duplicate_region_id_is_rejected(enterprise_dir):
    data = _valid()
    data["regions"][1]["id"] = "metro"
    with pytest.raises(ValueError, match="duplicate region id"):
        load(_write(enterprise_dir, data))


def test_non_mapping_file_is_rejected(tmp_path):
    path = tmp_path / "enterprise.yaml"
    path.write_text("- just\n- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        load(path)


# ── validate: cross-file rules ───────────────────────────────────────────────


def test_validate_passes_when_topology_site_id_matches(enterprise_dir):
    config = load(_write(enterprise_dir, _valid()))
    result = validate(config, enterprise_dir)
    assert result.valid, result.errors


def test_validate_rejects_site_id_mismatch_with_topology(enterprise_dir):
    data = _valid()
    data["regions"][0]["sites"][0]["site_id"] = "wtp-eastside-01"
    result = validate(load(_write(enterprise_dir, data)), enterprise_dir)
    assert not result.valid
    assert "declares facility.site_id 'wtp-riverside-01'" in result.errors[0]


def test_validate_rejects_missing_topology_file(enterprise_dir):
    data = _valid()
    data["regions"][0]["sites"][0]["topology_file"] = "missing.yaml"
    result = validate(load(_write(enterprise_dir, data)), enterprise_dir)
    assert result.errors == [
        "site 'wtp-riverside-01': topology_file not found: missing.yaml"
    ]


def test_validate_rejects_invalid_topology(enterprise_dir):
    (enterprise_dir / "riverside.yaml").write_text("facility: {name: x}\n")
    result = validate(load(_write(enterprise_dir, _valid())), enterprise_dir)
    assert not result.valid
    assert "not a valid topology.yaml" in result.errors[0]


def test_validate_resolves_topology_relative_to_base_dir(
    enterprise_dir, tmp_path_factory
):
    config = load(_write(enterprise_dir, _valid()))
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert not validate(config, elsewhere).valid
    assert validate(config, enterprise_dir).valid


# ── federated_read ───────────────────────────────────────────────────────────

SITES = {"a": "site-a", "b": "site-b", "c": "site-c"}


def _run(coro):
    return asyncio.run(coro)


def test_federated_read_merges_and_sorts_by_timestamp():
    data = {
        "a": [{"ts": "2026-01-01T03:00:00Z"}, {"ts": "2026-01-01T01:00:00Z"}],
        "b": [{"ts": "2026-01-01T02:00:00Z"}],
        "c": [],
    }

    async def fetch(sid, site):
        return [dict(r) for r in data[sid]]

    result = _run(federated_read(SITES, fetch))
    assert [r["ts"][11:13] for r in result.records] == ["01", "02", "03"]
    assert [r["site_id"] for r in result.records] == ["a", "b", "a"]
    assert result.queried == ["a", "b", "c"]
    assert result.complete


def test_federated_read_keeps_site_id_the_plant_stamped():
    async def fetch(sid, site):
        return [{"ts": "1", "site_id": "plant-stamped"}]

    result = _run(federated_read({"a": None}, fetch))
    assert result.records[0]["site_id"] == "plant-stamped"


def test_federated_read_reports_failed_plant_instead_of_dropping_it():
    async def fetch(sid, site):
        if sid == "b":
            raise ConnectionError("refused")
        return [{"ts": "1"}]

    result = _run(federated_read(SITES, fetch))
    assert not result.complete
    assert result.unavailable == {"b": "ConnectionError: refused"}
    assert {r["site_id"] for r in result.records} == {"a", "c"}


def test_federated_read_site_unavailable_carries_reason():
    async def fetch(sid, site):
        raise SiteUnavailable("no aggregator_url in enterprise.yaml")

    result = _run(federated_read({"a": None}, fetch))
    assert result.unavailable == {"a": "no aggregator_url in enterprise.yaml"}


def test_federated_read_timeout_isolates_slow_plant():
    async def fetch(sid, site):
        if sid == "a":
            await asyncio.sleep(5)
        return [{"ts": "1"}]

    result = _run(federated_read({"a": None, "b": None}, fetch, timeout=0.05))
    assert result.unavailable == {"a": "did not answer within 0.05s"}
    assert [r["site_id"] for r in result.records] == ["b"]


def test_federated_read_runs_plants_in_parallel():
    async def fetch(sid, site):
        await asyncio.sleep(0.2)
        return []

    async def timed():
        loop = asyncio.get_running_loop()
        start = loop.time()
        await federated_read(SITES, fetch)
        return loop.time() - start

    assert _run(timed()) < 0.5


def test_federated_read_single_site():
    async def fetch(sid, site):
        return [{"ts": "1"}]

    result = _run(federated_read(SITES, fetch, site_id="b"))
    assert result.queried == ["b"]
    assert [r["site_id"] for r in result.records] == ["b"]


def test_federated_read_unknown_site_lists_known_sites():
    async def fetch(sid, site):
        return []

    with pytest.raises(UnknownSiteError) as exc:
        _run(federated_read(SITES, fetch, site_id="zzz"))
    assert str(exc.value) == "unknown site_id 'zzz'. Known sites: a, b, c."


def test_federated_read_non_list_answer_is_unavailable():
    async def fetch(sid, site):
        return {"sessions": []}

    result = _run(federated_read({"a": None}, fetch))
    assert result.unavailable == {"a": "returned dict, expected a list of records"}


def test_federated_result_to_dict():
    async def fetch(sid, site):
        if sid == "a":
            raise SiteUnavailable("down")
        return [{"ts": "1"}]

    out = _run(federated_read({"a": None, "b": None}, fetch)).to_dict()
    assert out == {
        "records": [{"ts": "1", "site_id": "b"}],
        "queried": ["a", "b"],
        "unavailable": {"a": "down"},
        "complete": False,
    }
