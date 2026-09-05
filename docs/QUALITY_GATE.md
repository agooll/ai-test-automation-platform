# Test Case Quality Gate

TestTeller evaluates generated test cases in three layers:

1. Pydantic/JSON Schema validates the canonical test-case contract.
2. Deterministic rules validate fields, executable steps, assertions, traceability, and requirement-level scenario coverage.
3. The AI Review Skill checks semantic clarity and automation feasibility. It cannot override hard-rule failures.

The final status is `PASS`, `REJECTED`, or `NEEDS_REVIEW`. Only `PASS` results may be stored as high-quality RAG examples or sent to the automation generator.

## CLI

```powershell
testteller quality-check .\test-cases.md
testteller quality-check .\test-cases.md --no-ai --json
```

## Web API

`POST /api/quality-check` accepts:

```json
{
  "content": "...markdown test cases...",
  "use_ai": true
}
```

The response includes the gate status, deterministic violations, coverage findings, semantic review, and storage/automation permissions.

## Required case content

Each case needs an ID, title, requirement ID, precondition, priority (`P0`-`P3`), scenario type (`normal`, `abnormal`, or `boundary`), at least one executable step, and at least one concrete assertion. Each requirement should be represented by normal, abnormal, and boundary cases unless an explicit coverage exemption is provided.
