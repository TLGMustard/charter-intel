"""
tests/unit/test_dry_run.py

Regression guard: --dry-run must never trigger live API calls in any stage.

S6 (s6_synthesis) was the only stage missing a dry-run guard (confirmed by
grep: s2, s3, s4 all had guards; s6 had none before the Session 18 fix).
These tests verify the fix is in place and covers both execution paths:
  - standard-brief mode (run() → _generate_brief + _run_audit)
  - scan mode         (run() → _run_scan_synthesis)

Scenarios covered:
  1. Standard-brief: cache miss + dry_run=True  → SKIPPED, zero API calls
  2. Scan mode:      cache miss + dry_run=True  → SKIPPED, zero API calls
  3. Cache-hit path: cache populated, dry_run=True → SUCCESS (cache wins, zero API calls)
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from pipeline import (
    OperatorPreset, OutputMode, PipelineConfig, StageStatus,
)
from pipeline.s6_synthesis import run as s6_run

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _chdir_root(monkeypatch):
    monkeypatch.chdir(_ROOT)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_config(
    *,
    dry_run: bool,
    mode: OutputMode = OutputMode.STRATEGIC_BRIEF,
    cache_enabled: bool = False,
    force_refresh: bool = True,
) -> PipelineConfig:
    """Minimal PipelineConfig for unit tests — no real API credentials needed."""
    return PipelineConfig(
        state="NM",
        preset=OperatorPreset.MATURITY_ADJUSTED,
        mode=mode,
        output_format="markdown",
        cache_enabled=cache_enabled,
        dry_run=dry_run,
        force_refresh=force_refresh,
    )


def _fake_inputs_ok():
    """Return a (bundle, scorecard, errors=[]) tuple suitable for _load_inputs mock."""
    bundle = {
        "facts": [
            {"fact_id": f"f{i}", "in_main_analysis": True, "claim": f"claim {i}"}
            for i in range(5)
        ]
    }
    scorecard = {
        "composite_score": 6.0,
        "composite_score_rounded": 6.0,
        "tier": "MODERATE",
        "data_coverage_tier": "reliable",
        "confidence_overall": "MODERATE",
        "override_flags": [],
    }
    return bundle, scorecard, []


# ─────────────────────────────────────────────────────────────────────────────
# Standard-brief mode (OutputMode.STRATEGIC_BRIEF)
# ─────────────────────────────────────────────────────────────────────────────

class TestS6DryRunStandardBrief:
    @patch("pipeline.s6_synthesis.call_claude")
    @patch("pipeline.s6_synthesis._load_inputs")
    def test_dry_run_returns_skipped(self, mock_load_inputs, mock_call_claude):
        """cache miss + dry_run=True must return SKIPPED."""
        mock_load_inputs.return_value = _fake_inputs_ok()

        result = s6_run("nm-dry-run-test", "NM", _make_config(dry_run=True))

        assert result.status == StageStatus.SKIPPED

    @patch("pipeline.s6_synthesis.call_claude")
    @patch("pipeline.s6_synthesis._load_inputs")
    def test_dry_run_makes_zero_api_calls(self, mock_load_inputs, mock_call_claude):
        """call_claude must never be invoked when dry_run=True (cache miss)."""
        mock_load_inputs.return_value = _fake_inputs_ok()

        s6_run("nm-dry-run-test", "NM", _make_config(dry_run=True))

        mock_call_claude.assert_not_called()

    @patch("pipeline.s6_synthesis.call_claude")
    @patch("pipeline.s6_synthesis._load_inputs")
    def test_dry_run_warning_text(self, mock_load_inputs, mock_call_claude):
        """SKIPPED result should carry a human-readable warning."""
        mock_load_inputs.return_value = _fake_inputs_ok()

        result = s6_run("nm-dry-run-test", "NM", _make_config(dry_run=True))

        assert result.warnings, "Expected at least one warning on SKIPPED result"
        assert any("dry run" in w.lower() for w in result.warnings)


# ─────────────────────────────────────────────────────────────────────────────
# Scan mode (OutputMode.SCAN)
# ─────────────────────────────────────────────────────────────────────────────

class TestS6DryRunScanMode:
    @patch("pipeline.s6_synthesis.call_claude")
    @patch("pipeline.s6_synthesis._load_inputs")
    def test_scan_dry_run_returns_skipped(self, mock_load_inputs, mock_call_claude):
        """Scan mode: cache miss + dry_run=True → SKIPPED."""
        mock_load_inputs.return_value = _fake_inputs_ok()

        result = s6_run(
            "nm-dry-run-test", "NM",
            _make_config(dry_run=True, mode=OutputMode.SCAN),
        )

        assert result.status == StageStatus.SKIPPED

    @patch("pipeline.s6_synthesis.call_claude")
    @patch("pipeline.s6_synthesis._load_inputs")
    def test_scan_dry_run_makes_zero_api_calls(self, mock_load_inputs, mock_call_claude):
        """call_claude must never be invoked in scan-mode dry-run (cache miss)."""
        mock_load_inputs.return_value = _fake_inputs_ok()

        s6_run(
            "nm-dry-run-test", "NM",
            _make_config(dry_run=True, mode=OutputMode.SCAN),
        )

        mock_call_claude.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Cache-hit path: a warm cache must be returned even in dry-run
# ─────────────────────────────────────────────────────────────────────────────

class TestS6DryRunCacheHit:
    @patch("pipeline.s6_synthesis.call_claude")
    @patch("pipeline.s6_synthesis._load_inputs")
    @patch("pipeline.s6_synthesis.CacheManager")
    def test_cache_hit_serves_brief_without_api_call(
        self, MockCacheManager, mock_load_inputs, mock_call_claude
    ):
        """When the synthesis cache is warm, dry-run returns SUCCESS+cache_hit
        rather than SKIPPED — the guard is placed after the cache check on
        purpose so cached runs are never blocked."""
        mock_load_inputs.return_value = _fake_inputs_ok()

        fake_brief = {"scorecard_summary": {}, "community": "nm-dry-run-test"}
        mock_cm = MagicMock()
        mock_cm.get.return_value = fake_brief
        MockCacheManager.return_value = mock_cm

        config = _make_config(dry_run=True, cache_enabled=True, force_refresh=False)
        result = s6_run("nm-dry-run-test", "NM", config)

        assert result.status == StageStatus.SUCCESS
        assert result.cache_hit is True
        mock_call_claude.assert_not_called()
