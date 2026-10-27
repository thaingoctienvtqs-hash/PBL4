"""Real filesystem JSONL integration. Each test retains its own new phase_e artifacts."""
import hashlib
import json
import unittest
import uuid
from pathlib import Path
from .controlled_cases import settings,controlled_cases
from .replay import replay_file,MAX_LINE_BYTES,BASE,write_json

class ReplayFileTests(unittest.TestCase):
    def fixture(self,raw):
        directory=BASE/"io_tests"/uuid.uuid4().hex
        directory.mkdir(parents=True,exist_ok=False)
        config=directory/"settings.json";write_json(config,settings())
        data=directory/"predictions.jsonl"
        with data.open("xb") as out:out.write(raw)
        return directory,config,data
    def test_real_jsonl_file_to_alert_and_log(self):
        records=next(c for c in controlled_cases() if c["name"]=="slow_entry")["records"]
        raw=("".join(json.dumps(r)+"\n" for r in records)).encode("utf-8")
        directory,config,data=self.fixture(raw)
        output,summary=replay_file(data,config,True,directory/"output")
        self.assertEqual(summary["event_count"],1)
        self.assertEqual(summary["input_sha256"],hashlib.sha256(raw).hexdigest())
        logs=[json.loads(line) for line in (output/"frames.jsonl").read_text().splitlines()]
        self.assertEqual(len(logs),len(records))
        self.assertTrue(any(r["used_for_confirmation"] for r in logs))
    def test_invalid_utf8_and_oversized_record_are_logged(self):
        raw=b"\xff\n"+b" "*(MAX_LINE_BYTES+1)+b"\n"
        directory,config,data=self.fixture(raw)
        output,summary=replay_file(data,config,True,directory/"output")
        self.assertEqual(summary["rejected"],2)
        logs=[json.loads(line) for line in (output/"frames.jsonl").read_text().splitlines()]
        self.assertEqual([r["reason"] for r in logs],["invalid_utf8_jsonl","oversized_jsonl_record"])
    def test_replays_do_not_overwrite_previous_output(self):
        records=next(c for c in controlled_cases() if c["name"]=="slow_entry")["records"]
        raw=("".join(json.dumps(r)+"\n" for r in records)).encode("utf-8")
        directory,config,data=self.fixture(raw)
        first,unused=replay_file(data,config,True,directory/"output")
        before=(first/"frames.jsonl").read_bytes()
        second,unused=replay_file(data,config,True,directory/"output")
        self.assertNotEqual(first,second)
        self.assertEqual((first/"frames.jsonl").read_bytes(),before)
    def test_default_real_file_run_is_unknown(self):
        records=next(c for c in controlled_cases() if c["name"]=="slow_entry")["records"]
        directory,config,data=self.fixture(("".join(json.dumps(r)+"\n" for r in records)).encode())
        output,summary=replay_file(data,config,False,directory/"output")
        self.assertEqual(summary["event_count"],0)
        self.assertEqual(summary["unavailable_records"],summary["records"])
        self.assertFalse(summary["simulate_stability"])

if __name__=="__main__":unittest.main()
