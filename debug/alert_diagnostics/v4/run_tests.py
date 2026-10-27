"""Run logic tests and comparisons; all newly created outputs stay under v4/runs."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
from .compare_v3_v4 import new_output_directory,write_comparison,ROOT
from . import test_comparison

def protected_hashes():
    reference = ROOT/"debug/alert_diagnostics/protected_files.sha256.corrected.json"
    names = json.loads(reference.read_text())
    result = {}
    for name in names:
        digest = hashlib.sha256()
        with (ROOT/name).open("rb") as handle:
            for block in iter(lambda:handle.read(1048576),b""):
                digest.update(block)
        result[name] = digest.hexdigest()
    return result

def main():
    before = protected_hashes()
    directory = new_output_directory("logic_v4")
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_comparison)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    comparisons = write_comparison(directory)
    after = protected_hashes()
    summary = {"python":sys.version,"tests_run":result.testsRun,"failures":len(result.failures),
               "errors":len(result.errors),"skipped":len(result.skipped),"success":result.wasSuccessful(),
               "comparison_rows":len(comparisons),"protected_before":before,"protected_after":after,
               "protected_files_unchanged":before==after,"gpu_inference_run":False,
               "camera_opened":False,"database_opened":False,"accuracy":"NOT_EVALUATED",
               "precision":"NOT_EVALUATED","recall":"NOT_EVALUATED","f1":"NOT_EVALUATED"}
    with (directory/"test_summary.json").open("x",encoding="utf-8") as handle:
        json.dump(summary,handle,indent=2)
    print("ARTIFACTS="+str(directory))
    return 0 if result.wasSuccessful() and before==after else 1

if __name__=="__main__":
    sys.exit(main())
