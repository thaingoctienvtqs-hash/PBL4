"""Offline JSONL commands only. --help never imports the ArtGuard application."""
import argparse
import json
import sys
from pathlib import Path

try:
    from . import analyzer
except ImportError:
    import analyzer

def bounded_lines(stream):
    """Read at most 1 MiB + one byte at once, draining oversized physical lines."""
    limit = analyzer.MAX_LINE_BYTES
    while True:
        part = stream.readline(limit + 1)
        if not part:
            return
        if len(part) > limit:
            # Drop the remainder without constructing a giant line in memory.
            while part and not part.endswith(b"\n"):
                part = stream.readline(limit + 1)
            yield b"x" * (limit + 1)
        else:
            yield part

def build_parser():
    parser = argparse.ArgumentParser(description="ArtGuard latency: offline JSONL only; no camera or GPU.")
    commands = parser.add_subparsers(dest="command")
    analyze = commands.add_parser("analyze", help="Read timing JSONL and produce separate timing summaries.")
    analyze.add_argument("--input", required=True, type=Path, help="Existing JSONL file, opened read-only.")
    analyze.add_argument("--stdout", action="store_true", help="Write the full JSON report to stdout; no artifacts.")
    analyze.add_argument("--output-root", type=Path, default=None,
                         help="Optional parent under debug/latency_diagnostics/runs; create a unique new run.")
    return parser

def _write_summary(root, report):
    # The recorder enforces the single authorized runs root, no symlink/reparse
    # ancestors, and exclusive leaf directory creation.
    try:
        from .recorder import create_run_directory
    except ImportError:
        from recorder import create_run_directory
    directory = Path(create_run_directory(parent=root, label="analysis"))
    output = directory / "summary.json"
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    return output

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "analyze":
        parser.error("Choose analyze; live acquisition and GPU benchmark commands are intentionally unavailable.")
    if not args.stdout and args.output_root is None:
        parser.error("Use --stdout and/or an explicit --output-root under this tool's runs directory.")
    try:
        if not args.input.is_file():
            raise ValueError("--input must name an existing regular JSONL file")
        with args.input.open("rb") as handle:
            records, parse_errors = analyzer.parse_jsonl(bounded_lines(handle))
        report = analyzer.analyze_records(records)
        report["parse_errors"] = parse_errors
        report["counts"]["invalid_jsonl_lines"] = len(parse_errors)
        if parse_errors:
            analyzer.mark_incomplete_input(report, "invalid_jsonl_lines")
        output = _write_summary(args.output_root, report) if args.output_root is not None else None
        if args.stdout:
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        elif output is not None:
            print(json.dumps(dict(summary_path=str(output), parsed_records=len(records),
                                  invalid_lines=len(parse_errors)), ensure_ascii=False))
        return 1 if parse_errors or report["errors"] else 0
    except (OSError, ValueError, TypeError) as exc:
        print("latency analyze: " + str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
