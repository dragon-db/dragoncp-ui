#!/usr/bin/env python3
"""
Every connector this application knows how to talk to.

Importing this package is what makes an adapter real — each module registers
itself with `@register` on import. Adding a service is a new module here plus
one line below, and nothing outside this package changes.
"""

# Import order is menu order: the registry hands its ids out in the order they
# were registered, and the sidebar renders that. Deliberately not alphabetical —
# Discord is the one that does something today, Sonarr and Radarr are next, and
# Jellyfin is a stub with no decided purpose. Alphabetical put Jellyfin second.
from services.connectors.adapters import discord  # noqa: F401
from services.connectors.adapters import sonarr  # noqa: F401
from services.connectors.adapters import radarr  # noqa: F401
from services.connectors.adapters import jellyfin  # noqa: F401

__all__ = ['discord', 'jellyfin', 'radarr', 'sonarr']
