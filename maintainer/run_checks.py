"""Run the installed-skill runtime checks and repository-only maintainer checks.

These checks validate software behavior, not the accuracy of life predictions.
They run without real birth records, answer keys, network access, or credentials.
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
from pathlib import Path
import sys
import unittest


def main():
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path,
                        default=repo_root / "skills/bazi-inference",
                        help="Optional canonical skill checkout during development")
    args = parser.parse_args()
    skill_root = args.skill_root.resolve()
    maintainer_root = repo_root / "maintainer"
    release = json.loads((skill_root / "assets/release.json").read_text(encoding="utf-8"))
    required = ["scripts/event_rules.py", "scripts/benchmark.py", "scripts/iteration.py",
                "scripts/compare_versions.py", "references/iteration.md",
                "assets/rule-registry.json"]
    for relative in required:
        if not (maintainer_root / relative).is_file():
            raise FileNotFoundError("maintainer/" + relative)
    roots = {"core": skill_root / "scripts", "maintainer": maintainer_root / "scripts"}
    tests = [(kind, path) for kind, folder in roots.items()
             for path in sorted(folder.glob("test_*.py"))]
    names = [path.stem for _, path in tests]
    if len(names) != len(set(names)):
        raise RuntimeError("Test module names must be unique across core and maintainer directories")
    for folder in roots.values():
        sys.path.insert(0, str(folder))
    suite = unittest.TestSuite()
    counts = {"core": 0, "maintainer": 0}
    for kind, path in tests:
        module = importlib.import_module(path.stem)
        if Path(module.__file__).resolve() != path.resolve():
            raise RuntimeError("Test module imported from an unexpected directory: " + path.stem)
        group = unittest.defaultTestLoader.loadTestsFromModule(module)
        counts[kind] += group.countTestCases()
        suite.addTests(group)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    print(output.getvalue(), file=sys.stderr)
    print(json.dumps({"skill": release["name"], "version": release["version"],
                      "core_tests": counts["core"], "maintainer_tests": counts["maintainer"],
                      "tests": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "skipped": len(result.skipped),
                      "software_checks_pass": result.wasSuccessful(),
                      "prediction_accuracy_validated": False}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
