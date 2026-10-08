"""Prism v0.1: independent entity/action policy-value network."""

from .data import PrismDataset, collate, collate_states
from .model import PrismModel, predict

__all__ = [
    "PrismModel", "PrismDataset", "collate", "collate_states", "predict",
    "export_weights", "load_weights",
]


def __getattr__(name):
    # Keep `python -m training.prism.export` free of runpy double-import warnings.
    if name in ("export_weights", "load_weights"):
        from . import export
        return getattr(export, name)
    raise AttributeError(name)
