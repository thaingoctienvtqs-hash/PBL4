"""Run isolated logic tests and persist explicitly labeled diagnostic artifacts."""
import json
import sys
import unittest
from common import create_run, source_hashes, write_json_new, LogicSession, config_compat
import test_logic

def main():
    run = create_run("logic")
    before = source_hashes()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_logic)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    with (run / "logic_frames.jsonl").open("x", encoding="utf-8") as log:
        for case, frames in sorted(test_logic.TRACES.items()):
            for frame in frames:
                log.write(json.dumps(dict(frame, scenario=case), allow_nan=False) + "\n")
    sweep = []
    for timeout in (1.0, 2.0, 3.0, 5.0):
        for gap in (.6, 1.01, 2.01, 3.01):
            session = LogicSession()
            session.settings["alert"]["track_timeout_seconds"] = timeout
            session.step(0, (250,))
            for index in range(1, 6):
                session.step(index*gap, (400,), .6)
            tracks = [f["tracks"][0] for f in session.rows]
            sweep.append({"controlled_gap_seconds": gap, "timeout_seconds": timeout,
                          "unique_track_ids": len(set(t["track_id"] for t in tracks)),
                          "alert_starts": sum(t["alert_started"] for t in tracks),
                          "not_real_inference_timing": True})
    write_json_new(run / "timeout_sweep.json", sweep)
    # Only this new database receives writes. It is not an AI alert database.
    from src.services.event_store import EventStore
    store = EventStore(run / "logic_only.sqlite3")
    store.set_status("LOGIC_TEST_ONLY", tests_run=result.testsRun,
                     failures=len(result.failures), errors=len(result.errors),
                     model_loaded=False, camera_opened=False)
    for case, frames in test_logic.TRACES.items():
        for frame in frames:
            for track in frame["tracks"]:
                if track["alert_started"]:
                    store.record_event("CONTROLLED_LOGIC_TEST_NOT_AI",
                                       {"scenario": case, "track": track,
                                        "controlled_time": frame["tracking_monotonic_seconds"]})
    summary = {"tests_run": result.testsRun, "failures": len(result.failures),
               "errors": len(result.errors), "skipped": len(result.skipped),
               "success": result.wasSuccessful(), "source_hashes_before": before,
               "source_hashes_after": source_hashes(),
               "model_loaded": False, "camera_opened": False,
               "note": "Characterization PASS includes reproducing current limitations; not recognition metrics."}
    summary["production_sources_unchanged"] = summary["source_hashes_before"] == summary["source_hashes_after"]
    write_json_new(run / "summary.json", summary)
    print("ARTIFACTS=" + str(run))
    return 0 if result.wasSuccessful() and summary["production_sources_unchanged"] else 1

if __name__ == "__main__":
    sys.exit(main())
