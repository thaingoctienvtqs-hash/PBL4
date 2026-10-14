"""Dataset utilities load the Detectron2 stack only when training code uses them."""

__all__ = ["load_voc_hand_instances", "register_pascal_voc"]


def load_voc_hand_instances(*args, **kwargs):
    from .load_data import load_voc_hand_instances as load
    return load(*args, **kwargs)


def register_pascal_voc(*args, **kwargs):
    from .load_data import register_pascal_voc as register
    return register(*args, **kwargs)
