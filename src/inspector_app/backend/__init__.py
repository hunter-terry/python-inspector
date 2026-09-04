"""The real, deterministic InspectorBackend implementation.

No AI, cloud model, or paid API is used anywhere in this package. Everything
here is either a subprocess call to a proven open-source static-analysis
tool, or plain Python.
"""
from __future__ import annotations

from .real_backend import RealBackend

__all__ = ["RealBackend"]
