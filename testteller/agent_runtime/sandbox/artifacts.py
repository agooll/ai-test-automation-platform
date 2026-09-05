"""Artifact extraction and parsing from test runs (JUnit XML, JSON reports, coverage)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
from typing import Any
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class ArtifactExtractor:
    """Discovers, parses, and persists standard test execution artifacts."""

    @staticmethod
    def extract_from_dir(workspace_dir: Path | str) -> dict[str, Any]:
        """Extract artifacts in-place from a directory."""
        workdir = Path(workspace_dir).resolve()
        artifacts: dict[str, Any] = {
            "junit_xml": None,
            "junit_summary": None,
            "json_report": None,
            "coverage": None,
            "captured_files": [],
        }
        if not workdir.is_dir():
            return artifacts

        # Look for junit.xml or test-results.xml
        junit_candidates = [
            workdir / "junit.xml",
            workdir / "test-results.xml",
            workdir / "pytest-report.xml",
        ]
        for candidate in junit_candidates:
            if candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8", errors="replace")
                    artifacts["junit_xml"] = content
                    artifacts["junit_summary"] = ArtifactExtractor._parse_junit_xml(content)
                    artifacts["captured_files"].append(candidate.name)
                    break
                except Exception as exc:
                    logger.debug("Failed parsing junit file %s: %s", candidate, exc)

        # Look for .report.json or report.json
        json_candidates = [
            workdir / ".report.json",
            workdir / "report.json",
            workdir / "test-report.json",
        ]
        for candidate in json_candidates:
            if candidate.is_file():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
                    artifacts["json_report"] = data
                    artifacts["captured_files"].append(candidate.name)
                    break
                except Exception as exc:
                    logger.debug("Failed parsing json report %s: %s", candidate, exc)

        # Look for coverage files
        coverage_candidates = [
            workdir / "coverage.json",
            workdir / "coverage.xml",
        ]
        for candidate in coverage_candidates:
            if candidate.is_file():
                try:
                    if candidate.suffix == ".json":
                        artifacts["coverage"] = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
                    else:
                        artifacts["coverage"] = {"xml_present": True, "path": candidate.name}
                    artifacts["captured_files"].append(candidate.name)
                    break
                except Exception as exc:
                    logger.debug("Failed parsing coverage file %s: %s", candidate, exc)

        # Look for screenshots or image artifacts
        for img in workdir.glob("*.png"):
            artifacts["captured_files"].append(img.name)

        return artifacts

    @classmethod
    def extract_and_persist(
        cls,
        source_dir: Path | str,
        persistent_dir: Path | str,
    ) -> dict[str, Any]:
        """Extract artifacts from source_dir, persist them to persistent_dir before staging deletion."""
        src = Path(source_dir).resolve()
        dest = Path(persistent_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        # First extract structured data from source
        artifacts = cls.extract_from_dir(src)
        persisted_files: list[str] = []

        # Copy captured files to persistent storage
        for file_name in artifacts["captured_files"]:
            src_file = src / file_name
            dest_file = dest / file_name
            if src_file.is_file():
                try:
                    shutil.copy2(src_file, dest_file)
                    persisted_files.append(file_name)
                except Exception as exc:
                    logger.warning("Failed copying artifact %s to persistent dir: %s", file_name, exc)

        artifacts["persisted_dir"] = str(dest)
        artifacts["persisted_files"] = persisted_files
        return artifacts

    @staticmethod
    def _parse_junit_xml(xml_content: str) -> dict[str, Any] | None:
        try:
            root = ET.fromstring(xml_content)
            # Root can be <testsuites> or <testsuite>
            if root.tag == "testsuites":
                suites = root.findall("testsuite")
                if "tests" in root.attrib:
                    tests = int(root.attrib.get("tests", 0))
                    failures = int(root.attrib.get("failures", 0))
                    errors = int(root.attrib.get("errors", 0))
                    skipped = int(root.attrib.get("skipped", 0))
                    time_taken = float(root.attrib.get("time", 0.0))
                elif suites:
                    tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
                    failures = sum(int(s.attrib.get("failures", 0)) for s in suites)
                    errors = sum(int(s.attrib.get("errors", 0)) for s in suites)
                    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
                    time_taken = round(sum(float(s.attrib.get("time", 0.0)) for s in suites), 4)
                else:
                    tests = failures = errors = skipped = 0
                    time_taken = 0.0
            elif root.tag == "testsuite":
                tests = int(root.attrib.get("tests", 0))
                failures = int(root.attrib.get("failures", 0))
                errors = int(root.attrib.get("errors", 0))
                skipped = int(root.attrib.get("skipped", 0))
                time_taken = float(root.attrib.get("time", 0.0))
            else:
                return None

            passed = max(0, tests - (failures + errors + skipped))
            return {
                "tests": tests,
                "passed": passed,
                "failures": failures,
                "errors": errors,
                "skipped": skipped,
                "time_seconds": time_taken,
            }
        except Exception:
            return None
