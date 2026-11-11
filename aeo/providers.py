"""Provider interfaces and deterministic mock implementations.

The first AEO slice must run without network access.  These mocks make the
citation outcomes explicit and reproducible so the supervisor's evaluation is
testable instead of relying on an LLM's opinion.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Protocol, Sequence


@dataclass
class CitationResult:
    engine: str
    query: str
    cited: bool
    snippet: str = ""
    source_url: str = ""
    checked_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CitationReport:
    scenario: str
    content_hash: str
    total_queries: int
    cited_count: int
    citation_rate: float | None
    results: list[CitationResult] = field(default_factory=list)
    error: str = ""

    @property
    def valid(self) -> bool:
        return not self.error and self.total_queries > 0 and self.citation_rate is not None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["valid"] = self.valid
        return data


class AEOProvider(Protocol):
    def measure(
        self, content: str, queries: Sequence[str], *, scenario: str = "baseline"
    ) -> CitationReport: ...


class MockAEOProvider:
    """Deterministic citation-rate provider for local experiments.

    Scenarios:
      baseline  - 35% citation rate
      improved  - 65% citation rate
      regressed - 15% citation rate
      no_change - 35% citation rate
      invalid   - no usable measurement
    """

    RATES = {
        "baseline": 0.35,
        "improved": 0.65,
        "regressed": 0.15,
        "no_change": 0.35,
    }

    def __init__(self, engine: str = "mock-aeo"):
        self.engine = engine

    def measure(
        self, content: str, queries: Sequence[str], *, scenario: str = "baseline"
    ) -> CitationReport:
        query_list = [str(query).strip() for query in queries if str(query).strip()]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        if not query_list:
            return CitationReport(
                scenario=scenario,
                content_hash=digest,
                total_queries=0,
                cited_count=0,
                citation_rate=None,
                error="no queries provided",
            )
        if scenario == "invalid":
            return CitationReport(
                scenario=scenario,
                content_hash=digest,
                total_queries=len(query_list),
                cited_count=0,
                citation_rate=None,
                error="mock scenario marked the measurement invalid",
            )

        rate = self.RATES.get(scenario)
        if rate is None:
            return CitationReport(
                scenario=scenario,
                content_hash=digest,
                total_queries=len(query_list),
                cited_count=0,
                citation_rate=None,
                error=f"unknown mock scenario: {scenario}",
            )

        cited_count = int(round(rate * len(query_list)))
        results: list[CitationResult] = []
        for index, query in enumerate(query_list):
            cited = index < cited_count
            results.append(
                CitationResult(
                    engine=self.engine,
                    query=query,
                    cited=cited,
                    snippet=(
                        f"Mock citation for '{query}'" if cited else ""
                    ),
                    source_url=(
                        f"mock://aeo/{digest}/{index}" if cited else ""
                    ),
                    checked_at="mock-now",
                )
            )
        return CitationReport(
            scenario=scenario,
            content_hash=digest,
            total_queries=len(query_list),
            cited_count=cited_count,
            citation_rate=cited_count / len(query_list),
            results=results,
        )


class MockAnalyticsProvider:
    """Small deterministic analytics fixture used as a secondary signal."""

    def __init__(self, base_views: int = 1000):
        self.base_views = int(base_views)

    def measure(self, content: str, *, scenario: str = "baseline") -> dict:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        multipliers = {
            "baseline": 1.0,
            "no_change": 1.0,
            "improved": 1.12,
            "regressed": 0.88,
            "invalid": 0.0,
        }
        multiplier = multipliers.get(scenario, 1.0)
        return {
            "page_views": int(round(self.base_views * multiplier)),
            "avg_time_on_page_s": round(45.0 * multiplier, 1),
            "content_hash": digest,
            "scenario": scenario,
        }
