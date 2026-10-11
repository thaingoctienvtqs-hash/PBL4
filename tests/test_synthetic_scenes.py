import random

import numpy as np

from tools.synthetic_scenes import HEIGHT, WIDTH, _artwork_layer, _box, _hand_mask, _tool_mask, _validate_geometry, _wall


def test_generated_vector_masks_match_safe_near_contact_labels():
    for class_name, maker in (("hand", _hand_mask), ("tool", _tool_mask)):
        for label in ("SAFE", "NEAR", "CONTACT"):
            rng = random.Random(1234)
            canvas = _wall(rng)
            art_mask = _artwork_layer(canvas, np.full((40, 60, 3), 180, dtype=np.uint8), rng)
            interaction_mask = maker(label, rng, _box(art_mask))
            report = _validate_geometry(label, art_mask, interaction_mask)
            assert interaction_mask.shape == (HEIGHT, WIDTH)
            assert report["overlap_pixels"] > 0 if label == "CONTACT" else report["overlap_pixels"] == 0

