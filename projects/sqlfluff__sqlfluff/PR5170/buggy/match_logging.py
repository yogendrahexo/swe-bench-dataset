"""Classes to help with match logging."""

import logging
from typing import TYPE_CHECKING, Any, Tuple

from sqlfluff.core.parser.helpers import join_segments_raw_curtailed

if TYPE_CHECKING:  # pragma: no cover
    from sqlfluff.core.parser import BaseSegment
    from sqlfluff.core.parser.context import ParseContext


class LateLoggingObject:
    """A basic late binding log object for parse_match_logging.

    This allows us to defer the string manipulation involved
    until actually required by the logger.
    """

    __slots__ = "v_level", "logger", "msg"

    def __init__(self, logger: logging.Logger, msg: str, v_level: int = 3) -> None:
        self.v_level = v_level
        self.logger = logger
        self.msg = msg

    def __str__(self) -> str:  # pragma: no cover TODO?
        """Actually materialise the string."""
        return self.msg

    def log(self) -> None:
        """Actually log this object."""
        # Otherwise carry on...
        if self.v_level == 3:
            self.logger.info(self)
        elif self.v_level == 4:
            self.logger.debug(self)


class ParseMatchLogObject(LateLoggingObject):
    """A late binding log object for parse_match_logging.

    This allows us to defer the string manipulation involved
    until actually required by the logger.
    """

    __slots__ = [
        "context",
        "grammar",
        "func",
        "kwargs",
    ]

    def __init__(
        self,
        parse_context: "ParseContext",
        grammar: str,
        func: str,
        msg: str,
        v_level: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(v_level=v_level, logger=parse_context.logger, msg=msg)
        self.context = parse_context
        self.grammar = grammar
        self.func = func
        self.kwargs = kwargs

    def __str__(self) -> str:
        """Actually materialise the string."""
        symbol = self.kwargs.pop("symbol", "")
        s = "[PD:{:<2} MD:{:<2}]\t{:<50}\t{:<20}\t{:<4}".format(
            self.context.parse_depth,
            self.context.match_depth,
            ("." * self.context.match_depth) + str(self.context.match_segment),
            f"{self.grammar:.5}.{self.func} {self.msg}",
            symbol,
        )
        if self.kwargs:
            s += "\t[{}]".format(
                ", ".join(
                    f"{k}={repr(v) if isinstance(v, str) else str(v)}"
                    for k, v in self.kwargs.items()
                )
            )
        return s


def parse_match_logging(
    grammar: str,
    func: str,
    msg: str,
    parse_context: "ParseContext",
    v_level: int = 3,
    **kwargs: Any,
) -> None:
    """Log in a particular consistent format for use while matching."""
    # Make a late bound log object so we only do the string manipulation when we need
    # to.
    ParseMatchLogObject(
        parse_context, grammar, func, msg, v_level=v_level, **kwargs
    ).log()


class LateBoundJoinSegmentsCurtailed:
    """Object to delay `join_segments_raw_curtailed` until later.

    This allows us to defer the string manipulation involved
    until actually required by the logger.
    """

    def __init__(self, segments: Tuple["BaseSegment", ...]) -> None:
        self.segments = segments

    def __str__(self) -> str:
        return repr(join_segments_raw_curtailed(self.segments))
