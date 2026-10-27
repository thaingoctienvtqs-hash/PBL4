"""Offline CLI entrypoint; no camera/GPU commands."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
