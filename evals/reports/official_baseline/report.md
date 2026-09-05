# TestTeller Benchmark Report: benchmark_v1

## 1. Executive Summary

| Evaluation Dimension | Value |
| :--- | :--- |
| **Total Cases** | 24 |
| **Total Runs** | 72 (Repeats per case: 3) |
| **First Execution Pass Rate** | **29.2%** |
| **Final Execution Pass Rate** | **38.9%** |
| **Repair Recovery Rate** | **13.7%** |
| **Repair Uplift** | **+9.7% pts** |
| **Dual-Oracle Semantic Success** | **11.1%** |
| **Seeded Bug Detection Rate** | **78.6%** |
| **Average Repair Rounds (All)** | 1.35 |
| **Average Repair Rounds (Repaired)** | 1.29 |
| **E2E Latency (p50)** | 37666.8 ms |
| **E2E Latency (p95)** | 88755.7 ms |
| **Sandbox Environment Failure Rate** | 1.4% |

---

## 2. Category Performance Breakdown

| Category | Runs | First Pass | Final Pass | Semantic Success |
| :--- | :--- | :--- | :--- | :--- |
| `boundary_value` | 12 | 25.0% | 41.7% | 8.3% |
| `concurrency_state` | 12 | 41.7% | 50.0% | 0.0% |
| `error_handling` | 12 | 16.7% | 50.0% | 33.3% |
| `happy_path` | 12 | 41.7% | 41.7% | 25.0% |
| `mock_contract` | 12 | 41.7% | 41.7% | 0.0% |
| `security_injection` | 12 | 8.3% | 8.3% | 0.0% |

---

## 3. Difficulty Level Breakdown

| Difficulty | Runs | First Pass | Final Pass | Semantic Success |
| :--- | :--- | :--- | :--- | :--- |
| `easy` | 27 | 29.6% | 40.7% | 18.5% |
| `hard` | 24 | 25.0% | 33.3% | 0.0% |
| `medium` | 21 | 33.3% | 42.9% | 14.3% |

---

## 4. Failure Taxonomy Distribution

| Failure Classification | Count |
| :--- | :--- |
| `assertion_failure` | 23 |
| `missing_dependency` | 10 |
| `repair_exhausted` | 10 |
| `timeout` | 1 |

---

## 5. Reproducibility & Provenance Metadata

- **actual_backend**: `docker`
- **actual_backends**: `['docker']`
- **actual_model_name**: `glm-4-flash`
- **actual_model_names**: `['glm-4-flash']`
- **actual_model_provider**: `zhipu`
- **actual_model_providers**: `['zhipu']`
- **actual_runner_digest**: `sha256:2049fafd14858c6090ecada28df35ea4ec57d2cf1b48225ebc5b1345b3051f68`
- **actual_runner_digests**: `['sha256:2049fafd14858c6090ecada28df35ea4ec57d2cf1b48225ebc5b1345b3051f68']`
- **actual_runner_image**: `testteller-runner-python:3.11-v1`
- **actual_runner_images**: `['testteller-runner-python:3.11-v1']`
- **commit_sha**: `oss_project_1@4500e3d0, oss_project_2@62d7e076`
- **corpus_hash**: `oss_project_1:dc5bd42e, oss_project_2:7dca9165`
- **corpus_hashes**: `{'oss_project_1': 'dc5bd42e5b5fa07fc6d76bc736278e8e24845f0a8efd53291a2095d36b8019d6', 'oss_project_2': '7dca916568d5ef74281462e9ccffbaecf583983a6893b2d82edcc6aa02c8ef71'}`
- **fallback_used**: `False`
- **model_name**: `glm-4-flash`
- **project_name**: `oss_project_1, oss_project_2`
- **projects**: `['oss_project_1', 'oss_project_2']`
- **rag_collections**: `['benchmark_v1_oss_project_1_4500e3d0', 'benchmark_v1_oss_project_2_62d7e076']`
- **runner_image**: `testteller-runner-python:3.11-v1`
- **target_commits**: `{'oss_project_1': '4500e3d04288738d25acbb4973eb3c3e1bf41db9', 'oss_project_2': '62d7e076e1f7d10ed4d9e13314df32c6a1e80173'}`
- **testteller_commit**: `5f3e80c3cf6c5ba764f9dbb34305fab068802651`
