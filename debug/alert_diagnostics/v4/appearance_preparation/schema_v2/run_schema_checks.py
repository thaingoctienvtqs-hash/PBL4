"""Run annotation-only tests; exclusive reports under this new schema_v2 tree."""
import ast
import io
import json
import sys
import unittest
import uuid
from datetime import datetime
from pathlib import Path

def main():
    root = Path(__file__).resolve().parent
    if sys.version_info < (3, 7):
        raise RuntimeError("Python 3.7+ required")
    for path in root.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    suite = unittest.defaultTestLoader.discover(str(root), pattern="test_schema_v2.py", top_level_dir=str(root))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    from validate_v2 import validation_report
    from synthetic_cases import base
    formal = validation_report(base())["formal_draft7"]
    report = {
        "scope": "SYNTHETIC_TEST annotation contract only; no AI or tracking executed",
        "python": sys.version, "tests": result.testsRun,
        "pass": result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        "fail": len(result.failures), "error": len(result.errors), "skip": len(result.skipped),
        "formal_draft7": formal, "ai_metrics": "NOT_EVALUATED", "output": stream.getvalue()}
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    out = runs / ("schema_tests_" + datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8] + ".json")
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(stream.getvalue())
    print(json.dumps({k:v for k,v in report.items() if k != "output"}, ensure_ascii=True))
    print("report=" + str(out))
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())
