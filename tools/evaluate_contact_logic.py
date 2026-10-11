from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.contact import ContactAnalyzer, ContactSettings, Detection


OUTPUT = ROOT / "dataset/reports/synthetic_logic_evaluation.json"


def evaluate() -> dict:
    settings = ContactSettings(
        confidence_threshold=0.5,
        contact_overlap_threshold=0.2,
        near_distance_threshold=20.0,
        minimum_contact_duration=0.1,
        required_positive_frames=4,
        sliding_window_size=8,
        alert_cooldown=0.0,
    )
    painting = Detection(0, 1.0, (100, 100, 200, 200), 1)
    cases = {
        "SAFE": Detection(2, 0.95, (20, 140, 40, 160), 7),
        "NEAR": Detection(2, 0.95, (202, 120, 218, 136), 7),
        "CONTACT": Detection(2, 0.95, (150, 140, 170, 160), 7),
    }
    results = []
    for label, hand in cases.items():
        analyzer = ContactAnalyzer(settings)
        events = []
        states = []
        for frame_index in range(12):
            result = analyzer.analyze(
                (painting, hand),
                monotonic_time=frame_index / 30.0,
                event_time=datetime.fromtimestamp(frame_index / 30.0, timezone.utc),
            )
            events.extend(result.events)
            states.append(result.state.value)
        predicted_contact = bool(events)
        expected_contact = label == "CONTACT"
        results.append({
            "sample_type": "SYNTHETIC_LOGIC_ONLY",
            "scenario_label": label,
            "expected_contact": expected_contact,
            "predicted_contact": predicted_contact,
            "event_count": len(events),
            "states_seen": sorted(set(states)),
            "pass": predicted_contact == expected_contact,
        })

    true_positive = sum(item["expected_contact"] and item["predicted_contact"] for item in results)
    false_positive = sum(not item["expected_contact"] and item["predicted_contact"] for item in results)
    false_negative = sum(item["expected_contact"] and not item["predicted_contact"] for item in results)
    true_negative = sum(not item["expected_contact"] and not item["predicted_contact"] for item in results)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    report = {
        "sample_type": "SYNTHETIC_LOGIC_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "test_scope": "ContactAnalyzer on hand-supplied geometric detections; no image model, video labels, or real footage involved.",
        "scenarios": results,
        "counts": {"true_positive": int(true_positive), "false_positive": int(false_positive), "false_negative": int(false_negative), "true_negative": int(true_negative)},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "synthetic_event_detection_rate": true_positive / (true_positive + false_negative) if true_positive + false_negative else None,
        "false_alarms_per_hour": None,
        "false_alarms_per_hour_note": "Not meaningful: these short geometric logic cases are not representative labeled video durations.",
        "real_world_artwork_contact_validation": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, ensure_ascii=False))

