"""Deterministic AEO experiment supervisor.

The supervisor owns the control flow.  LLM/tool agents are invoked at specific
states, never as an unbounded lead loop.  That keeps approvals, budgets,
resume, and evaluation reproducible.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Sequence

from aeo.content_store import ContentStore
from aeo.providers import MockAEOProvider, MockAnalyticsProvider
from aeo.publish import SandboxPublisher
from approval_store import ApprovalStore
from experiment_store import (
    ExperimentStore,
    default_artifact_root,
    now_iso,
)

TERMINAL_STATES = {"COMPLETED", "FAILED", "ROLLED_BACK"}
READY_STATES = {"DRAFT", "HYPOTHESIZED", "PENDING_APPROVAL", "APPROVED", "OBSERVING", "EVALUATING", "LEARNING"}

DEFAULT_BUDGET = {
    "max_steps": 12,
    "max_llm_calls": 4,
    "max_api_calls": 20,
    "max_wall_seconds": 1800,
}


class SupervisorError(RuntimeError):
    pass


class BudgetExceeded(SupervisorError):
    pass


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _clip(text: str, limit: int = 12000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [truncated]\n"


class Supervisor:
    def __init__(
        self,
        *,
        db_path: str | Path | None = None,
        artifact_root: str | Path | None = None,
        agent_mode: str = "rule",
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.store = ExperimentStore(db_path)
        self.approvals = ApprovalStore(self.store.db_path)
        self.artifact_root = (
            Path(artifact_root).expanduser().resolve()
            if artifact_root
            else default_artifact_root()
        )
        self.agent_mode = agent_mode
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.provider = MockAEOProvider()
        self.analytics = MockAnalyticsProvider()

    # ── Creation ──────────────────────────────────────────────────────────

    def create(
        self,
        *,
        objective: str,
        site: str,
        page: str,
        queries: Sequence[str],
        target_metric: str = "aeo_citation_rate",
        content_root: str | Path,
        publish_root: str | Path | None = None,
        variant_scenario: str = "improved",
        min_lift: float = 0.05,
        agent_mode: str | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        objective = str(objective or "").strip()
        site = str(site or "").strip()
        page = str(page or "").strip()
        target_metric = str(target_metric or "").strip()
        if not objective:
            raise SupervisorError("objective is required")
        if not site:
            raise SupervisorError("site is required")
        if not page:
            raise SupervisorError("page is required")
        if not target_metric:
            raise SupervisorError("target_metric is required")
        mode = (agent_mode or self.agent_mode or "rule").strip().lower()
        if mode not in {"rule", "llm"}:
            raise SupervisorError("agent_mode must be rule or llm")

        content_root = Path(content_root).expanduser().resolve()
        publish_root = (
            Path(publish_root).expanduser().resolve()
            if publish_root
            else (content_root.parent / "published").resolve()
        )
        content = ContentStore(content_root)
        if not content.exists(page):
            raise SupervisorError(f"page does not exist in content root: {page}")

        query_list = [query.strip() for query in queries if query.strip()]
        if not query_list:
            raise SupervisorError("at least one query is required")

        baseline_content = content.read(page)
        baseline_report = self.provider.measure(
            baseline_content, query_list, scenario="baseline"
        )
        experiment = self.store.create(
            objective=objective,
            site=site,
            page=page,
            queries=query_list,
            target_metric=target_metric,
            baseline={
                "page_content": baseline_content,
                "citation_rate": baseline_report.citation_rate,
                "content_hash": baseline_report.content_hash,
            },
            config={
                "content_root": str(content_root),
                "publish_root": str(publish_root),
                "variant_scenario": variant_scenario,
                "min_lift": float(min_lift),
                "agent_mode": mode,
                "baseline_snapshot": content.snapshot(),
            },
            budget={**DEFAULT_BUDGET, **(budget or {})},
        )
        experiment_id = experiment["id"]
        artifact_dir = self._artifact_dir(experiment)
        _write_json(artifact_dir / "baseline.json", baseline_report.to_dict())
        self.store.add_metric(
            experiment_id,
            name=target_metric,
            value=baseline_report.citation_rate,
            unit="ratio",
            source="mock-aeo",
            scenario="baseline",
            raw=baseline_report.to_dict(),
        )
        self.store.add_step(
            experiment_id,
            state="DRAFT",
            role="supervisor",
            status="done",
            output_data={"baseline": baseline_report.to_dict()},
        )
        return self.advance(experiment_id)

    # ── Main state machine ────────────────────────────────────────────────

    def advance(self, experiment_id: str, *, max_transitions: int = 12) -> dict[str, Any]:
        for _ in range(max_transitions):
            experiment = self.store.get(experiment_id)
            state = experiment["state"]
            if state in TERMINAL_STATES:
                break
            if state == "PENDING_APPROVAL":
                approval_id = experiment.get("approval_id") or ""
                if not approval_id:
                    break
                try:
                    approval = self.approvals.get(approval_id)
                except KeyError:
                    break
                if approval["status"] == "approved":
                    self.store.set_state(experiment_id, "APPROVED")
                    continue
                if approval["status"] in {"rejected", "expired"}:
                    reason = f"approval {approval['status']}"
                    self.store.set_state(
                        experiment_id,
                        "FAILED",
                        status="failed",
                        error=reason,
                    )
                    self.store.add_step(
                        experiment_id,
                        state="FAILED",
                        role="approval",
                        status=approval["status"],
                        output_data={"approval_id": approval_id},
                    )
                break
            self._check_budget(experiment)
            if state not in READY_STATES:
                raise SupervisorError(f"unknown experiment state: {state}")
            if state == "DRAFT":
                self._hypothesize(experiment)
            elif state == "HYPOTHESIZED":
                self._request_approval(experiment)
            elif state == "APPROVED":
                self._execute(experiment)
            elif state == "OBSERVING":
                self._observe(experiment)
            elif state == "EVALUATING":
                self._evaluate(experiment)
            elif state == "LEARNING":
                self._learn(experiment)
                break
        return self.store.detail(experiment_id)

    def resume(self, experiment_id: str) -> dict[str, Any]:
        return self.advance(experiment_id)

    def approve(
        self, experiment_id: str, *, message: str = "", resolved_by: str = "dashboard"
    ) -> dict[str, Any]:
        experiment = self.store.get(experiment_id)
        if experiment["state"] != "PENDING_APPROVAL":
            raise SupervisorError(
                f"experiment is not awaiting approval: {experiment['state']}"
            )
        approval_id = experiment.get("approval_id") or ""
        if not approval_id:
            raise SupervisorError("experiment has no pending approval id")
        self.approvals.resolve(
            approval_id,
            decision="approve",
            message=message,
            resolved_by=resolved_by,
        )
        self.store.set_state(experiment_id, "APPROVED")
        self.store.add_step(
            experiment_id,
            state="APPROVED",
            role="human",
            status="approved",
            output_data={"approval_id": approval_id, "message": message},
        )
        return self.advance(experiment_id)

    def reject(
        self, experiment_id: str, *, message: str = "", resolved_by: str = "dashboard"
    ) -> dict[str, Any]:
        experiment = self.store.get(experiment_id)
        if experiment["state"] != "PENDING_APPROVAL":
            raise SupervisorError(
                f"experiment is not awaiting approval: {experiment['state']}"
            )
        approval_id = experiment.get("approval_id") or ""
        if not approval_id:
            raise SupervisorError("experiment has no pending approval id")
        self.approvals.resolve(
            approval_id,
            decision="reject",
            message=message,
            resolved_by=resolved_by,
        )
        self.store.set_state(
            experiment_id,
            "FAILED",
            status="failed",
            error=f"rejected: {message}" if message else "rejected",
        )
        self.store.add_step(
            experiment_id,
            state="FAILED",
            role="human",
            status="rejected",
            output_data={"approval_id": approval_id, "message": message},
        )
        return self.store.detail(experiment_id)

    # ── States ────────────────────────────────────────────────────────────

    def _hypothesize(self, experiment: dict[str, Any]) -> None:
        experiment_id = experiment["id"]
        public_hypothesis = experiment.get("hypothesis") or {}
        if public_hypothesis:
            self.store.set_state(experiment_id, "HYPOTHESIZED")
            return

        started = now_iso()
        config = experiment["config"]
        proposal = self._propose_content(experiment)
        hypothesis = {
            "statement": (
                f"Adding a direct-answer section and FAQ to {experiment['page']} "
                f"will improve {experiment['target_metric']} for the selected query set."
            ),
            "rationale": (
                "Answer-first passages and explicit question coverage improve "
                "extractability for answer engines."
            ),
            "change_plan": [
                "Add a concise direct-answer section.",
                "Add FAQ entries for the highest-value queries.",
                "Preserve existing headings and substantive content.",
            ],
            "expected_lift": float(config.get("min_lift", 0.05)),
            "risk": "low",
            "agent_mode": config.get("agent_mode", "rule"),
            "proposal": {
                "summary": proposal.get("summary", ""),
                "changed_paths": proposal.get("changed_paths", []),
                "changes": proposal.get("changes", {}),
                "diff": proposal.get("diff", ""),
                "run_id": proposal.get("run_id", ""),
            },
        }
        artifact_dir = self._artifact_dir(experiment)
        _write_json(artifact_dir / "hypothesis.json", hypothesis)
        _write_text(artifact_dir / "proposal.diff", proposal.get("diff", ""))
        self.store.update(experiment_id, hypothesis=hypothesis)
        self.store.set_state(experiment_id, "HYPOTHESIZED")
        self.store.add_step(
            experiment_id,
            state="HYPOTHESIZED",
            role="hypothesis",
            status="done",
            input_data={"objective": experiment["objective"]},
            output_data=hypothesis,
            run_id=proposal.get("run_id") or None,
            cost={"agent_mode": config.get("agent_mode", "rule")},
            started_at=started,
            ended_at=now_iso(),
        )

    def _request_approval(self, experiment: dict[str, Any]) -> None:
        experiment_id = experiment["id"]
        hypothesis = experiment.get("hypothesis") or {}
        proposal = hypothesis.get("proposal") or {}
        config = experiment["config"]
        payload = {
            "experiment_id": experiment_id,
            "objective": experiment["objective"],
            "site": experiment["site"],
            "page": experiment["page"],
            "queries": experiment["queries"],
            "target_metric": experiment["target_metric"],
            "hypothesis": hypothesis.get("statement", ""),
            "rationale": hypothesis.get("rationale", ""),
            "proposal_summary": proposal.get("summary", ""),
            "changed_paths": proposal.get("changed_paths", []),
            "diff": proposal.get("diff", ""),
            "expected_metric": {
                "name": experiment["target_metric"],
                "baseline": (experiment.get("baseline") or {}).get("citation_rate"),
                "min_lift": config.get("min_lift", 0.05),
            },
            "budget": experiment.get("budget") or {},
            "rollback": (
                "Baseline content and sandbox publish snapshots are stored. "
                "Rejecting leaves the content workspace untouched."
            ),
        }
        approval = self.approvals.request(
            experiment_id=experiment_id,
            action="execute_content_experiment",
            payload=payload,
            metadata={"page": experiment["page"], "site": experiment["site"]},
        )
        self.store.update(experiment_id, approval_id=approval["id"])
        self.store.set_state(experiment_id, "PENDING_APPROVAL")
        self.store.add_step(
            experiment_id,
            state="PENDING_APPROVAL",
            role="supervisor",
            status="pending",
            output_data={"approval_id": approval["id"]},
        )

    def _execute(self, experiment: dict[str, Any]) -> None:
        experiment_id = experiment["id"]
        config = experiment["config"]
        hypothesis = experiment.get("hypothesis") or {}
        proposal = hypothesis.get("proposal") or {}
        before = (experiment.get("baseline") or {}).get("page_content", "")
        after = self._page_after_proposal(experiment, proposal)
        verification = self._verify(before, after)
        artifact_dir = self._artifact_dir(experiment)
        _write_json(artifact_dir / "verification.json", verification)
        if not verification["ok"]:
            self.store.update(
                experiment_id,
                result={
                    "verification": verification,
                    "decision": "invalid",
                    "reason": "content verification failed",
                },
            )
            self.store.set_state(
                experiment_id,
                "FAILED",
                status="failed",
                error="content verification failed",
            )
            self.store.add_step(
                experiment_id,
                state="FAILED",
                role="verifier",
                status="failed",
                output_data=verification,
            )
            return

        content = ContentStore(config["content_root"])
        changes = content.apply_changes({experiment["page"]: after})
        publisher = SandboxPublisher(config["content_root"], config["publish_root"])
        publish_before = publisher.snapshot()
        publish_result = publisher.publish([experiment["page"]])
        _write_json(artifact_dir / "publish.json", publish_result)
        self.store.update(
            experiment_id,
            result={
                "verification": verification,
                "changes": [change.to_dict() for change in changes],
                "publish": publish_result,
                "publish_before": publish_before,
            },
        )
        self.store.set_state(experiment_id, "OBSERVING")
        self.store.add_step(
            experiment_id,
            state="OBSERVING",
            role="content",
            status="done",
            input_data={"changed_paths": [experiment["page"]]},
            output_data={
                "verification": verification,
                "publish": publish_result,
                "changed_files": [change.path for change in changes],
            },
        )

    def _observe(self, experiment: dict[str, Any]) -> None:
        experiment_id = experiment["id"]
        config = experiment["config"]
        content = ContentStore(config["content_root"]).read(experiment["page"])
        scenario = config.get("variant_scenario", "improved")
        report = self.provider.measure(content, experiment["queries"], scenario=scenario)
        analytics = self.analytics.measure(content, scenario=scenario)
        artifact_dir = self._artifact_dir(experiment)
        _write_json(artifact_dir / "observation.json", {
            "aeo": report.to_dict(),
            "analytics": analytics,
        })
        self.store.add_metric(
            experiment_id,
            name=experiment["target_metric"],
            value=report.citation_rate,
            unit="ratio",
            source="mock-aeo",
            scenario=scenario,
            raw=report.to_dict(),
        )
        self.store.add_metric(
            experiment_id,
            name="page_views",
            value=analytics["page_views"],
            unit="count",
            source="mock-analytics",
            scenario=scenario,
            raw=analytics,
        )
        result = dict(experiment.get("result") or {})
        result["observation"] = {"aeo": report.to_dict(), "analytics": analytics}
        self.store.update(experiment_id, result=result)
        self.store.set_state(experiment_id, "EVALUATING")
        self.store.add_step(
            experiment_id,
            state="EVALUATING",
            role="observer",
            status="done",
            output_data={"aeo": report.to_dict(), "analytics": analytics},
        )

    def _evaluate(self, experiment: dict[str, Any]) -> None:
        experiment_id = experiment["id"]
        config = experiment["config"]
        result = dict(experiment.get("result") or {})
        verification = result.get("verification") or {}
        baseline = float((experiment.get("baseline") or {}).get("citation_rate") or 0.0)
        observation = result.get("observation") or {}
        aeo = observation.get("aeo") or {}
        variant = aeo.get("citation_rate")
        min_lift = float(config.get("min_lift", 0.05))

        if not verification.get("ok", False):
            decision = "invalid"
            reason = "content verification failed"
            delta = None
        elif variant is None:
            decision = "invalid"
            reason = "AEO measurement was invalid"
            delta = None
        else:
            delta = float(variant) - baseline
            if delta >= min_lift:
                decision = "win"
                reason = f"citation rate improved by {delta:.3f}"
            elif delta <= -min_lift:
                decision = "loss"
                reason = f"citation rate regressed by {delta:.3f}"
            else:
                decision = "inconclusive"
                reason = f"citation rate changed by {delta:.3f}, below threshold"

        evaluation = {
            "decision": decision,
            "reason": reason,
            "baseline": baseline,
            "variant": variant,
            "delta": delta,
            "min_lift": min_lift,
            "guardrails": verification,
        }
        result["evaluation"] = evaluation
        result["decision"] = decision
        artifact_dir = self._artifact_dir(experiment)
        _write_json(artifact_dir / "evaluation.json", evaluation)

        if decision in {"loss", "invalid"}:
            self._rollback(experiment, result)
            self.store.update(experiment_id, result=result, decision=decision)
            self.store.set_state(
                experiment_id,
                "ROLLED_BACK",
                status="failed",
                error=reason,
            )
            self.store.add_step(
                experiment_id,
                state="ROLLED_BACK",
                role="evaluator",
                status="rolled_back",
                output_data=evaluation,
            )
            return

        self.store.update(experiment_id, result=result, decision=decision)
        self.store.set_state(experiment_id, "LEARNING")
        self.store.add_step(
            experiment_id,
            state="LEARNING",
            role="evaluator",
            status="done",
            output_data=evaluation,
        )

    def _learn(self, experiment: dict[str, Any]) -> None:
        experiment_id = experiment["id"]
        result = experiment.get("result") or {}
        evaluation = result.get("evaluation") or {}
        decision = result.get("decision") or "inconclusive"
        lesson = (
            f"{decision}: {experiment.get('hypothesis', {}).get('statement', '')} "
            f"Baseline={evaluation.get('baseline')}, variant={evaluation.get('variant')}, "
            f"delta={evaluation.get('delta')}. {evaluation.get('reason', '')}"
        )
        confidence = 0.8 if decision in {"win", "loss"} else 0.4
        self.store.add_lesson(
            experiment_id,
            lesson=lesson,
            confidence=confidence,
            tags=[experiment["site"], experiment["page"], decision],
        )
        artifact_dir = self._artifact_dir(experiment)
        _write_text(artifact_dir / "lesson.txt", lesson + "\n")
        self.store.set_state(experiment_id, "COMPLETED", status="completed")
        self.store.add_step(
            experiment_id,
            state="COMPLETED",
            role="memory",
            status="done",
            output_data={"lesson": lesson, "confidence": confidence},
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def _propose_content(self, experiment: dict[str, Any]) -> dict[str, Any]:
        config = experiment["config"]
        if config.get("agent_mode") == "llm":
            return self._llm_proposal(experiment)
        return self._rule_proposal(experiment)

    def _rule_proposal(self, experiment: dict[str, Any]) -> dict[str, Any]:
        content = ContentStore(experiment["config"]["content_root"])
        before = content.read(experiment["page"])
        queries = experiment["queries"]
        topic = queries[0] if queries else Path(experiment["page"]).stem
        after = before.rstrip() + "\n"
        if "## Direct Answer" not in after:
            section = (
                "## Direct Answer\n\n"
                f"{topic[:1].upper() + topic[1:]} is addressed directly below so "
                "answer engines can extract a concise response.\n\n"
            )
            lines = after.splitlines()
            insert_at = 1 if lines and lines[0].startswith("# ") else 0
            lines[insert_at:insert_at] = section.splitlines()
            after = "\n".join(lines).rstrip() + "\n"
        if "## FAQ" not in after:
            faq = ["## FAQ", ""]
            for query in queries[:3]:
                faq.extend([f"### {query}", "", f"Short answer for: {query}.", ""])
            after = after.rstrip() + "\n\n" + "\n".join(faq)
        if after == before:
            after = before.rstrip() + "\n\n## Key Takeaways\n\n- Keep answers direct.\n"
        diff = ContentStore.diff_text(experiment["page"], before, after)
        return {
            "changes": {experiment["page"]: after},
            "changed_paths": [experiment["page"]],
            "diff": diff,
            "summary": "Added a direct-answer section and FAQ coverage.",
            "run_id": "",
        }

    def _llm_proposal(self, experiment: dict[str, Any]) -> dict[str, Any]:
        from coding_agent import run_task

        config = experiment["config"]
        source_root = Path(config["content_root"])
        with tempfile.TemporaryDirectory(prefix="aeo-proposal-") as temporary:
            staging = Path(temporary) / "content"
            shutil.copytree(source_root, staging)
            prompt = (
                "You are an AEO content editor. Edit only the target Markdown page. "
                "Add a concise direct-answer section and an FAQ for the provided queries. "
                "Preserve all existing headings and substantive content. Do not add "
                "unsupported claims, placeholders, or TODO markers.\n\n"
                f"Target page: {experiment['page']}\n"
                f"Queries: {', '.join(experiment['queries'])}\n"
                f"Objective: {experiment['objective']}\n"
            )
            result = run_task(
                prompt,
                workspace=staging,
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
                max_steps=8,
                timeout=600,
            )
            staged = ContentStore(staging)
            after = staged.read(experiment["page"])
            before = ContentStore(source_root).read(experiment["page"])
            diff = ContentStore.diff_text(experiment["page"], before, after)
            return {
                "changes": {experiment["page"]: after},
                "changed_paths": [experiment["page"]],
                "diff": diff,
                "summary": "LLM content agent proposed a direct-answer and FAQ update.",
                "run_id": getattr(result, "run_id", ""),
            }

    def _page_after_proposal(
        self, experiment: dict[str, Any], proposal: dict[str, Any]
    ) -> str:
        changes = proposal.get("changes") or {}
        if experiment["page"] in changes:
            return str(changes[experiment["page"]])
        # The stored hypothesis only keeps a diff; recompute the deterministic
        # proposal if the process resumed before the changes were persisted.
        return str(self._rule_proposal(experiment)["changes"][experiment["page"]])

    def _verify(self, before: str, after: str) -> dict[str, Any]:
        issues: list[str] = []
        if not after.strip():
            issues.append("content is empty")
        if len(after.split()) < len(before.split()):
            issues.append("content shrank")
        lowered = after.lower()
        if "placeholder" in lowered:
            issues.append("content contains placeholder text")
        if "todo" in lowered:
            issues.append("content contains TODO text")
        before_headings = [
            line.strip() for line in before.splitlines() if line.strip().startswith("#")
        ]
        after_headings = {
            line.strip() for line in after.splitlines() if line.strip().startswith("#")
        }
        missing = [heading for heading in before_headings if heading not in after_headings]
        if missing:
            issues.append("existing headings removed: " + ", ".join(missing))
        return {
            "ok": not issues,
            "issues": issues,
            "checks": {
                "word_count_before": len(before.split()),
                "word_count_after": len(after.split()),
                "headings_before": len(before_headings),
                "headings_after": len(after_headings),
            },
        }

    def _rollback(self, experiment: dict[str, Any], result: dict[str, Any]) -> None:
        config = experiment["config"]
        baseline_snapshot = config.get("baseline_snapshot") or {}
        if baseline_snapshot:
            ContentStore(config["content_root"]).rollback(baseline_snapshot)
        publish_before = result.get("publish_before")
        if publish_before is not None:
            SandboxPublisher(config["content_root"], config["publish_root"]).rollback(
                publish_before
            )
        result["rolled_back"] = True

    def _check_budget(self, experiment: dict[str, Any]) -> None:
        budget = experiment.get("budget") or {}
        max_steps = int(budget.get("max_steps", DEFAULT_BUDGET["max_steps"]))
        steps = self.store.steps(experiment["id"], limit=max_steps + 1)
        if len(steps) >= max_steps:
            self.store.set_state(
                experiment["id"],
                "FAILED",
                status="failed",
                error=f"step budget exceeded (max_steps={max_steps})",
            )
            raise BudgetExceeded(f"step budget exceeded (max_steps={max_steps})")

    def _artifact_dir(self, experiment: dict[str, Any]) -> Path:
        configured = (experiment.get("config") or {}).get("artifact_dir")
        path = Path(configured) if configured else self.artifact_root / experiment["id"]
        path.mkdir(parents=True, exist_ok=True)
        return path


def _print_experiment(experiment: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(experiment, indent=2, ensure_ascii=False, default=str))
        return
    print(f"{experiment['id']}  {experiment['state']:<16} {experiment['status']:<9} {experiment['page']}")
    print(f"  objective: {experiment['objective']}")
    if experiment.get("decision"):
        print(f"  decision: {experiment['decision']}")
    if experiment.get("approval_id"):
        print(f"  approval: {experiment['approval_id']}")
    if experiment.get("error"):
        print(f"  error: {experiment['error']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic AEO experiment supervisor.",
        allow_abbrev=False,
    )
    parser.add_argument("--db", type=Path, default=None, help="experiment SQLite path")
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    parser.add_argument("--agent-mode", choices=["rule", "llm"], default="rule")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--json", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", allow_abbrev=False)
    start.add_argument("--objective", required=True)
    start.add_argument("--site", required=True)
    start.add_argument("--page", required=True)
    start.add_argument("--queries", required=True, help="comma-separated query set")
    start.add_argument("--target-metric", default="aeo_citation_rate")
    start.add_argument("--content-root", required=True, type=Path)
    start.add_argument("--publish-root", type=Path, default=None)
    start.add_argument("--scenario", default="improved")
    start.add_argument("--min-lift", type=float, default=0.05)
    start.add_argument("--max-steps", type=int, default=DEFAULT_BUDGET["max_steps"])

    for name in ("status", "resume"):
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("experiment_id")

    for name in ("approve", "reject"):
        command = sub.add_parser(name, allow_abbrev=False)
        command.add_argument("experiment_id")
        command.add_argument("--message", default="")
        command.add_argument("--resolved-by", default="cli")

    sub.add_parser("list", allow_abbrev=False).add_argument("--limit", type=int, default=50)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    supervisor = Supervisor(
        db_path=args.db,
        artifact_root=args.artifacts_dir,
        agent_mode=args.agent_mode,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
    )
    try:
        if args.command == "start":
            queries = [query.strip() for query in args.queries.split(",") if query.strip()]
            budget = {"max_steps": max(1, int(args.max_steps))}
            experiment = supervisor.create(
                objective=args.objective,
                site=args.site,
                page=args.page,
                queries=queries,
                target_metric=args.target_metric,
                content_root=args.content_root,
                publish_root=args.publish_root,
                variant_scenario=args.scenario,
                min_lift=args.min_lift,
                agent_mode=args.agent_mode,
                budget=budget,
            )
            _print_experiment(experiment, args.json)
        elif args.command == "list":
            experiments = supervisor.store.list(limit=args.limit)
            if args.json:
                print(json.dumps(experiments, indent=2, ensure_ascii=False, default=str))
            else:
                for experiment in experiments:
                    _print_experiment(experiment, False)
        elif args.command == "status":
            _print_experiment(supervisor.store.detail(args.experiment_id), args.json)
        elif args.command == "resume":
            _print_experiment(supervisor.resume(args.experiment_id), args.json)
        elif args.command == "approve":
            _print_experiment(
                supervisor.approve(
                    args.experiment_id,
                    message=args.message,
                    resolved_by=args.resolved_by,
                ),
                args.json,
            )
        elif args.command == "reject":
            _print_experiment(
                supervisor.reject(
                    args.experiment_id,
                    message=args.message,
                    resolved_by=args.resolved_by,
                ),
                args.json,
            )
    except (SupervisorError, KeyError, ValueError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
