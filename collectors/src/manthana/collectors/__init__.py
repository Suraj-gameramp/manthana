"""Manthana collectors — per-surface adapters that normalize raw transcripts
into ``Turn``s. See ``manthana.collectors.base`` for the seam.

SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from .base import Collector, get, register, registered

__all__ = ["Collector", "register", "get", "registered"]
