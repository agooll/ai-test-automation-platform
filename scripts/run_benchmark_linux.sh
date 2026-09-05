#!/usr/bin/env bash
# ==============================================================================
# TestTeller Stage 3 Benchmark Execution Script (Linux / CI Environment)
# ==============================================================================
set -eo pipefail

MODE="${1:-smoke}"
MODEL="${2:-gemini-2.5-pro}"

echo "================================================================================"
echo " TestTeller Stage 3 Benchmark Runner (Linux / CI)"
echo " Mode:  ${MODE}"
echo " Model: ${MODEL}"
echo " Date:  $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "================================================================================"

# 1. Environment and Prerequisite Validation
echo "==> [Check 1/3] Validating Python environment..."
if ! command -v python3 &>/dev/null; then
    echo "❌ ERROR: python3 not found in PATH."
    exit 1
fi
python3 --version

echo "==> [Check 2/3] Validating Docker daemon..."
if ! command -v docker &>/dev/null; then
    echo "❌ ERROR: docker command not found in PATH."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "❌ ERROR: Docker daemon is not running or current user lacks docker permissions."
    echo "    Try running: sudo systemctl start docker"
    echo "    Or ensure current user is in the 'docker' group: sudo usermod -aG docker \$USER"
    exit 1
fi
echo "✅ Docker daemon is active and accessible."

echo "==> [Check 3/3] Validating GOOGLE_API_KEY..."
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs -d '\n') &>/dev/null || true
fi

if [ -z "${GOOGLE_API_KEY}" ]; then
    echo "❌ ERROR: GOOGLE_API_KEY is not set."
    echo "    Please export GOOGLE_API_KEY='your-gemini-api-key' or put it in .env"
    exit 1
fi
echo "✅ GOOGLE_API_KEY is configured."

# 2. Build Docker Runner Images
echo ""
echo "================================================================================"
echo "==> [Build] Building TestTeller Pinned Runner Docker Images..."
echo "================================================================================"
python3 docker/build_runners.py
docker images | grep testteller-runner || true

# 3. Execution based on Mode
run_smoke() {
    echo ""
    echo "================================================================================"
    echo "==> [Step 1] Executing Real Smoke Suite (smoke_v1: 2 cases × 1)"
    echo "================================================================================"
    python3 -m testteller.main benchmark \
        --suite evals/suites/smoke_v1.yaml \
        --repeats 1 \
        --backend docker \
        --model "${MODEL}"

    echo ""
    echo "==> [Audit] Validating Smoke Evidence Chain..."
    python3 scripts/audit_smoke_evidence.py
}

run_dry_run() {
    echo ""
    echo "================================================================================"
    echo "==> [Step 2] Executing Formal Dry Run (benchmark_v1: 24 cases × 1)"
    echo "================================================================================"
    python3 -m testteller.main benchmark \
        --suite evals/suites/benchmark_v1.yaml \
        --repeats 1 \
        --backend docker \
        --model "${MODEL}"
}

run_baseline() {
    echo ""
    echo "================================================================================"
    echo "==> [Step 3] Executing Official Baseline Freeze (benchmark_v1: 24 cases × 3 = 72)"
    echo "================================================================================"
    python3 -m testteller.main benchmark \
        --suite evals/suites/benchmark_v1.yaml \
        --repeats 3 \
        --backend docker \
        --model "${MODEL}"
}

case "${MODE}" in
    smoke)
        run_smoke
        ;;
    dry-run|dryrun)
        run_dry_run
        ;;
    baseline)
        run_baseline
        ;;
    all)
        run_smoke
        run_dry_run
        run_baseline
        ;;
    *)
        echo "❌ Unknown mode: ${MODE}"
        echo "Usage: $0 [smoke|dry-run|baseline|all] [model_name]"
        exit 1
        ;;
esac

echo ""
echo "================================================================================"
echo "✅ Execution completed successfully for mode: ${MODE}"
echo "================================================================================"
