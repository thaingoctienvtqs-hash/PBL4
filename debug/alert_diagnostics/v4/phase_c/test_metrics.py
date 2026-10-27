"""Known arithmetic fixtures only. These are not empirical ArtGuard performance."""
import unittest
from .metrics import binary_metrics,make_windows,classification_report,event_report,validate_manifest,percentile

def label(start,end,value):
    return {"start_seconds":start,"end_seconds":end,"label":value}

def gt(key,start,end,video="v"):
    return {"event_id":key,"video_id":video,"start_seconds":start,"end_seconds":end}

def alert(key,t,video="v",emit=None):
    return {"event_id":key,"video_id":video,"trigger_source_seconds":t,"emitted_elapsed_seconds":emit}

def pred(window,value,available=1):
    return dict(window,predicted_contact=value,available=available)

class MetricTests(unittest.TestCase):
    def test_confusion_and_standard_metrics(self):
        rows=make_windows("v",4,[label(0,2,"contact"),label(2,4,"no_contact")])
        report=classification_report(rows,[pred(w,v) for w,v in zip(rows,[1,0,1,0])])
        self.assertEqual(report["confusion_matrix"]["counts"],[[1,1,0],[1,1,0]])
        self.assertEqual(report["metrics"],{"accuracy":.5,"precision":.5,"recall":.5,"f1":.5})

    def test_zero_denominators_are_undefined_not_one(self):
        self.assertEqual(binary_metrics(0,0,0,10),{"accuracy":1.0,"precision":None,"recall":None,"f1":None})
        self.assertIsNone(binary_metrics(0,0,0,0)["accuracy"])

    def test_no_predicted_positive_with_true_positive_class(self):
        report=binary_metrics(0,0,3,2)
        self.assertIsNone(report["precision"])
        self.assertEqual(report["recall"],0)
        self.assertEqual(report["f1"],0)

    def test_counts_invalid(self):
        for counts in ((-1,0,0,0),(True,0,0,0),(1.2,0,0,0)):
            with self.assertRaises(ValueError):binary_metrics(*counts)

    def test_missing_prediction_blocks_primary_metrics(self):
        rows=make_windows("v",2,[label(0,1,"contact"),label(1,2,"no_contact")])
        report=classification_report(rows,[pred(rows[0],1)])
        self.assertIsNone(report["metrics"])
        self.assertEqual(report["coverage"],.5)
        self.assertEqual(report["confusion_matrix"]["counts"],[[1,0,0],[0,0,1]])

    def test_explicit_unavailable_is_not_negative(self):
        rows=make_windows("v",1,[label(0,1,"contact")])
        report=classification_report(rows,[pred(rows[0],None,0)])
        self.assertEqual(report["confusion_matrix"]["counts"],[[0,0,1],[0,0,0]])

    def test_uncertain_window_reported_separately(self):
        rows=make_windows("v",2,[label(0,.2,"uncertain"),label(.2,2,"no_contact")])
        report=classification_report(rows,[pred(w,0) for w in rows])
        self.assertEqual(report["unknown_windows"],1)
        self.assertEqual(report["known_windows"],1)

    def test_short_touch_marks_window_positive(self):
        rows=make_windows("v",1,[label(0,.1,"no_contact"),label(.1,.2,"contact"),label(.2,1,"no_contact")])
        self.assertEqual(rows[0]["target"],1)

    def test_annotation_gaps_and_overlaps_rejected(self):
        for intervals in ([label(0,.4,"contact"),label(.5,1,"no_contact")],
                          [label(0,.6,"contact"),label(.5,1,"no_contact")]):
            with self.assertRaises(ValueError):make_windows("v",1,intervals)

    def test_final_partial_window_is_explicit(self):
        rows=make_windows("v",1.5,[label(0,1.5,"no_contact")])
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]["end_seconds"],1.5)

    def test_duplicate_unexpected_or_misaligned_predictions_rejected(self):
        rows=make_windows("v",1,[label(0,1,"contact")]);p=pred(rows[0],1)
        for predictions in ([p,p],[dict(p,video_id="wrong")],[dict(p,start_seconds=.1)]):
            with self.assertRaises(ValueError):classification_report(rows,predictions)

    def test_one_to_one_event_matching_penalizes_duplicates(self):
        report=event_report([gt("g",1,2)],[alert("a",1.2),alert("b",1.3)],3600)
        self.assertEqual((report["tp"],report["fp"],report["fn"]),(1,1,0))
        self.assertEqual(report["false_alerts_per_known_monitoring_hour"],1)

    def test_maximum_cardinality_not_greedy_matching(self):
        report=event_report([gt("long",0,3),gt("short",1,1.1)],
                            [alert("a",1.05),alert("b",2)],10,late_tolerance=0,max_delay=3)
        self.assertEqual(report["tp"],2)

    def test_latency_source_and_emission_are_separate(self):
        report=event_report([gt("g",1,2)],[alert("a",1.2,emit=1.5)],10)
        self.assertAlmostEqual(report["latency_detected_events_only"]["source_p50"],.2)
        self.assertAlmostEqual(report["latency_detected_events_only"]["emission_p50"],.5)

    def test_late_and_early_alerts_outside_protocol_are_false(self):
        report=event_report([gt("g",1,2)],[alert("early",.9),alert("late",3.1)],10)
        self.assertEqual((report["tp"],report["fp"],report["fn"]),(0,2,1))

    def test_event_matching_never_crosses_video(self):
        report=event_report([gt("g",1,2,"one")],[alert("a",1.2,"two")],10)
        self.assertEqual((report["tp"],report["fp"],report["fn"]),(0,1,1))

    def test_zero_event_exposure_is_undefined(self):
        report=event_report([],[],0)
        self.assertIsNone(report["false_alerts_per_known_monitoring_hour"])
        self.assertIsNone(report["precision"])

    def test_duplicate_event_ids_and_negative_times_rejected(self):
        for alerts in ([alert("a",1),alert("a",1.1)],[alert("a",-1)],[alert("a",1.2,emit=1.1)]):
            with self.assertRaises(ValueError):event_report([gt("g",1,2)],alerts,10)

    def test_percentile_interpolation(self):
        self.assertEqual(percentile([0,10],.5),5)
        self.assertIsNone(percentile([],.95))

    def test_session_group_and_hash_split_leakage(self):
        a={"video_id":"a","split":"validation","duration_seconds":10,"sha256":"a"*64,
           "session_id":"session-a","capture_group_id":"group-a"}
        b=dict(a,video_id="b",split="test",sha256="b"*64,session_id="session-b",capture_group_id="group-b")
        self.assertTrue(validate_manifest([a,b]))
        for bad in (dict(b,session_id=a["session_id"]),dict(b,capture_group_id=a["capture_group_id"]),
                    dict(b,sha256=a["sha256"])):
            with self.assertRaises(ValueError):validate_manifest([a,bad])

class AdditionalExposureTests(unittest.TestCase):
    def test_duplicate_content_same_split_is_also_rejected(self):
        a={"video_id":"a","split":"test","duration_seconds":10,"sha256":"a"*64,
           "session_id":"s1","capture_group_id":"g1"}
        b=dict(a,video_id="b",session_id="s2",capture_group_id="g2")
        with self.assertRaises(ValueError):validate_manifest([a,b])

class TraceWindowTests(unittest.TestCase):
    def test_no_lookahead_or_forward_filling(self):
        from .metrics import trace_to_windows
        windows=make_windows("v",2,[label(0,2,"no_contact")])
        result=trace_to_windows(windows,[{"video_id":"v","frame_id":"a","timestamp":1.2,
                                         "accepted":True,"model_frame_available":True,"tracks":[{"state":"ALERT"}]}])
        self.assertEqual(result[0]["available"],0)
        self.assertIsNone(result[0]["predicted_contact"])
        self.assertEqual(result[1]["predicted_contact"],1)

    def test_missing_model_result_is_not_true_negative(self):
        from .metrics import trace_to_windows
        windows=make_windows("v",1,[label(0,1,"no_contact")])
        result=trace_to_windows(windows,[{"video_id":"v","accepted":True,"timestamp":.2,"tracks":[]}])
        self.assertEqual(result[0]["available"],0)

    def test_fresh_no_hand_model_frame_is_valid_negative(self):
        from .metrics import trace_to_windows
        windows=make_windows("v",1,[label(0,1,"contact")])
        result=trace_to_windows(windows,[{"video_id":"v","frame_id":"a","timestamp":.2,
                                         "accepted":True,"model_frame_available":True,"tracks":[]}])
        self.assertEqual(result[0]["available"],1)
        self.assertEqual(result[0]["predicted_contact"],0)

    def test_duplicate_successful_trace_rejected(self):
        from .metrics import trace_to_windows
        windows=make_windows("v",1,[label(0,1,"contact")])
        row={"video_id":"v","frame_id":"a","timestamp":.2,"accepted":True,
             "model_frame_available":True,"tracks":[]}
        with self.assertRaises(ValueError):trace_to_windows(windows,[row,row])
