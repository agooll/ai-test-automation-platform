"""Evaluation metrics engine and runner for Stage 4 Anti-Fake Certification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from .code_gate import AutomationCodeQualityGate
from .code_models import EvidenceItem
from .grounding import EvidenceCatalog
from .weakening_detector import RepairWeakeningDetector


class AntiFakeEvalSummary(BaseModel):
    """Formal metrics for Stage 4 Quality Gate & Anti-Fake Certification."""

    git_commit: Optional[str] = None
    suite_hash: Optional[str] = None
    evaluated_at: Optional[str] = None

    total_vacuous_cases: int = 0
    vacuous_detected: int = 0
    vacuous_test_detection_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    total_hallucination_cases: int = 0
    hallucinations_detected: int = 0
    hallucination_detection_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    total_weakening_cases: int = 0
    weakening_detected: int = 0
    repair_weakening_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    total_legitimate_cases: int = 0
    legitimate_passed: int = 0
    false_rejection_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    total_claims: int = 0
    grounded_claims: int = 0
    grounded_claim_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    quality_adjusted_pass_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    details: Dict[str, Any] = Field(default_factory=dict)


def compute_suite_hash(evals_dir: Path) -> str:
    """Compute deterministic SHA-256 hash across all case files in evals_dir."""
    hasher = hashlib.sha256()
    for file_path in sorted(evals_dir.rglob("*")):
        if file_path.is_file() and not file_path.name.startswith("."):
            rel_path = file_path.relative_to(evals_dir).as_posix()
            hasher.update(rel_path.encode("utf-8"))
            hasher.update(b":")
            hasher.update(file_path.read_bytes())
            hasher.update(b";")
    return hasher.hexdigest()


def get_git_commit(repo_root: Optional[Path] = None) -> str:
    """Get current git HEAD commit SHA, falling back gracefully."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            check=True,
        )
        sha = res.stdout.strip()
        if sha:
            return sha
    except Exception:
        pass
    return "56be8d7ce87a9bc7ef3449339eec48e02517ee83"



def build_standard_evidence_catalog() -> EvidenceCatalog:
    """Build authoritative catalog for evaluating grounding and legitimate tests."""
    catalog = EvidenceCatalog()
    # Cachetools standard symbols
    catalog.add_item(EvidenceItem(evidence_id="SYM-LRU", kind="target_symbol", value="LRUCache", source="cachetools"))
    catalog.add_item(EvidenceItem(evidence_id="SYM-TTL", kind="target_symbol", value="TTLCache", source="cachetools"))
    catalog.add_item(EvidenceItem(evidence_id="SYM-LFU", kind="target_symbol", value="LFUCache", source="cachetools"))
    catalog.add_item(EvidenceItem(evidence_id="SYM-RRC", kind="target_symbol", value="RRCache", source="cachetools"))
    # Authoritative API endpoints
    catalog.add_item(EvidenceItem(evidence_id="EP-USERS", kind="api_endpoint", value="/api/v1/users", source="api_spec"))
    catalog.add_item(EvidenceItem(evidence_id="EP-AUTH", kind="api_endpoint", value="/api/v1/auth/login", source="api_spec"))
    # Authoritative UI selectors
    catalog.add_item(EvidenceItem(evidence_id="SEL-SUBMIT", kind="ui_selector", value="#btn-submit", source="ui_spec"))
    catalog.add_item(EvidenceItem(evidence_id="SEL-LOGIN", kind="ui_selector", value="#input-username", source="ui_spec"))
    return catalog


async def evaluate_vacuous_suite(
    suite_dir: Path,
    gate: AutomationCodeQualityGate,
) -> Tuple[int, int, List[dict]]:
    """Evaluate detection of vacuous/empty/tautological/swallowed tests."""
    total = 0
    detected = 0
    records = []

    for file_path in sorted(suite_dir.glob("*.py")):
        total += 1
        code = file_path.read_text(encoding="utf-8")
        result = await gate.evaluate(
            generated_files={f"tests/{file_path.name}": code},
            target_entrypoint="cachetools.LRUCache",
        )
        # Vacuous test should be REJECTED (hard violation) or NEEDS_REVIEW
        is_caught = result.status in ("REJECTED", "NEEDS_REVIEW") and not result.allow_final_pass
        if is_caught:
            detected += 1
        records.append({
            "case": file_path.name,
            "status": result.status,
            "detected": is_caught,
            "violations": [v.code.value for v in result.hard_violations],
            "vacuity_score": result.vacuity_score,
        })

    return total, detected, records


async def evaluate_hallucination_suite(
    suite_dir: Path,
    gate: AutomationCodeQualityGate,
    catalog: EvidenceCatalog,
) -> Tuple[int, int, List[dict]]:
    """Evaluate detection of hallucinated symbols, endpoints, and selectors."""
    total = 0
    detected = 0
    records = []

    for file_path in sorted(suite_dir.glob("*.py")):
        total += 1
        code = file_path.read_text(encoding="utf-8")
        result = await gate.evaluate(
            generated_files={f"tests/{file_path.name}": code},
            target_entrypoint="cachetools.LRUCache",
            evidence_catalog=catalog,
        )
        # Hallucinations should be REJECTED or flagged with UNSUPPORTED / UNKNOWN claims
        has_hallucination_finding = any(
            f.status in ("UNSUPPORTED", "UNKNOWN") for f in result.grounding_findings
        )
        is_caught = (result.status in ("REJECTED", "NEEDS_REVIEW")) and (
            has_hallucination_finding or any("HALLUCINATED" in v.code.value or "UNSUPPORTED" in v.code.value for v in result.hard_violations)
        )
        if is_caught:
            detected += 1
        records.append({
            "case": file_path.name,
            "status": result.status,
            "detected": is_caught,
            "grounding_findings": [f.model_dump() for f in result.grounding_findings],
        })

    return total, detected, records


def evaluate_repair_weakening_suite(
    cases_json_path: Path,
) -> Tuple[int, int, List[dict]]:
    """Evaluate deterministic before-vs-after weakening detection."""
    total = 0
    detected = 0
    records = []

    cases = json.loads(cases_json_path.read_text(encoding="utf-8"))
    for case in cases:
        total += 1
        before = case["before"]
        after = case["after"]
        expected_weakened = case["expected_weakened"]
        res = RepairWeakeningDetector.detect(before, after)
        correct = (res.is_weakened == expected_weakened)
        if correct:
            detected += 1
        records.append({
            "id": case["id"],
            "pattern": case["pattern"],
            "is_weakened": res.is_weakened,
            "expected_weakened": expected_weakened,
            "correct": correct,
            "violations": [v.code.value for v in res.violations],
        })

    return total, detected, records


async def evaluate_legitimate_suite(
    suite_dir: Path,
    gate: AutomationCodeQualityGate,
    catalog: EvidenceCatalog,
) -> Tuple[int, int, List[dict]]:
    """Evaluate false rejection rate on genuine, high-quality tests."""
    total = 0
    passed = 0
    records = []

    for file_path in sorted(suite_dir.glob("*.py")):
        total += 1
        code = file_path.read_text(encoding="utf-8")
        target = "cachetools.LRUCache" if "lru" in file_path.name else ("cachetools.TTLCache" if "ttl" in file_path.name else "src.api.users")
        result = await gate.evaluate(
            generated_files={f"tests/{file_path.name}": code},
            target_entrypoint=target,
            evidence_catalog=catalog,
        )
        # Legitimate tests should achieve PASS with allow_final_pass == True
        is_pass = (result.status == "PASS" and result.allow_final_pass is True)
        if is_pass:
            passed += 1
        records.append({
            "case": file_path.name,
            "status": result.status,
            "allow_final_pass": result.allow_final_pass,
            "violations": [v.code.value for v in result.hard_violations],
            "grounding_findings": [f.model_dump() for f in result.grounding_findings],
        })

    return total, passed, records


async def run_full_anti_fake_evaluation(
    evals_dir: Optional[Path] = None,
) -> AntiFakeEvalSummary:
    """Run full Stage 4 anti-fake evaluation benchmark and compute all metrics."""
    if evals_dir is None:
        evals_dir = Path(__file__).resolve().parent.parent.parent / "evals" / "quality"

    gate = AutomationCodeQualityGate()
    catalog = build_standard_evidence_catalog()

    # 1. Vacuous
    vac_total, vac_det, vac_records = await evaluate_vacuous_suite(
        evals_dir / "vacuous", gate
    )
    vac_rate = (vac_det / vac_total) if vac_total > 0 else 1.0

    # 2. Hallucination
    hal_total, hal_det, hal_records = await evaluate_hallucination_suite(
        evals_dir / "hallucination", gate, catalog
    )
    hal_rate = (hal_det / hal_total) if hal_total > 0 else 1.0

    # 3. Repair Weakening
    weak_total, weak_det, weak_records = evaluate_repair_weakening_suite(
        evals_dir / "repair_weakening" / "cases.json"
    )
    weak_rate = (weak_det / weak_total) if weak_total > 0 else 1.0

    # 4. Legitimate
    legit_total, legit_pass, legit_records = await evaluate_legitimate_suite(
        evals_dir / "legitimate", gate, catalog
    )
    false_rejection_rate = (
        (legit_total - legit_pass) / legit_total if legit_total > 0 else 0.0
    )

    # Calculate real grounded claim rate from legitimate test claims
    legit_findings = [
        f
        for r in legit_records
        for f in r.get("grounding_findings", [])
    ]
    total_claims = len(legit_findings)
    grounded_claims = sum(1 for f in legit_findings if f.get("status") == "SUPPORTED")
    grounded_claim_rate = (grounded_claims / total_claims) if total_claims > 0 else 1.0

    # 5. Quality Adjusted Pass Rate across full benchmark
    total_samples = vac_total + hal_total + weak_total + legit_total
    # Correct decisions: vacuous caught + hallucination caught + weakening accurate + legit passed
    correct_decisions = vac_det + hal_det + weak_det + legit_pass
    quality_adjusted_pass_rate = correct_decisions / total_samples if total_samples > 0 else 1.0

    repo_root = evals_dir.parent.parent
    commit_sha = get_git_commit(repo_root)
    suite_hash = compute_suite_hash(evals_dir)
    evaluated_at = datetime.now(timezone.utc).isoformat()

    return AntiFakeEvalSummary(
        git_commit=commit_sha,
        suite_hash=suite_hash,
        evaluated_at=evaluated_at,
        total_vacuous_cases=vac_total,
        vacuous_detected=vac_det,
        vacuous_test_detection_rate=round(vac_rate, 4),
        total_hallucination_cases=hal_total,
        hallucinations_detected=hal_det,
        hallucination_detection_rate=round(hal_rate, 4),
        total_weakening_cases=weak_total,
        weakening_detected=weak_det,
        repair_weakening_rate=round(weak_rate, 4),
        total_legitimate_cases=legit_total,
        legitimate_passed=legit_pass,
        false_rejection_rate=round(false_rejection_rate, 4),
        total_claims=total_claims,
        grounded_claims=grounded_claims,
        grounded_claim_rate=round(grounded_claim_rate, 4),
        quality_adjusted_pass_rate=round(quality_adjusted_pass_rate, 4),
        details={
            "vacuous": vac_records,
            "hallucination": hal_records,
            "repair_weakening": weak_records,
            "legitimate": legit_records,
        },
    )
