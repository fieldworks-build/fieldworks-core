"""Tests for the fieldworks CLI's --seed flag."""


def test_run_validate_seed_prints_counts(wtp_topology_path, capsys):
    from fieldworks.cli import _run_validate

    _run_validate(wtp_topology_path, None, seed=True)
    out = capsys.readouterr().out
    assert "valid" in out
    assert "seed check ok" in out
    assert "equipment instances" in out


def test_run_validate_without_seed_flag_skips_seeding(wtp_topology_path, capsys):
    from fieldworks.cli import _run_validate

    _run_validate(wtp_topology_path, None, seed=False)
    out = capsys.readouterr().out
    assert "valid" in out
    assert "seed check" not in out
