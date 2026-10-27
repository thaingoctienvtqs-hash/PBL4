"""Equivalent file replay contracts in F; frozen E I/O tests are not run to avoid E writes."""
import hashlib
import json
import uuid
import unittest
from .replay_f import BASE,replay_file,output_directory
from .cases_f import cases_f
from ..phase_e.replay import MAX_LINE_BYTES,write_json

class FileReplayTests(unittest.TestCase):
    def files(self,raw):
        folder=BASE/"io_tests"/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=False)
        settings=folder/"settings.json";data=folder/"input.jsonl"
        case=next(c for c in cases_f() if c["name"]=="explicit_missing_frame")
        write_json(settings,case["settings"])
        with data.open("xb") as out:out.write(raw)
        return folder,settings,data
    def positive(self):
        c=next(c for c in cases_f() if c["name"]=="explicit_missing_frame")
        return ("".join(json.dumps(r)+"\n" for r in c["records"])).encode()
    def test_file_recovery_to_alert(self):
        raw=self.positive();folder,config,data=self.files(raw)
        path,summary=replay_file(data,config,True,True,folder/"output")
        self.assertEqual(summary["event_count"],1)
        self.assertEqual(summary["input_sha256"],hashlib.sha256(raw).hexdigest())
    def test_default_strict_does_not_assume_identity(self):
        folder,config,data=self.files(self.positive())
        path,summary=replay_file(data,config,False,True,folder/"output")
        self.assertEqual(summary["event_count"],0)
    def test_utf8_and_oversized_records_visible(self):
        folder,config,data=self.files(b"\xff\n"+b" "*(MAX_LINE_BYTES+1)+b"\n")
        path,summary=replay_file(data,config,True,True,folder/"output")
        self.assertEqual(summary["rejected"],2)
    def test_no_overwrite_on_second_replay(self):
        folder,config,data=self.files(self.positive())
        first,unused=replay_file(data,config,True,True,folder/"output")
        before=(first/"frames.jsonl").read_bytes()
        second,unused=replay_file(data,config,True,True,folder/"output")
        self.assertNotEqual(first,second);self.assertEqual((first/"frames.jsonl").read_bytes(),before)
    def test_outside_output_rejected(self):
        with self.assertRaises(ValueError):output_directory(BASE.parent/"phase_e")
    def test_missing_stability_is_unavailable(self):
        folder,config,data=self.files(self.positive())
        path,summary=replay_file(data,config,True,False,folder/"output")
        self.assertEqual(summary["event_count"],0)
        self.assertEqual(summary["records"],summary["unavailable_records"])

if __name__=="__main__":unittest.main()
