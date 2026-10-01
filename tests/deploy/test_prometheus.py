"""Structural checks for deploy/prometheus/alerts.yml (promtool-compatible shape).

The file is parsed with a tiny indentation-aware reader so the test does not need PyYAML.
"""

from __future__ import annotations

import re
from pathlib import Path

ALERTS = Path(__file__).resolve().parents[2] / "deploy" / "prometheus" / "alerts.yml"
REQUIRED = {
    "SearchIwaraDown": "up{",
    "SearchIwaraSyncStale": "search_iwara_last_sync_success_timestamp_seconds",
    "SearchIwaraSyncFailed": "search_iwara_last_sync_failed == 1",
    "SearchIwaraThrottled": "search_iwara_last_sync_throttled > 10",
    "SearchIwaraHighLatency": "histogram_quantile(",
}


def rules() -> dict[str, str]:
    text = ALERTS.read_text(encoding="utf-8")
    assert text.lstrip().startswith("#") or text.startswith("groups:")
    assert "\ngroups:\n" in f"\n{text}"
    blocks = re.split(r"\n      - alert: ", text)[1:]
    return {block.split("\n", 1)[0].strip(): block for block in blocks}


def test_alert_rules_present_with_expected_expressions():
    parsed = rules()
    assert set(parsed) == set(REQUIRED)
    for name, fragment in REQUIRED.items():
        assert fragment in parsed[name], name


def test_every_rule_has_for_severity_and_annotations():
    for name, block in rules().items():
        assert re.search(r"\n        expr: ", block), name
        assert re.search(r"\n        for: \d+m", block), name
        assert re.search(r"\n          severity: (critical|warning|info)", block), name
        assert "summary:" in block, name
        assert "description:" in block, name
    assert "\t" not in ALERTS.read_text(encoding="utf-8")
