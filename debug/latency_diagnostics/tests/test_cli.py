"""Passive CLI tests. All JSONL data SYNTHETIC_TEST, all I/O in memory."""
import contextlib
import io
import json
import unittest
from unittest import mock

from debug.latency_diagnostics import analyzer, cli, recorder
from debug.latency_diagnostics.tests.test_schema import frame


class MemoryOutput:
    def __init__(self):
        self.buffer = io.StringIO()
        self.calls = []

    def open(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return contextlib.nullcontext(self.buffer)

    def __str__(self):
        return "SYNTHETIC_TEST_IN_MEMORY/summary.json"


class MemoryDirectory:
    def __init__(self, output):
        self.output = output
        self.mkdir_calls = []
        self.children = []

    def mkdir(self, *args, **kwargs):
        self.mkdir_calls.append((args, kwargs))

    def __truediv__(self, name):
        self.children.append(name)
        if name == "summary.json":
            return self.output
        return self


class BoundedLinesTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(list(cli.bounded_lines(io.BytesIO())), [])

    def test_oversized_row_drain_preserves_following_record(self):
        raw = b"x" * (analyzer.MAX_LINE_BYTES * 2 + 5) + b"\n"
        valid = json.dumps(frame()).encode("utf-8") + b"\n"
        lines = list(cli.bounded_lines(io.BytesIO(raw + valid)))
        self.assertEqual(len(lines), 2)
        self.assertGreater(len(lines[0]), analyzer.MAX_LINE_BYTES)
        self.assertEqual(lines[1], valid)
        records, errors = analyzer.parse_jsonl(lines)
        self.assertEqual(records, [frame()])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["line"], 1)

    def test_exact_limit_final_line_without_newline_is_preserved(self):
        raw = b" " * analyzer.MAX_LINE_BYTES
        self.assertEqual(list(cli.bounded_lines(io.BytesIO(raw))), [raw])

    def test_exact_limit_line_with_actual_newline_is_preserved(self):
        raw = b" " * (analyzer.MAX_LINE_BYTES - 1) + b"\n"
        self.assertEqual(list(cli.bounded_lines(io.BytesIO(raw))), [raw])

    def test_exactly_one_over_limit_line_preserves_next_line(self):
        first = b"x" * analyzer.MAX_LINE_BYTES + b"\n"
        second = b"{}\n"
        lines = list(cli.bounded_lines(io.BytesIO(first + second)))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1], second)

    def test_oversized_final_line_does_not_loop_or_allocate_full_row(self):
        lines = list(cli.bounded_lines(io.BytesIO(b"x" * (analyzer.MAX_LINE_BYTES * 3 + 19))))
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0]), analyzer.MAX_LINE_BYTES + 1)

    def test_invalid_utf8_is_rejected_and_next_record_survives(self):
        valid = json.dumps(frame()).encode("utf-8")
        records, errors = analyzer.parse_jsonl(cli.bounded_lines(io.BytesIO(b"\xff\n" + valid + b"\n")))
        self.assertEqual(records, [frame()])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["line"], 1)


class CliTests(unittest.TestCase):
    def test_no_implicit_default_artifact_output(self):
        with mock.patch.object(cli.Path, "is_file", side_effect=AssertionError("must reject before input I/O")), \
                mock.patch.object(cli, "_write_summary", side_effect=AssertionError("no implicit artifacts")), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli.main(["analyze", "--input", "SYNTHETIC_TEST.jsonl"])
        self.assertEqual(raised.exception.code, 2)

    def test_no_live_commands_available(self):
        parser = cli.build_parser()
        for command in ("capture", "benchmark", "inference", "camera"):
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                parser.parse_args([command])
            self.assertEqual(raised.exception.code, 2)

    def test_stdout_analysis_opens_only_mocked_input_readonly(self):
        payload = json.dumps(frame()).encode("utf-8") + b"\n"
        output = io.StringIO()
        with mock.patch.object(cli.Path, "is_file", return_value=True), \
                mock.patch.object(cli.Path, "open", return_value=io.BytesIO(payload)) as opened, \
                mock.patch.object(cli, "_write_summary", side_effect=AssertionError("stdout must not write artifacts")), \
                contextlib.redirect_stdout(output):
            code = cli.main(["analyze", "--input", "SYNTHETIC_TEST.jsonl", "--stdout"])
        self.assertEqual(code, 0)
        opened.assert_called_once_with("rb")
        report = json.loads(output.getvalue())
        self.assertEqual(report["counts"]["accepted_records"], 1)
        self.assertEqual(report["groups"][0]["data_kind"], "SYNTHETIC_TEST")
        self.assertEqual(report["counts"]["invalid_jsonl_lines"], 0)
        self.assertTrue(output.getvalue().endswith("\n"))

    def test_stdout_parse_error_reports_nonzero_and_keeps_valid_records(self):
        payload = b"\xff\n" + json.dumps(frame()).encode("utf-8") + b"\n"
        output = io.StringIO()
        with mock.patch.object(cli.Path, "is_file", return_value=True), \
                mock.patch.object(cli.Path, "open", return_value=io.BytesIO(payload)), \
                mock.patch.object(cli, "_write_summary", side_effect=AssertionError("no artifacts")), \
                contextlib.redirect_stdout(output):
            code = cli.main(["analyze", "--input", "SYNTHETIC_TEST.jsonl", "--stdout"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(report["counts"]["accepted_records"], 1)
        self.assertEqual(report["parse_errors"][0]["line"], 1)

    def test_missing_input_reports_error_without_writes(self):
        errors = io.StringIO()
        with mock.patch.object(cli.Path, "is_file", return_value=False), \
                mock.patch.object(cli.Path, "open", side_effect=AssertionError("must not open")), \
                mock.patch.object(cli, "_write_summary", side_effect=AssertionError("must not write")), \
                contextlib.redirect_stderr(errors):
            code = cli.main(["analyze", "--input", "SYNTHETIC_TEST_missing.jsonl", "--stdout"])
        self.assertEqual(code, 2)
        self.assertIn("existing regular JSONL", errors.getvalue())

    def test_input_permission_error_does_not_write_output(self):
        with mock.patch.object(cli.Path, "is_file", return_value=True), \
                mock.patch.object(cli.Path, "open", side_effect=PermissionError("SYNTHETIC_TEST denied")), \
                mock.patch.object(cli, "_write_summary", side_effect=AssertionError("must not write")), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["analyze", "--input", "SYNTHETIC_TEST.jsonl", "--stdout"])
        self.assertEqual(code, 2)


class SummaryWriterTests(unittest.TestCase):
    def test_new_summary_is_exclusive_utf8_json_with_real_trailing_newline(self):
        output = MemoryOutput()
        directory = MemoryDirectory(output)
        report = {"data_kind": "SYNTHETIC_TEST", "description": "offline-only", "metrics": None}
        with mock.patch.object(recorder, "create_run_directory", return_value=directory) as created, \
                mock.patch.object(cli, "Path", side_effect=lambda value: value):
            result = cli._write_summary("SYNTHETIC_TEST_parent", report)
        self.assertIs(result, output)
        self.assertEqual(directory.children, ["summary.json"])
        self.assertEqual(output.calls, [(("x",), {"encoding": "utf-8", "newline": "\n"})])
        self.assertEqual(json.loads(output.buffer.getvalue()), report)
        self.assertTrue(output.buffer.getvalue().endswith("\n"))
        self.assertFalse(output.buffer.getvalue().endswith("\\n"))
        created.assert_called_once_with(parent="SYNTHETIC_TEST_parent", label="analysis")

    def test_summary_label_accepted_by_real_directory_factory_without_disk_io(self):
        output = MemoryOutput()
        directory = MemoryDirectory(output)
        with mock.patch.object(recorder, "_safe_parent", return_value=directory), \
                mock.patch.object(cli, "Path", side_effect=lambda value: value):
            result = cli._write_summary("SYNTHETIC_TEST_parent", {"data_kind": "SYNTHETIC_TEST"})
        self.assertIs(result, output)
        self.assertEqual(directory.mkdir_calls, [((), {"parents": True, "exist_ok": False})])
        self.assertTrue(directory.children[0].startswith("analysis_"))

    def test_existing_summary_collision_propagates_instead_of_overwrite(self):
        output = MemoryOutput()
        directory = MemoryDirectory(output)
        with mock.patch.object(recorder, "create_run_directory", return_value=directory), \
                mock.patch.object(cli, "Path", side_effect=lambda value: value), \
                mock.patch.object(output, "open", side_effect=FileExistsError("SYNTHETIC_TEST collision")) as opened, \
                self.assertRaises(FileExistsError):
            cli._write_summary("SYNTHETIC_TEST_parent", {"data_kind": "SYNTHETIC_TEST"})
        opened.assert_called_once_with("x", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    unittest.main()
