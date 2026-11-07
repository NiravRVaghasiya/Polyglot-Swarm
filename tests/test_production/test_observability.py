"""Metrics, access logs, correlation, alert rules and dashboards (R9)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yaml

from src.observability import metrics
from src.observability.logging_config import CorrelationFilter

ROOT = Path(__file__).parents[2]
ALERTS = ROOT / "ops" / "prometheus" / "alerts.yml"
DASHBOARD = ROOT / "ops" / "grafana" / "polyglot-dashboard.json"
RUNBOOK = ROOT / "docs" / "production" / "operations-runbook.md"
_LABELS = r'(\{[a-z_]+="[^"]*"(,[a-z_]+="[^"]*")*\})?'
_VALUE = r"(-?[0-9.]+(e[+-][0-9]+)?|[+-]?Inf|NaN)"
_SAMPLE = re.compile(rf"^[a-z_]+{_LABELS} {_VALUE}$")


def _referenced_metrics(text: str) -> set[str]:
    names = set(re.findall(r"\bpolyglot_[a-z_]+", text))
    return {re.sub(r"_(bucket|sum|count)$", "", n) for n in names}


def _anchor(heading: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).strip().replace(" ", "-")


class TestMetricsEndpoint:
    def test_exposition_format_and_route_templates(self, auth_client, mock_llm):
        client, headers, user_id = auth_client
        sid = client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
        ).json()["session_id"]
        client.get(f"/api/v1/sessions/{sid}/state", headers=headers)
        text = client.get("/metrics").text
        for line in text.splitlines():
            assert line.startswith("# ") or _SAMPLE.match(line), line
        assert 'route="/api/v1/sessions/{session_id}/state"' in text
        # No raw ids, user ids or tokens in label values.
        assert sid not in text and user_id not in text and "Bearer" not in text
        assert 'polyglot_session_events_total{event="started"}' in text

    def test_histogram_buckets_are_cumulative(self):
        h = metrics.Histogram("t_seconds", "test", ("route",), buckets=(0.1, 1.0))
        for v in (0.05, 0.5, 5.0):
            h.observe(v, route="/x")
        lines = h.samples()
        assert 't_seconds_bucket{route="/x",le="0.1"} 1' in lines
        assert 't_seconds_bucket{route="/x",le="1"} 2' in lines
        assert 't_seconds_bucket{route="/x",le="+Inf"} 3' in lines


class TestLogs:
    def test_access_log_has_correlation_and_no_secrets(self, auth_client, caplog):
        client, headers, user_id = auth_client
        caplog.set_level(logging.INFO, logger="polyglot.access")
        client.get("/api/v1/learner/plan", headers={**headers, "X-Request-ID": "req-abc-1"})
        records = [r for r in caplog.records if r.name == "polyglot.access"]
        assert records, "no access log line"
        rec = records[-1]
        assert rec.route == "/api/v1/learner/plan" and rec.status == 200
        assert rec.duration_ms >= 0
        line = rec.getMessage() + str(rec.__dict__)
        assert headers["Authorization"].split()[1] not in line and user_id not in line

    def test_correlation_filter_stamps_request_ids(self):
        from src.observability.context import reset_request_id, set_request_id

        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", (), None)
        token = set_request_id("req-42")
        try:
            CorrelationFilter().filter(record)
        finally:
            reset_request_id(token)
        assert record.request_id == "req-42"


class TestAlertsAndDashboards:
    def test_alert_rules_are_well_formed_and_linked_to_the_runbook(self):
        rules = [r for g in yaml.safe_load(ALERTS.read_text(encoding="utf-8"))["groups"]
                 for r in g["rules"]]  # fmt: skip
        anchors = {_anchor(m) for m in re.findall(r"^#+ (.+)$", RUNBOOK.read_text("utf-8"), re.M)}
        assert len(rules) >= 10
        for rule in rules:
            assert rule["expr"] and rule["labels"]["severity"] in {"sev1", "sev2", "sev3"}
            anchor = rule["annotations"]["runbook"].split("#")[1]
            assert anchor in anchors, f"{rule['alert']}: runbook section #{anchor} missing"

    def test_every_referenced_metric_is_exported(self):
        exported = metrics.REGISTRY.names()
        referenced = _referenced_metrics(ALERTS.read_text(encoding="utf-8"))
        referenced |= _referenced_metrics(DASHBOARD.read_text(encoding="utf-8"))
        assert referenced and referenced <= exported, referenced - exported

    def test_dashboard_is_valid_json(self):
        dash = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        assert dash["uid"] == "polyglot-swarm" and len(dash["panels"]) >= 12
