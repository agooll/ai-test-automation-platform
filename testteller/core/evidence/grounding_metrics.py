"""Formal metric computation for Stage 5 RAG Grounding and Traceability (Stage 5.8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GroundingBenchmarkScenarioResult:
    scenario_name: str
    category: str
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundingMetricsReport:
    """Formal metrics for Stage 5 RAG Grounding & Evidence Traceability certification."""
    evidence_provenance_completeness: float
    exact_fact_hit_rate: float
    grounded_claim_rate: float
    citation_accuracy: float
    unsupported_fact_detection_rate: float
    conflict_detection_rate: float
    unknown_false_acceptance_rate: float
    stale_evidence_false_selection_rate: float
    repair_expectation_without_evidence_count: int

    total_scenarios: int
    passed_scenarios: int
    all_thresholds_met: bool
    scenario_results: List[GroundingBenchmarkScenarioResult] = field(default_factory=list)


class GroundingMetricsCalculator:
    """Calculates formal certification metrics against Stage 5 acceptance thresholds."""

    # Stage 5 Hard Thresholds
    THRESHOLDS = {
        "evidence_provenance_completeness": 1.00,  # 100%
        "exact_fact_hit_rate": 0.98,               # >= 98%
        "grounded_claim_rate": 0.95,               # >= 95%
        "citation_accuracy": 0.95,                 # >= 95%
        "unsupported_fact_detection_rate": 0.95,   # >= 95%
        "conflict_detection_rate": 1.00,           # 100%
        "unknown_false_acceptance_rate": 0.00,     # 0%
        "stale_evidence_false_selection_rate": 0.00,  # 0%
        "repair_expectation_without_evidence_count": 0,  # 0 allowed
    }

    @classmethod
    def compute_metrics(
        cls,
        scenario_results: List[GroundingBenchmarkScenarioResult],
    ) -> GroundingMetricsReport:
        cat_map: Dict[str, List[GroundingBenchmarkScenarioResult]] = {}
        for r in scenario_results:
            cat_map.setdefault(r.category, []).append(r)

        def pass_rate(category: str) -> float:
            items = cat_map.get(category, [])
            if not items:
                return 1.0
            return round(sum(1 for i in items if i.passed) / len(items), 4)

        prov_comp = pass_rate("provenance_completeness")
        exact_hit = pass_rate("exact_lookup")
        grounded_claim = pass_rate("grounded_claim")
        citation_acc = pass_rate("citation_accuracy")
        unsupp_det = pass_rate("unsupported_detection")
        conflict_det = pass_rate("conflict_detection")

        # Inverted rates (0.0 is perfect)
        unknown_false_acc = 1.0 - pass_rate("unknown_handling")
        stale_false_sel = 1.0 - pass_rate("stale_evidence")
        repair_unbacked = sum(
            r.details.get("unbacked_changes_count", 0)
            for r in cat_map.get("repair_expectation", [])
            if not r.passed
        )

        all_met = (
            prov_comp >= cls.THRESHOLDS["evidence_provenance_completeness"]
            and exact_hit >= cls.THRESHOLDS["exact_fact_hit_rate"]
            and grounded_claim >= cls.THRESHOLDS["grounded_claim_rate"]
            and citation_acc >= cls.THRESHOLDS["citation_accuracy"]
            and unsupp_det >= cls.THRESHOLDS["unsupported_fact_detection_rate"]
            and conflict_det >= cls.THRESHOLDS["conflict_detection_rate"]
            and unknown_false_acc <= cls.THRESHOLDS["unknown_false_acceptance_rate"]
            and stale_false_sel <= cls.THRESHOLDS["stale_evidence_false_selection_rate"]
            and repair_unbacked <= cls.THRESHOLDS["repair_expectation_without_evidence_count"]
        )

        total_count = len(scenario_results)
        passed_count = sum(1 for r in scenario_results if r.passed)

        return GroundingMetricsReport(
            evidence_provenance_completeness=prov_comp,
            exact_fact_hit_rate=exact_hit,
            grounded_claim_rate=grounded_claim,
            citation_accuracy=citation_acc,
            unsupported_fact_detection_rate=unsupp_det,
            conflict_detection_rate=conflict_det,
            unknown_false_acceptance_rate=unknown_false_acc,
            stale_evidence_false_selection_rate=stale_false_sel,
            repair_expectation_without_evidence_count=repair_unbacked,
            total_scenarios=total_count,
            passed_scenarios=passed_count,
            all_thresholds_met=all_met,
            scenario_results=scenario_results,
        )
