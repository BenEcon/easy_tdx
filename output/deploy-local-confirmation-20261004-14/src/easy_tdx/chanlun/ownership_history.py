"""Opt-in delivery projection, not compression or a change to historical rules."""
from copy import deepcopy
from typing import Literal

OwnershipHistoryMode = Literal['full', 'summary']


def ownership_history_summary(version: dict) -> dict:
    """Detached address for replay, never an alias into the current detail."""
    return deepcopy({key: version[key] for key in (
        'id', 'known_index', 'known_date', 'source_segment_indices',
        'highest_completed_internal_level') if key in version})


def summarize_ownership_history(view: dict) -> dict:
    """Keep every history address and full current owners; omit historical detail.

    Full exports remain the default. The UI already replays original input bars
    at a selected confirmation to recover that time's full current-owner detail.
    No server session/cache is involved, and no historical address is truncated.
    """
    current = set(view['current_owner_ids'])
    summaries = [ownership_history_summary(version) for version in view['versions']]
    return {
        **deepcopy({key: value for key, value in view.items() if key != 'versions'}),
        'history_format': 'summary_v1', 'history_summaries': summaries,
        'versions': [deepcopy(v) for v in view['versions'] if v['id'] in current],
    }
