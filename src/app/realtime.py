"""Backward-compatible command entry point for the PBL4 inference worker."""

from src.realtime_worker import main


if __name__ == "__main__":
    raise SystemExit(main())
