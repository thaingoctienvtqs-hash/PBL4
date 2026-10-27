"""All data SYNTHETIC_TEST. Device/filesystem actions are stubs, never real I/O."""
import copy
import io
import sys
import unittest
from unittest.mock import Mock, patch
from debug.latency_diagnostics import schema
from debug.latency_diagnostics.recorder import FrameTrace, ProcessClock, JsonlWriter, BASE, _safe_parent
from debug.latency_diagnostics.timing import observe_call

def trace(values=(100, 200, 300, 400)):
    return FrameTrace("synthetic-camera", "synthetic-session", "frame-1",
                      "SYNTHETIC_TEST", "WARM",
                      ProcessClock("host:test", "epoch-test", iter(values).__next__))

class RecorderTests(unittest.TestCase):
    def test_capture_unknown_and_other_stages_unavailable(self):
        row = trace().snapshot()
        self.assertEqual(row["timestamps"]["t_capture"]["status"], "UNKNOWN")
        self.assertIsNone(row["timestamps"]["t_capture"]["value_ns"])
        self.assertTrue(all(s["status"] == "NOT_AVAILABLE" for k,s in row["timestamps"].items() if k != "t_capture"))
        self.assertEqual(row["alerts"], [])

    def test_explicit_data_kind_required(self):
        with self.assertRaises(ValueError):
            FrameTrace("s", "session", "f", "DEMO", "WARM")

    def test_blank_clock_id_rejected(self):
        with self.assertRaises(ValueError):
            ProcessClock("", "e")

    def test_mark_reads_injected_monotonic_clock(self):
        t = trace()
        t.mark("t_stream2_start");t.mark("t_stream2_end")
        self.assertEqual(t.snapshot()["timestamps"]["t_stream2_end"]["value_ns"], 200)

    def test_capture_cannot_be_marked_as_local_now(self):
        with self.assertRaises(ValueError):
            trace().mark("t_capture")

    def test_capture_rejects_mtime(self):
        t = trace()
        with self.assertRaises(ValueError):
            t.set_capture(schema.measured(123, "host:test", method="st_mtime_ns"))

    def test_capture_rejects_local_clock_placeholder(self):
        with self.assertRaises(ValueError):
            trace().set_capture(schema.measured(123, "host:test"))

    def test_source_capture_domain_declared_and_preserved(self):
        t = trace();t.add_clock("cam:1", "SOURCE_MONOTONIC", "camera-boot-1")
        t.set_capture(schema.measured(12, "cam:1", method="SYNTHETIC_TEST_sensor_timestamp"))
        self.assertEqual(t.snapshot()["timestamps"]["t_capture"]["clock_id"], "cam:1")

    def test_epoch_reuse_conflict_rejected(self):
        with self.assertRaises(ValueError):
            trace().add_clock("host:test", "MONOTONIC", "different-epoch")

    def test_sync_is_explicit_and_copied(self):
        t = trace();t.add_clock("cam:1", "SOURCE_MONOTONIC", "c1")
        sync = dict(sync_id="sync1", from_clock="cam:1", to_clock="host:test",
                    offset_ns=10, uncertainty_ns=2, valid_from_ns=0, valid_to_ns=1000,
                    method="SYNTHETIC_TEST_calibration")
        t.add_sync(sync);sync["offset_ns"]=999
        self.assertEqual(t.snapshot()["clock_sync"][0]["offset_ns"], 10)

    def test_repeated_mark_needs_explicit_replacement(self):
        t = trace();t.mark("t_tracking_end")
        with self.assertRaises(ValueError):
            t.mark("t_tracking_end")
        t.mark("t_tracking_end", replace=True)
        self.assertEqual(t.snapshot()["timestamps"]["t_tracking_end"]["value_ns"], 300)

    def test_readiness_cannot_be_generic_mark(self):
        with self.assertRaises(ValueError):
            trace().mark("t_prediction_ready")

    def test_unconfirmed_prediction_is_unknown(self):
        t=trace();t.prediction_ready(False)
        self.assertFalse(t.snapshot()["prediction_ready_confirmed"])
        self.assertEqual(t.snapshot()["timestamps"]["t_prediction_ready"]["status"], "UNKNOWN")

    def test_confirmed_prediction_measured(self):
        t=trace();t.prediction_ready(True)
        self.assertTrue(t.snapshot()["prediction_ready_confirmed"])
        self.assertEqual(t.snapshot()["timestamps"]["t_prediction_ready"]["value_ns"],100)

    def test_duplicate_alert_rejected(self):
        t=trace();t.add_alert("event-1")
        with self.assertRaises(ValueError):
            t.add_alert("event-1")

    def test_event_commit_is_not_delivery(self):
        t=trace();t.add_alert("event-1");t.mark_alert("event-1","t_event_committed")
        row=t.snapshot()["alerts"][0]
        self.assertEqual(row["timestamps"]["t_alert_delivered"]["status"],"NOT_AVAILABLE")
        self.assertEqual(row["timestamps"]["t_alert_visible"]["status"],"NOT_AVAILABLE")

    def test_delivery_needs_explicit_ack(self):
        t=trace();t.add_alert("event-1")
        with self.assertRaises(ValueError):
            t.mark_alert("event-1","t_alert_delivered")

    def test_ack_has_event_binding_and_observer_time(self):
        t=trace();t.add_alert("event-1")
        stamp=schema.measured(500,"host:test",method="SYNTHETIC_TEST_display")
        t.acknowledge("event-1","t_alert_visible",stamp,"signal-1","synthetic-display")
        row=t.snapshot()["alerts"][0]
        self.assertEqual(row["acknowledgements"]["t_alert_visible"]["kind"],"DISPLAY_RENDER_ACK")
        self.assertEqual(row["timestamps"]["t_alert_visible"]["value_ns"],500)

    def test_unknown_ack_timestamp_rejected(self):
        t=trace();t.add_alert("event-1")
        with self.assertRaises(ValueError):
            t.acknowledge("event-1","t_alert_delivered",schema.unknown(),"signal","observer")

    def test_gpu_interval_keeps_sync_flag_without_inventing_it(self):
        t=trace();t.record_gpu_interval("stream1",1.5,False)
        self.assertFalse(t.snapshot()["gpu_intervals"]["stream1"]["synchronized"])

    def test_snapshot_has_no_mutable_alias(self):
        t=trace();row=t.snapshot();row["issues"].append("changed")
        self.assertEqual(t.snapshot()["issues"],[])

    def test_output_outside_runs_rejected_without_writing(self):
        with self.assertRaises(ValueError):
            _safe_parent(BASE.parent)

    def test_writer_is_exclusive_and_keeps_real_synthetic_separate(self):
        handle=io.StringIO();fake=Mock();fake.parent=BASE/"runs"
        fake.open.return_value=handle
        with patch("debug.latency_diagnostics.recorder.Path",return_value=fake), patch("debug.latency_diagnostics.recorder._safe_parent"):
            writer=JsonlWriter("fake-path","SYNTHETIC_TEST")
            row=trace().snapshot();writer.write(row)
            original=handle.getvalue()
            changed=copy.deepcopy(row);changed["data_kind"]="REAL_INFERENCE"
            with self.assertRaises(ValueError):
                writer.write(changed)
            self.assertEqual(handle.getvalue(),original)
            fake.open.assert_called_once_with("x",encoding="utf-8",newline="\n")
            self.assertTrue(original.endswith("\n"))

    def test_unavailable_gpu_timing_cannot_hide_nonfinite_method(self):
        row=trace().snapshot()
        row["gpu_intervals"]={"stream1":dict(status="NOT_AVAILABLE",duration_ms=None,method=float("nan"),synchronized=False)}
        with self.assertRaises(ValueError):
            schema.validate_record(row)

    def test_unknown_ground_truth_verification_not_an_object(self):
        row=trace().snapshot()
        row["ground_truth"]=dict(label="UNKNOWN",episode_id=None,episode_complete=False,matched_event_keys=[],verification={})
        with self.assertRaises(ValueError):
            schema.validate_record(row)

    def test_no_alert_frame_age_uses_explicit_decision_end(self):
        from debug.latency_diagnostics.analyzer import analyze_records
        t=trace()
        t.set_capture(schema.measured(50,"host:test",method="SYNTHETIC_TEST_source"))
        t.mark("t_decision_end")
        result=analyze_records([t.snapshot()])
        metrics=result["groups"][0]["metrics"]
        self.assertEqual(metrics["frame_age_at_decision_all_frames"]["MEASURED"]["n"],1)
        self.assertAlmostEqual(metrics["frame_age_at_decision_all_frames"]["MEASURED"]["p50_ms"],0.00005)
        self.assertEqual(metrics["frame_age_at_decision"]["MEASURED"]["n"],0)

    def test_frame_age_never_fills_decision_from_tracking(self):
        from debug.latency_diagnostics.analyzer import analyze_records
        t=trace()
        t.set_capture(schema.measured(50,"host:test",method="SYNTHETIC_TEST_source"))
        t.mark("t_tracking_end")
        result=analyze_records([t.snapshot()])
        metrics=result["groups"][0]["metrics"]
        self.assertEqual(metrics["frame_age_at_decision_all_frames"]["MEASURED"]["n"],0)

class CallTimingTests(unittest.TestCase):
    def test_unprintable_probe_exception_does_not_block_business_return(self):
        class BrokenTelemetryError(Exception):
            def __str__(self):
                raise RuntimeError("must not format this telemetry exception")
        t=trace();result=object();business=Mock(return_value=result)
        with patch.object(t,"set_execution_mode",side_effect=BrokenTelemetryError()):
            actual=observe_call(business,t,"t_stream1_start","t_stream1_end",
                                execution_stage="stream1",execution_mode="CPU_ONLY")
        self.assertIs(actual,result)
        business.assert_called_once_with()
        self.assertTrue(any("BrokenTelemetryError" in issue for issue in t.snapshot()["issues"]))

    def test_unprintable_probe_exception_keeps_original_business_exception(self):
        class BrokenTelemetryError(Exception):
            def __str__(self):
                raise RuntimeError("must not format this telemetry exception")
        t=trace();original=ValueError("original business failure");business=Mock(side_effect=original)
        with patch.object(t,"set_execution_mode",side_effect=BrokenTelemetryError()):
            with self.assertRaises(ValueError) as caught:
                observe_call(business,t,"t_stream1_start","t_stream1_end",
                             execution_stage="stream1",execution_mode="CPU_ONLY")
        self.assertIs(caught.exception,original)
        business.assert_called_once_with()

    def test_arguments_and_return_object_are_unchanged(self):
        t=trace();obj=object();argument=[];calls=[]
        def business(a, flag=None):
            calls.append((a,flag));return obj
        result=observe_call(business,t,"t_stream1_start","t_stream1_end",
                            args=(argument,),kwargs={"flag":obj},execution_stage="stream1",execution_mode="CPU_ONLY")
        self.assertIs(result,obj);self.assertEqual(len(calls),1)
        self.assertIs(calls[0][0],argument);self.assertIs(calls[0][1],obj)

    def test_same_business_exception_propagates_and_no_false_end(self):
        t=trace();error=RuntimeError("SYNTHETIC_TEST_failure")
        def fail():raise error
        with self.assertRaises(RuntimeError) as caught:
            observe_call(fail,t,"t_stream1_start","t_stream1_end")
        self.assertIs(caught.exception,error)
        self.assertEqual(t.snapshot()["timestamps"]["t_stream1_end"]["status"],"NOT_AVAILABLE")

    def test_fake_cuda_callbacks_bracket_call(self):
        t=trace();order=[]
        result=observe_call(lambda:order.append("fn") or 5,t,"t_stream1_start","t_stream1_end",
                            execution_stage="stream1",execution_mode="CUDA_SYNCHRONIZED_WALL",
                            synchronize=lambda:order.append("fake-sync"))
        self.assertEqual(order,["fake-sync","fn","fake-sync"]);self.assertEqual(result,5)
        self.assertEqual(t.snapshot()["execution_modes"]["stream1"],"CUDA_SYNCHRONIZED_WALL")

    def test_enqueue_mode_does_not_run_sync_or_claim_execution(self):
        t=trace();sync=Mock(side_effect=AssertionError("must not sync"))
        observe_call(lambda:9,t,"t_stream1_start","t_stream1_end",execution_stage="stream1",
                     execution_mode="CUDA_ENQUEUE_ONLY",synchronize=sync)
        sync.assert_not_called()
        self.assertEqual(t.snapshot()["execution_modes"]["stream1"],"CUDA_ENQUEUE_ONLY")

    def test_missing_cuda_callback_downgrades_measurement(self):
        t=trace();result=observe_call(lambda:7,t,"t_stream1_start","t_stream1_end",
                                     execution_stage="stream1",execution_mode="CUDA_SYNCHRONIZED_WALL")
        self.assertEqual(result,7);self.assertEqual(t.snapshot()["execution_modes"]["stream1"],"UNKNOWN")
        self.assertTrue(t.snapshot()["issues"])

    def test_pre_sync_error_does_not_skip_business(self):
        t=trace();calls=[]
        def broken():raise RuntimeError("SYNTHETIC_TEST_sync")
        result=observe_call(lambda:calls.append("fn") or 7,t,"t_stream1_start","t_stream1_end",
                            execution_stage="stream1",execution_mode="CUDA_SYNCHRONIZED_WALL",synchronize=broken)
        self.assertEqual(result,7);self.assertEqual(calls,["fn"])
        self.assertEqual(t.snapshot()["execution_modes"]["stream1"],"UNKNOWN")

    def test_post_sync_error_does_not_claim_prediction_ready(self):
        t=trace();calls=[]
        def sync():
            calls.append(1)
            if len(calls)>1:raise RuntimeError("SYNTHETIC_TEST_sync")
        result=observe_call(lambda:7,t,"t_inference_start","t_prediction_ready",
                            execution_stage="inference",execution_mode="CUDA_SYNCHRONIZED_WALL",
                            synchronize=sync,prediction_ready_confirmed=True)
        self.assertEqual(result,7);self.assertFalse(t.snapshot()["prediction_ready_confirmed"])
        self.assertEqual(t.snapshot()["timestamps"]["t_prediction_ready"]["status"],"UNKNOWN")

    def test_clock_error_does_not_change_result(self):
        t=trace((-1,200))
        result=observe_call(lambda:7,t,"t_stream1_start","t_stream1_end")
        self.assertEqual(result,7)
        self.assertEqual(t.snapshot()["timestamps"]["t_stream1_start"]["status"],"NOT_AVAILABLE")

    def test_stale_probe_timestamp_is_invalidated_on_repeat(self):
        t=trace();t.mark("t_stream1_start")
        self.assertEqual(observe_call(lambda:7,t,"t_stream1_start","t_stream1_end"),7)
        self.assertEqual(t.snapshot()["timestamps"]["t_stream1_start"]["status"],"NOT_AVAILABLE")

    def test_event_return_without_predicate_is_not_commit_proof(self):
        t=trace();t.add_alert("e")
        self.assertIsNone(observe_call(lambda:None,t,None,"t_event_committed",event_key="e"))
        self.assertEqual(t.snapshot()["alerts"][0]["timestamps"]["t_event_committed"]["status"],"NOT_AVAILABLE")

    def test_event_success_predicate_allows_commit_marker(self):
        t=trace();t.add_alert("e")
        self.assertEqual(observe_call(lambda:42,t,None,"t_event_committed",event_key="e",
                                      end_predicate=lambda result:result is not None),42)
        self.assertEqual(t.snapshot()["alerts"][0]["timestamps"]["t_event_committed"]["status"],"MEASURED")

    def test_predicate_failure_does_not_change_business_result(self):
        t=trace();t.add_alert("e")
        def bad(result):raise RuntimeError("SYNTHETIC_TEST_predicate")
        self.assertEqual(observe_call(lambda:42,t,None,"t_event_committed",event_key="e",end_predicate=bad),42)
        self.assertEqual(t.snapshot()["alerts"][0]["timestamps"]["t_event_committed"]["status"],"NOT_AVAILABLE")

    def test_wrapper_does_not_infer_prediction_readiness(self):
        t=trace()
        observe_call(lambda:object(),t,"t_inference_start","t_prediction_ready")
        self.assertFalse(t.snapshot()["prediction_ready_confirmed"])

    def test_explicit_cpu_ready_preserves_object(self):
        t=trace();out=[]
        self.assertIs(observe_call(lambda:out,t,"t_inference_start","t_prediction_ready",
                                   execution_stage="inference",execution_mode="CPU_ONLY",
                                   prediction_ready_confirmed=True),out)
        self.assertTrue(t.snapshot()["prediction_ready_confirmed"])

if __name__ == "__main__":
    unittest.main()
