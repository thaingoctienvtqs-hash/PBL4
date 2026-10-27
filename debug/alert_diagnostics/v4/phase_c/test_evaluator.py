"""CSV evaluator arithmetic integration in memory, no real metrics or file writes."""
import copy
import unittest
from .evaluate import evaluate
from .metrics import validate_manifest

PROTOCOL={"window_seconds":1,"early_tolerance_seconds":0,"late_tolerance_seconds":.5,
          "max_detection_delay_seconds":2,"max_uncertain_exposure_fraction":.05}
def fixture():
    manifest=[{"video_id":"v","session_id":"s","capture_group_id":"g","sha256":"a"*64,
               "split":"test","duration_seconds":"2","labels_approved":"yes"}]
    intervals=[{"video_id":"v","start_seconds":"0","end_seconds":"1","label":"contact"},
               {"video_id":"v","start_seconds":"1","end_seconds":"2","label":"no_contact"}]
    events=[{"video_id":"v","event_id":"t","start_seconds":"0","end_seconds":"1"}]
    predictions=[{"video_id":"v","window_index":str(i),"start_seconds":str(i),"end_seconds":str(i+1),
                  "available":"1","predicted_contact":str(1-i)} for i in range(2)]
    alerts=[{"video_id":"v","event_id":"p","trigger_source_seconds":".2","emitted_elapsed_seconds":".3"}]
    return [manifest,intervals,events,predictions,alerts]
class EvaluatorTests(unittest.TestCase):
    def test_complete_math_fixture_evaluates_without_model(self):
        report=evaluate(*fixture(),PROTOCOL,"test")
        self.assertEqual(report["classification"]["metrics"]["accuracy"],1)
        self.assertEqual(report["events"]["tp"],1)

    def test_unapproved_labels_rejected(self):
        data=fixture();data[0][0]["labels_approved"]="no"
        with self.assertRaises(ValueError):evaluate(*data,PROTOCOL,"test")

    def test_missing_contact_event_annotation_rejected(self):
        data=fixture();data[2]=[]
        with self.assertRaises(ValueError):evaluate(*data,PROTOCOL,"test")

    def test_event_in_negative_interval_rejected(self):
        data=fixture();data[2][0].update(start_seconds="1",end_seconds="1.5")
        with self.assertRaises(ValueError):evaluate(*data,PROTOCOL,"test")

    def test_missing_predictions_block_target_assessment(self):
        data=fixture();data[3]=[]
        report=evaluate(*data,PROTOCOL,"test")
        self.assertEqual(report["target_assessment_status"],"BLOCKED")
        self.assertIsNone(report["classification"]["metrics"])

    def test_no_real_manifest_never_produces_metrics(self):
        with self.assertRaises(ValueError):evaluate([],[],[],[],[],PROTOCOL,"test")

    def test_unknown_video_rejected(self):
        data=fixture();data[4][0]["video_id"]="other"
        with self.assertRaises(ValueError):evaluate(*data,PROTOCOL,"test")
