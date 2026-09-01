"""End-to-end CLI behaviour, including the exit codes CI depends on."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from preflight.cli import main

ROOT = Path(__file__).resolve().parents[1]
CLEAN = "src/preflight/evals/samples/sample_6_clean.html"
MIXED = "src/preflight/evals/samples/sample_5_mixed.html"


def run_cli(*args):
    return main(list(args))


def test_audit_clean_sample_exits_zero(corpus, capsys):
    assert run_cli("audit", str(corpus / "sample_6_clean.html"), "--offline", "--no-llm") == 0
    assert "READY" in capsys.readouterr().out


def test_audit_strict_blocks_a_broken_send(corpus, capsys):
    code = run_cli("audit", str(corpus / "sample_5_mixed.html"), "--offline", "--no-llm", "--strict")
    assert code == 1
    assert "HOLD" in capsys.readouterr().out


def test_audit_without_strict_never_blocks(corpus):
    assert run_cli("audit", str(corpus / "sample_5_mixed.html"), "--offline", "--no-llm") == 0


def test_audit_json_is_machine_readable(corpus, capsys):
    run_cli("audit", str(corpus / "sample_1_contrast.html"), "--offline", "--no-llm", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["code"] == "contrast.aa_fail"
    assert payload["timing"]["total_ms"] > 0


def test_audit_missing_file_exits_two(capsys):
    assert run_cli("audit", "does-not-exist.html") == 2


def test_fix_writes_the_expected_filename(corpus, tmp_path, capsys):
    source = tmp_path / "email.html"
    source.write_text((corpus / "sample_1_contrast.html").read_text())
    assert run_cli("fix", str(source), "--offline") == 0
    assert (tmp_path / "fixed_email.html").exists()
    assert "HOLD" in capsys.readouterr().out


def test_fix_dry_run_leaves_the_disk_alone(corpus, tmp_path, capsys):
    source = tmp_path / "email.html"
    source.write_text((corpus / "sample_1_contrast.html").read_text())
    assert run_cli("fix", str(source), "--offline", "--dry-run") == 0
    assert not (tmp_path / "fixed_email.html").exists()


def test_fixing_clears_the_verdict(corpus, tmp_path):
    import asyncio
    from preflight.audit import audit_file
    source = tmp_path / "email.html"
    source.write_text((corpus / "sample_1_contrast.html").read_text())
    run_cli("fix", str(source), "--offline")
    before = asyncio.run(audit_file(source, offline_links={}, skip_llm=True))
    after = asyncio.run(audit_file(tmp_path / "fixed_email.html", offline_links={}, skip_llm=True))
    assert before.verdict == "HOLD"
    # Every AA failure is repairable, so nothing blocks any more. It lands on
    # REVIEW rather than READY because the fixer targets AA and the AAA
    # shortfalls survive - which is the honest result, not a miss.
    assert after.verdict == "REVIEW"
    assert after.blocking_findings == []


def test_eval_renders_and_exits_zero(capsys):
    assert run_cli("eval") == 0
    out = capsys.readouterr().out
    assert "Accuracy by module" in out and "Blended" in out


def test_eval_strict_passes_at_current_quality():
    assert run_cli("eval", "--strict", "--json") == 0


def test_eval_json_shape(capsys):
    run_cli("eval", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["modules"]) == {"deterministic", "llm"}
    assert payload["clean_control_false_positives"] == 0
    assert len(payload["cases"]) == 8


def test_eval_strict_fails_when_the_bar_is_impossible():
    assert run_cli("eval", "--strict", "--min-f1", "1.01", "--json") == 1


@pytest.mark.parametrize("args", [["audit"], ["fix"], ["nonsense"], []])
def test_bad_invocations_are_rejected(args):
    with pytest.raises(SystemExit):
        run_cli(*args)


def test_root_entrypoint_works_from_a_clean_checkout():
    """`python cli.py audit <file>` must work without installing anything."""
    result = subprocess.run(
        [sys.executable, "cli.py", "audit", CLEAN, "--offline", "--no-llm"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "READY" in result.stdout


def test_root_entrypoint_eval():
    result = subprocess.run(
        [sys.executable, "cli.py", "eval", "--json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["modules"]["deterministic"]["f1"] == 1.0
