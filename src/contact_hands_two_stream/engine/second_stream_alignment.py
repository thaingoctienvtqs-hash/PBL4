"""Align stream 2 with the image that stream 1 receives during training.

The original train_net.py re-reads the image from disk for stream 2, so it
misses the RandomFlip applied by the dataset mapper to stream 1. This helper
feeds stream 2 the very same image tensor (data[0]["image"]) instead.
"""

import numpy as np

_VALID_FORMATS = ("BGR", "RGB")


def mapper_image_to_bgr_hwc(image, input_format="BGR"):
    """Convert a mapper image tensor (CHW) to a contiguous BGR HWC numpy array."""
    if input_format not in _VALID_FORMATS:
        raise ValueError("input_format must be 'BGR' or 'RGB', got {!r}".format(input_format))
    if image.dim() != 3 or image.shape[0] != 3:
        raise ValueError("expected a CHW image with 3 channels, got shape {}".format(tuple(image.shape)))
    array = image.detach().cpu().permute(1, 2, 0).numpy()
    if input_format == "RGB":
        array = array[:, :, ::-1]
    return np.ascontiguousarray(array)


def inference_second_stream_aligned(model2, data, input_format="BGR"):
    """Run stream 2 on the same (resized, possibly flipped) image as stream 1."""
    if len(data) != 1:
        raise ValueError("batch size must be 1, got {}".format(len(data)))
    im = mapper_image_to_bgr_hwc(data[0]["image"], input_format)
    return model2(im)