"""Accumulated outside-to-inside entry with overlap hysteresis."""
import math

class ROIEntry:
    def __init__(self, config):
        self.config = dict(config)
        self.entered = False
        self.episode = 0
        self.entry_at = None
        self.outside_anchor = None
        self.outside_at = None
        self.exit_since = None

    def update(self, now, center, overlap, center_inside):
        outside = not center_inside and overlap <= self.config["outside_overlap"]
        inside = overlap >= self.config["inside_overlap"]
        started, ended = False, False
        if outside:
            if self.entered:
                if self.exit_since is None:
                    self.exit_since = now
                if now-self.exit_since >= self.config["exit_confirm_seconds"]:
                    self.entered = False
                    ended = True
            if not self.entered:
                self.outside_anchor = tuple(center)
                self.outside_at = now
        else:
            self.exit_since = None
        if not self.entered and inside and self.outside_anchor is not None:
            age = now-self.outside_at
            displacement = math.hypot(center[0]-self.outside_anchor[0],center[1]-self.outside_anchor[1])
            if age <= self.config["entry_memory_seconds"] and displacement >= self.config["minimum_displacement"]:
                self.entered = True
                self.episode += 1
                self.entry_at = now
                self.outside_anchor = None
                started = True
        if self.outside_at is not None and now-self.outside_at > self.config["entry_memory_seconds"]:
            self.outside_anchor = None
        return {"entered":self.entered,"episode":self.episode,"new_entry":started,
                "exit_confirmed":ended,"entry_at":self.entry_at}
