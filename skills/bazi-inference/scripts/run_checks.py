"""Run portable software checks. This does not measure life-event accuracy."""
from pathlib import Path
import io
import json
import sys
import unittest


def main():
    scripts = Path(__file__).resolve().parent
    root = scripts.parent
    sys.path.insert(0, str(scripts))
    release = json.loads((root / "assets/release.json").read_text(encoding="utf-8"))
    required = ["SKILL.md", "scripts/report_engine.py", "references/inference.md", "references/annual-report.md",
                "references/calculation.md", "references/patterns.md", "references/question-analysis.md",
                "references/ziwei-inference.md", "references/event-discrimination.md"]
    for relative in required:
        if not (root / relative).is_file():
            raise FileNotFoundError(relative)
    suite = unittest.defaultTestLoader.discover(str(scripts), pattern="test_*.py")
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    print(output.getvalue(), file=sys.stderr)
    print(json.dumps({"skill": release["name"], "version": release["version"],
                      "tests": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "skipped": len(result.skipped),
                      "software_checks_pass": result.wasSuccessful(),
                      "prediction_accuracy_validated": False}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
