"""Helpers for the parser module."""

from typing import Tuple, List, Any, Iterator, TYPE_CHECKING

from sqlfluff.core.errors import SQLParseError
from sqlfluff.core.string_helpers import curtail_string

if TYPE_CHECKING:
    from sqlfluff.core.parser.segments import BaseSegment  # pragma: no cover


def join_segments_raw(segments: Tuple["BaseSegment", ...]) -> str:
    """Make a string from the joined `raw` attributes of an iterable of segments."""
    return "".join(s.raw for s in segments)


def join_segments_raw_curtailed(segments: Tuple["BaseSegment", ...], length=20) -> str:
    """Make a string up to a certain length from an iterable of segments."""
    return curtail_string(join_segments_raw(segments), length=length)


def check_still_complete(
    segments_in: Tuple["BaseSegment", ...],
    matched_segments: Tuple["BaseSegment", ...],
    unmatched_segments: Tuple["BaseSegment", ...],
) -> bool:
    """Check that the segments in are the same as the segments out."""
    initial_str = join_segments_raw(segments_in)
    current_str = join_segments_raw(matched_segments + unmatched_segments)

    if initial_str != current_str:
        raise SQLParseError(
            f"Could not parse: {current_str}",
            segment=unmatched_segments[0],
        )
    return True


def trim_non_code_segments(
    segments: Tuple["BaseSegment", ...]
) -> Tuple[
    Tuple["BaseSegment", ...], Tuple["BaseSegment", ...], Tuple["BaseSegment", ...]
]:
    """Take segments and split off surrounding non-code segments as appropriate.

    We use slices to avoid creating too many unnecessary tuples.
    """
    pre_idx = 0
    seg_len = len(segments)
    post_idx = seg_len

    if segments:
        seg_len = len(segments)

        # Trim the start
        while pre_idx < seg_len and not segments[pre_idx].is_code:
            pre_idx += 1

        # Trim the end
        while post_idx > pre_idx and not segments[post_idx - 1].is_code:
            post_idx -= 1

    return segments[:pre_idx], segments[pre_idx:post_idx], segments[post_idx:]


def iter_indices(seq: List, val: Any) -> Iterator[int]:
    """Iterate all indices in a list that val occurs at.

    Args:
        seq (list): A list to look for indices in.
        val: What to look for.

    Yields:
        int: The index of val in seq.

    Examples:
        The function works like str.index() but iterates all
        the results rather than returning the first.

        >>> print([i for i in iter_indices([1, 0, 2, 3, 2], 2)])
        [2, 4]
    """
    for idx, el in enumerate(seq):
        if el == val:
            yield idx
