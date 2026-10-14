"""Translate ContactHands scores into cautious, ROI-aware status reports."""

from .geometry import intersection_over_box_area, intersection_over_box_area_polygon

CONTACT_STATES = ("No-Contact", "Self-Contact", "Other-Person-Contact", "Object-Contact")
CONTACT_KEYS = ("no_contact", "self_contact", "other_person_contact", "object_contact")


def analyze_predictions(boxes, detection_scores, contact_scores, roi, thresholds,
                        minimum_roi_overlap=0.02, roi_polygon=None):
    """Summarize model output without treating a model label as proof of touching.

    ContactHands emits four independent sigmoid scores for each detected hand.
    A suspected in-ROI contact is raised only when a contact score crosses its
    configured threshold and that hand box overlaps the configured painting ROI.
    """
    if len(boxes) != len(detection_scores) or len(boxes) != len(contact_scores):
        raise ValueError("hand boxes, detection scores, and contact scores must align")
    if not 0.0 <= float(minimum_roi_overlap) <= 1.0:
        raise ValueError("minimum ROI overlap must be between 0 and 1")
    if not boxes:
        return {
            "status": "OK", "condition": "NO_HANDS", "event_kind": None,
            "message": "No hand detections in this frame", "hands": [],
        }

    normalized_thresholds = {}
    for key in CONTACT_KEYS:
        if key not in thresholds:
            raise ValueError("missing contact threshold: {}".format(key))
        value = float(thresholds[key])
        if not 0.0 <= value <= 1.0:
            raise ValueError("threshold {} must be between 0 and 1".format(key))
        normalized_thresholds[key] = value

    hands = []
    in_roi_candidates = []
    any_contact = False
    for index, (box, detection_score, raw_scores) in enumerate(
            zip(boxes, detection_scores, contact_scores)):
        if len(raw_scores) != 4:
            raise ValueError("each hand must have four ContactHands scores")
        scores = [float(value) for value in raw_scores]
        if any(value < 0.0 or value > 1.0 for value in scores):
            raise ValueError("ContactHands scores must be between 0 and 1")
        overlap = (intersection_over_box_area_polygon(box, roi_polygon)
                   if roi_polygon is not None else intersection_over_box_area(box, roi))
        candidates = [
            CONTACT_STATES[i] for i in range(1, 4)
            if scores[i] >= normalized_thresholds[CONTACT_KEYS[i]]
        ]
        any_contact = any_contact or bool(candidates)
        hand = {
            "index": index,
            "box": [float(value) for value in box],
            "detection_score": float(detection_score),
            "contact_scores": dict(zip(CONTACT_STATES, scores)),
            "contact_candidates": candidates,
            "roi_overlap": overlap,
        }
        hands.append(hand)
        if candidates and overlap >= minimum_roi_overlap:
            in_roi_candidates.append(hand)

    if in_roi_candidates:
        return {
            "status": "CANDIDATE", "condition": "CONTACT_CANDIDATE_IN_ROI",
            "event_kind": "AI_CONTACT_SUSPECTED_IN_ROI",
            "message": "AI contact candidate overlaps the painting ROI; temporal confirmation pending; verify the image",
            "hands": hands,
            "candidate_hand_indices": [hand["index"] for hand in in_roi_candidates],
        }
    if any_contact:
        return {
            "status": "OK", "condition": "CONTACT_CANDIDATE_OUTSIDE_ROI",
            "event_kind": None,
            "message": "Contact candidate detected outside the painting ROI",
            "hands": hands,
        }
    return {
        "status": "OK", "condition": "HANDS_NO_CONTACT",
        "event_kind": None,
        "message": "Hands detected; no contact score crossed its configured threshold",
        "hands": hands,
    }



def advance_track_contact(track, hand, now, alert_settings, object_contact_threshold,
                          minimum_roi_overlap, roi_enabled=True):
    """Update one hand's contact window and state; caller owns box association."""
    observed = hand is not None
    score = 0.0
    overlap = float(track.get("roi_overlap", 0.0))
    if observed:
        score = float(hand["contact_scores"].get("Object-Contact", 0.0))
        overlap = float(hand["roi_overlap"])
        track["last_object_contact_score"] = score
        track["last_contact_overlap"] = overlap

    in_roi = bool(track.get("currently_in_roi", False))
    valid = bool(roi_enabled and observed and in_roi
                 and overlap >= minimum_roi_overlap
                 and score >= object_contact_threshold)
    window = int(alert_settings["history_window_frames"])
    history = track.setdefault("contact_history", [])
    history.append(valid)
    if len(history) > window:
        del history[:-window]
    positive_count = sum(1 for value in history if value)

    clear_after = float(alert_settings["clear_after_seconds"])
    if valid:
        last = track.get("last_contact_at")
        if last is None or now - last > clear_after:
            track["contact_started_at"] = now
        track["last_contact_at"] = now
        track["last_object_contact_score"] = score
        track["last_contact_overlap"] = overlap
        if score >= float(alert_settings["fast_contact_score"]):
            track["high_contact_streak"] = track.get("high_contact_streak", 0) + 1
        else:
            track["high_contact_streak"] = 0
    else:
        track["high_contact_streak"] = 0

    if track.get("alert_active", False):
        last = track.get("last_contact_at")
        expired = last is None or now - last >= clear_after
        if not in_roi or expired:
            track["alert_active"] = False
            track["cooldown_until"] = now + float(alert_settings["cooldown_seconds"])
            track["contact_history"] = []
            track["state"] = "COOLDOWN"
            reason = "ROI exited" if not in_roi else "contact evidence cleared"
            track["state_reason"] = reason
            return {"state": "COOLDOWN", "valid_contact": valid,
                    "positive_frames": 0, "alert_started": False,
                    "reason": reason, "object_contact_score": score,
                    "roi_overlap": overlap}
        track["state"] = "ALERT"
        reason = track.get("alert_reason", "contact evidence persists")
        return {"state": "ALERT", "valid_contact": valid,
                "positive_frames": positive_count, "alert_started": False,
                "reason": reason, "object_contact_score": score,
                "roi_overlap": overlap}

    if now < float(track.get("cooldown_until", 0.0)):
        track["state"] = "COOLDOWN"
        return {"state": "COOLDOWN", "valid_contact": valid,
                "positive_frames": positive_count, "alert_started": False,
                "reason": "per-track cooldown", "object_contact_score": score,
                "roi_overlap": overlap}

    fast = (valid and track.get("high_contact_streak", 0)
            >= int(alert_settings["fast_contact_consecutive_frames"]))
    last = track.get("last_contact_at")
    recent = last is not None and now - last < clear_after
    window_ok = positive_count >= int(alert_settings["minimum_contact_roi_frames"])
    entered = bool(track.get("ever_entered_roi", False))
    reason = ""
    if in_roi and entered and fast:
        reason = "high_object_contact_{} consecutive frames".format(
            alert_settings["fast_contact_consecutive_frames"])
    elif in_roi and entered and window_ok and recent:
        reason = "object_contact_{}_of_{}_frames".format(positive_count, window)

    if reason:
        track["alert_active"] = True
        track["alert_reason"] = reason
        track["alert_at"] = now
        track["state"] = "ALERT"
        track["state_reason"] = reason
        return {"state": "ALERT", "valid_contact": valid,
                "positive_frames": positive_count, "alert_started": True,
                "reason": reason, "object_contact_score": score,
                "roi_overlap": overlap}

    if not in_roi:
        state, reason = "OUTSIDE_ROI", "hand outside painting ROI"
    elif valid or (positive_count and recent):
        state = "CANDIDATE"
        reason = "awaiting ROI entry" if not entered else "temporal confirmation pending"
    else:
        state, reason = "NO_CONTACT", "no Object-Contact evidence in ROI"
    track["state"] = state
    track["state_reason"] = reason
    return {"state": state, "valid_contact": valid,
            "positive_frames": positive_count, "alert_started": False,
            "reason": reason, "object_contact_score": score,
            "roi_overlap": overlap}
