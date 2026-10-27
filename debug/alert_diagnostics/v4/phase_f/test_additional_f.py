"""Additional explicit frame-loss and association contracts; all inputs are in memory."""
import copy
import unittest
from .cases_f import cases_f
from .compare_f import replay,evaluate_truth
from .pipeline_f import OfflineF
from ..phase_e.controlled_cases import control,SOURCE

def get(name):return copy.deepcopy(next(c for c in cases_f() if c["name"]==name))

def actual_missing(kind):
    case=get("multiple_missing")
    for row in case["records"][3:6]:
        row["kind"]=kind
        for key in ("prediction","image_size","coordinate_space"):row.pop(key,None)
    return case

class AdditionalContracts(unittest.TestCase):
    def test_three_explicit_missing_frames_recover_with_fresh_evidence(self):
        logs,p,unused=replay(actual_missing("missing"))
        self.assertEqual(sum(len(r["events"]) for r in logs),1)
        self.assertEqual([r["state"] for r in logs[3:6]],["FRAME_MISSING"]*3)
        self.assertTrue(all(r["tracks"][0]["positive_frames"]==0 for r in logs[3:6]))
        self.assertEqual(logs[-1]["tracks"][0]["positive_frames"],3)
    def test_three_explicit_frame_errors_recover(self):
        logs,p,unused=replay(actual_missing("frame_error"))
        self.assertEqual(sum(len(r["events"]) for r in logs),1)
        self.assertEqual([r["state"] for r in logs[3:6]],["FRAME_ERROR"]*3)
    def test_explicit_missing_timeout_one_two_three(self):
        counts=[]
        for timeout in (1,2,3):
            logs,p,unused=replay(actual_missing("missing"),True,timeout)
            counts.append(sum(len(r["events"]) for r in logs))
        self.assertEqual(counts,[0,1,1])
    def test_crossing_detection_permutation_no_owner_transfer(self):
        case=get("crossing_after_missing")
        for row in case["records"]:
            for values in row["prediction"].values():values.reverse()
            row["oracle"]["actors"].reverse()
        logs,p,unused=replay(case)
        self.assertEqual(evaluate_truth(case,logs)["identity"]["track_owner_transfers"],[])
    def test_full_cache_disconnect_clears_probation_buffers(self):
        case=get("explicit_missing_frame")
        case["settings"]["sources"][SOURCE]["pipeline_config"]["input"]={"frame_id_cache_size":5}
        model=OfflineF(case["settings"],True,True)
        for row in case["records"][:5]:model.process(row)
        self.assertTrue(model.pipelines[SOURCE].tracker.pending)
        output=model.process(control("disconnect",.8,frame_id=case["records"][4]["frame_id"]))
        self.assertEqual(output["state"],"CAMERA_OFFLINE")
        self.assertEqual(model.pipelines[SOURCE].tracker.pending,{})
        self.assertEqual(model.pipelines[SOURCE].contacts,{})
    def test_changed_view_calibration_cannot_restore_old_entry(self):
        case=get("explicit_missing_frame")
        case["records"][5]["stability"]["reference_id"]="changed_pose"
        logs,p,unused=replay(case)
        self.assertEqual(sum(len(r["events"]) for r in logs),0)
        self.assertEqual(logs[5]["state"],"CAMERA_UNVERIFIED")
        self.assertFalse(logs[-1]["tracks"][0]["ever_entered_roi"])

if __name__=="__main__":unittest.main()
