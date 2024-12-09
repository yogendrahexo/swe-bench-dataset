"""'Trace' Jinja template execution to map output back to the raw template.

This is a newer slicing algorithm that handles cases heuristic.py does not.
"""

from dataclasses import dataclass, field
import logging
import regex
from typing import Callable, cast, Dict, List, NamedTuple, Optional

from jinja2 import Environment
from jinja2.environment import Template
from jinja2.exceptions import TemplateSyntaxError

from sqlfluff.core.templaters.base import (
    RawFileSlice,
    TemplatedFileSlice,
)


# Instantiate the templater logger
templater_logger = logging.getLogger("sqlfluff.templater")


class JinjaTrace(NamedTuple):
    """Returned by JinjaTracer.trace()."""

    # Template output
    templated_str: str
    # Raw (i.e. before rendering) Jinja template sliced into tokens
    raw_sliced: List[RawFileSlice]
    # Rendered Jinja template (i.e. output) mapped back to rwa_str source
    sliced_file: List[TemplatedFileSlice]


@dataclass
class RawSliceInfo:
    """JinjaTracer-specific info about each RawFileSlice."""

    unique_alternate_id: Optional[str]
    alternate_code: Optional[str]
    next_slice_indices: List[int] = field(default_factory=list)
    inside_block: bool = field(default=False)  # {% block %}


class JinjaTracer:
    """Records execution path of a Jinja template."""

    def __init__(
        self,
        raw_str: str,
        raw_sliced: List[RawFileSlice],
        raw_slice_info: Dict[RawFileSlice, RawSliceInfo],
        sliced_file: List[TemplatedFileSlice],
        make_template: Callable[[str], Template],
    ):
        # Input
        self.raw_str = raw_str
        self.raw_sliced = raw_sliced
        self.raw_slice_info = raw_slice_info
        self.sliced_file = sliced_file
        self.make_template = make_template

        # Internal bookkeeping
        self.program_counter: int = 0
        self.source_idx: int = 0

    def trace(self, append_to_templated: str = "") -> JinjaTrace:
        """Executes raw_str. Returns template output and trace."""
        trace_template_str = "".join(
            cast(str, self.raw_slice_info[rs].alternate_code)
            if self.raw_slice_info[rs].alternate_code is not None
            else rs.raw
            for rs in self.raw_sliced
        )
        trace_template = self.make_template(trace_template_str)
        trace_template_output = trace_template.render()
        # Split output by section. Each section has two possible formats.
        trace_entries = list(regex.finditer(r"\0", trace_template_output))
        for match_idx, match in enumerate(trace_entries):
            pos1 = match.span()[0]
            try:
                pos2 = trace_entries[match_idx + 1].span()[0]
            except IndexError:
                pos2 = len(trace_template_output)
            p = trace_template_output[pos1 + 1 : pos2]
            m_id = regex.match(r"^([0-9a-f]+)(_(\d+))?", p)
            if not m_id:
                raise ValueError(  # pragma: no cover
                    "Internal error. Trace template output does not match expected "
                    "format."
                )
            if m_id.group(3):
                # E.g. "00000000000000000000000000000001_83". The number after
                # "_" is the length (in characters) of a corresponding literal
                # in raw_str.
                value = [m_id.group(1), int(m_id.group(3)), True]
            else:
                # E.g. "00000000000000000000000000000002 a < 10". The characters
                # after the slice ID are executable code from raw_str.
                value = [m_id.group(0), p[len(m_id.group(0)) + 1 :], False]
            alt_id, content_info, literal = value
            target_slice_idx = self.find_slice_index(alt_id)
            slice_length = content_info if literal else len(str(content_info))
            target_inside_block = self.raw_slice_info[
                self.raw_sliced[target_slice_idx]
            ].inside_block
            if not target_inside_block:
                # Normal case: Walk through the template.
                self.move_to_slice(target_slice_idx, slice_length)
            else:
                # {% block %} executes code elsewhere in the template but does
                # not move there. It's a bit like macro invocation.
                self.record_trace(slice_length, target_slice_idx)

        # TRICKY: The 'append_to_templated' parameter is only used by the dbt
        # templater, passing "\n" for this parameter if we need to add one back.
        # (The Jinja templater does not pass this parameter, so
        # 'append_to_templated' gets the default value of "", empty string.)
        # For more detail, see the comments near the call to slice_file() in
        # plugins/sqlfluff-templater-dbt/sqlfluff_templater_dbt/templater.py.
        templated_str = self.make_template(self.raw_str).render() + append_to_templated
        return JinjaTrace(templated_str, self.raw_sliced, self.sliced_file)

    def find_slice_index(self, slice_identifier) -> int:
        """Given a slice identifier, return its index.

        A slice identifier is a string like 00000000000000000000000000000002.
        """
        raw_slices_search_result = [
            idx
            for idx, rs in enumerate(self.raw_sliced)
            if self.raw_slice_info[rs].unique_alternate_id == slice_identifier
        ]
        if len(raw_slices_search_result) != 1:
            raise ValueError(  # pragma: no cover
                f"Internal error. Unable to locate slice for {slice_identifier}."
            )
        return raw_slices_search_result[0]

    def move_to_slice(self, target_slice_idx, target_slice_length):
        """Given a template location, walk execution to that point."""
        while self.program_counter < len(self.raw_sliced):
            self.record_trace(
                target_slice_length if self.program_counter == target_slice_idx else 0
            )
            current_raw_slice = self.raw_sliced[self.program_counter]
            if self.program_counter == target_slice_idx:
                # Reached the target slice. Go to next location and stop.
                self.program_counter += 1
                break
            else:
                # Choose the next step.

                # We could simply go to the next slice (sequential execution).
                candidates = [self.program_counter + 1]
                # If we have other options, consider those.
                for next_slice_idx in self.raw_slice_info[
                    current_raw_slice
                ].next_slice_indices:
                    # It's a valid possibility if it does not take us past the
                    # target.
                    if next_slice_idx <= target_slice_idx:
                        candidates.append(next_slice_idx)
                # Choose the candidate that takes us closest to the target.
                candidates.sort(key=lambda c: abs(target_slice_idx - c))
                self.program_counter = candidates[0]

    def record_trace(self, target_slice_length, slice_idx=None, slice_type=None):
        """Add the specified (default: current) location to the trace."""
        if slice_idx is None:
            slice_idx = self.program_counter
        if slice_type is None:
            slice_type = self.raw_sliced[slice_idx].slice_type
        self.sliced_file.append(
            TemplatedFileSlice(
                slice_type,
                slice(
                    self.raw_sliced[slice_idx].source_idx,
                    self.raw_sliced[slice_idx + 1].source_idx
                    if slice_idx + 1 < len(self.raw_sliced)
                    else len(self.raw_str),
                ),
                slice(self.source_idx, self.source_idx + target_slice_length),
            )
        )
        if slice_type in ("literal", "templated"):
            self.source_idx += target_slice_length


class JinjaAnalyzer:
    """Analyzes a Jinja template to prepare for tracing."""

    re_open_tag = regex.compile(r"^\s*({[{%])[\+\-]?\s*")
    re_close_tag = regex.compile(r"\s*[\+\-]?([}%]})\s*$")

    def __init__(self, raw_str: str, env: Environment):
        # Input
        self.raw_str: str = raw_str
        self.env = env

        # Output
        self.raw_sliced: List[RawFileSlice] = []
        self.raw_slice_info: Dict[RawFileSlice, RawSliceInfo] = {}
        self.sliced_file: List[TemplatedFileSlice] = []

        # Internal bookkeeping
        self.slice_id: int = 0
        # {% set %} or {% macro %} or {% call %}
        self.inside_set_macro_or_call: bool = False
        self.inside_block = False  # {% block %}
        self.stack: List[int] = []
        self.idx_raw: int = 0

    def next_slice_id(self) -> str:
        """Returns a new, unique slice ID."""
        result = "{0:#0{1}x}".format(self.slice_id, 34)[2:]
        self.slice_id += 1
        return result

    def slice_info_for_literal(self, length, prefix="") -> RawSliceInfo:
        """Returns a RawSliceInfo for a literal.

        In the alternate template, literals are replaced with a uniquely
        numbered, easy-to-parse literal. JinjaTracer uses this output as
        a "breadcrumb trail" to deduce the execution path through the template.

        This is important even if the original literal (i.e. in the raw SQL
        file) was empty, as is the case when Jinja whitespace control is used
        (e.g. "{%- endif -%}"), because fewer breadcrumbs means JinjaTracer has
        to *guess* the path, in which case it assumes simple, straight-line
        execution, which can easily be wrong with loops and conditionals.
        """
        unique_alternate_id = self.next_slice_id()
        alternate_code = f"\0{prefix}{unique_alternate_id}_{length}"
        return self.make_raw_slice_info(
            unique_alternate_id, alternate_code, inside_block=self.inside_block
        )

    def update_inside_set_call_macro_or_block(
        self,
        block_type: str,
        trimmed_parts: List[str],
        m_open: Optional[regex.Match],
        m_close: Optional[regex.Match],
        tag_contents: List[str],
    ) -> Optional[RawSliceInfo]:
        """Based on block tag, update whether in a set/call/macro/block section."""
        if block_type == "block_start" and trimmed_parts[0] in (
            "block",
            "call",
            "macro",
            "set",
        ):
            # Jinja supports two forms of {% set %}:
            # - {% set variable = value %}
            # - {% set variable %}value{% endset %}
            # https://jinja.palletsprojects.com/en/2.10.x/templates/#block-assignments
            # When the second format is used, set one of the fields
            # 'inside_set_or_macro' or 'inside_block' to True. This info is
            # used elsewhere, as other code inside these regions require
            # special handling. (Generally speaking, JinjaAnalyzer ignores
            # the contents of these blocks, treating them like opaque templated
            # regions.)
            try:
                # Entering a set/macro block. Build a source string consisting
                # of just this one Jinja command and see if it parses. If so,
                # it's a standalone command. OTOH, if it fails with "Unexpected
                # end of template", it was the opening command for a block.
                self.env.from_string(
                    f"{self.env.block_start_string} {' '.join(trimmed_parts)} "
                    f"{self.env.block_end_string}"
                )
            except TemplateSyntaxError as e:
                if (
                    isinstance(e.message, str)
                    and "Unexpected end of template" in e.message
                ):
                    # It was opening a block, thus we're inside a set, macro, or
                    # block.
                    if trimmed_parts[0] == "block":
                        self.inside_block = True
                    else:
                        result = None
                        if trimmed_parts[0] == "call":
                            assert m_open and m_close
                            result = self.track_call(m_open, m_close, tag_contents)
                        self.inside_set_macro_or_call = True
                        return result
                else:
                    raise  # pragma: no cover
        elif block_type == "block_end":
            if trimmed_parts[0] in ("endcall", "endmacro", "endset"):
                # Exiting a set or macro or block.
                self.inside_set_macro_or_call = False
            elif trimmed_parts[0] == "endblock":
                # Exiting a {% block %} block.
                self.inside_block = False
        return None

    def make_raw_slice_info(
        self,
        unique_alternate_id: Optional[str],
        alternate_code: Optional[str],
        inside_block: bool = False,
    ) -> RawSliceInfo:
        """Create RawSliceInfo as given, or "empty" if in set/macro block."""
        if not self.inside_set_macro_or_call:
            return RawSliceInfo(unique_alternate_id, alternate_code, [], inside_block)
        else:
            return RawSliceInfo(None, None, [], False)

    # We decide the "kind" of element we're dealing with using its _closing_
    # tag rather than its opening tag. The types here map back to similar types
    # of sections in the python slicer.
    block_types = {
        "variable_end": "templated",
        "block_end": "block",
        "comment_end": "comment",
        # Raw tags should behave like blocks. Note that
        # raw_end and raw_begin are whole tags rather
        # than blocks and comments where we get partial
        # tags.
        "raw_end": "block",
        "raw_begin": "block",
    }

    def analyze(self, make_template: Callable[[str], Template]) -> JinjaTracer:
        """Slice template in jinja."""
        # str_buff and str_parts are two ways we keep track of tokens received
        # from Jinja. str_buff concatenates them together, while str_parts
        # accumulates the individual strings. We generally prefer using
        # str_parts. That's because Jinja doesn't just split on whitespace, so
        # by keeping tokens as Jinja returns them, the code is more robust.
        # Consider the following:
        #   {% set col= "col1" %}
        # Note there's no space after col. Jinja splits this up for us. If we
        # simply concatenated the parts together and later split on whitespace,
        # we'd need some ugly, fragile logic to handle various whitespace
        # possibilities:
        #   {% set col= "col1" %}
        #   {% set col = "col1" %}
        #   {% set col ="col1" %}
        # By using str_parts and letting Jinja handle this, it just works.

        str_buff = ""
        str_parts = []

        # https://jinja.palletsprojects.com/en/2.11.x/api/#jinja2.Environment.lex
        block_idx = 0
        last_elem_type = None
        for _, elem_type, raw in self.env.lex(self.raw_str):
            if last_elem_type == "block_end" or elem_type == "block_start":
                block_idx += 1
            last_elem_type = elem_type

            if elem_type == "data":
                self.track_literal(raw, block_idx)
                continue
            str_buff += raw
            str_parts.append(raw)

            if elem_type.endswith("_begin"):
                self.handle_left_whitespace_stripping(raw, block_idx)

            raw_slice_info: RawSliceInfo = self.make_raw_slice_info(None, None)
            tag_contents = []
            # raw_end and raw_begin behave a little differently in
            # that the whole tag shows up in one go rather than getting
            # parts of the tag at a time.
            m_open = None
            m_close = None
            if elem_type.endswith("_end") or elem_type == "raw_begin":
                block_type = self.block_types[elem_type]
                block_subtype = None
                # Handle starts and ends of blocks
                if block_type in ("block", "templated"):
                    m_open = self.re_open_tag.search(str_parts[0])
                    m_close = self.re_close_tag.search(str_parts[-1])
                    if m_open and m_close:
                        tag_contents = self.extract_tag_contents(
                            str_parts, m_close, m_open, str_buff
                        )

                    if block_type == "block" and tag_contents:
                        block_type, block_subtype = self.extract_block_type(
                            tag_contents[0], block_subtype
                        )
                    if block_type == "templated" and tag_contents:
                        assert m_open and m_close
                        raw_slice_info = self.track_templated(
                            m_open, m_close, tag_contents
                        )
                raw_slice_info_temp = self.update_inside_set_call_macro_or_block(
                    block_type, tag_contents, m_open, m_close, tag_contents
                )
                if raw_slice_info_temp:
                    raw_slice_info = raw_slice_info_temp
                m_strip_right = regex.search(
                    r"\s+$", raw, regex.MULTILINE | regex.DOTALL
                )
                if elem_type.endswith("_end") and raw.startswith("-") and m_strip_right:
                    # Right whitespace was stripped after closing block. Split
                    # off the trailing whitespace into a separate slice. The
                    # desired behavior is to behave similarly as the left
                    # stripping case. Note that the stakes are a bit lower here,
                    # because lex() hasn't *omitted* any characters from the
                    # strings it returns, it has simply grouped them differently
                    # than we want.
                    trailing_chars = len(m_strip_right.group(0))
                    self.raw_sliced.append(
                        RawFileSlice(
                            str_buff[:-trailing_chars],
                            block_type,
                            self.idx_raw,
                            block_subtype,
                            block_idx,
                        )
                    )
                    self.raw_slice_info[self.raw_sliced[-1]] = raw_slice_info
                    slice_idx = len(self.raw_sliced) - 1
                    self.idx_raw += len(str_buff) - trailing_chars
                    self.raw_sliced.append(
                        RawFileSlice(
                            str_buff[-trailing_chars:],
                            "literal",
                            self.idx_raw,
                            None,
                            block_idx,
                        )
                    )
                    self.raw_slice_info[
                        self.raw_sliced[-1]
                    ] = self.slice_info_for_literal(0)
                    self.idx_raw += trailing_chars
                else:
                    self.raw_sliced.append(
                        RawFileSlice(
                            str_buff,
                            block_type,
                            self.idx_raw,
                            block_subtype,
                            block_idx,
                        )
                    )
                    self.raw_slice_info[self.raw_sliced[-1]] = raw_slice_info
                    slice_idx = len(self.raw_sliced) - 1
                    self.idx_raw += len(str_buff)
                if block_type.startswith("block"):
                    self.track_block_start(block_type, tag_contents[0])
                    self.track_block_end(block_type, tag_contents[0])
                    self.update_next_slice_indices(
                        slice_idx, block_type, tag_contents[0]
                    )
                str_buff = ""
                str_parts = []
        return JinjaTracer(
            self.raw_str,
            self.raw_sliced,
            self.raw_slice_info,
            self.sliced_file,
            make_template,
        )

    def track_templated(
        self, m_open: regex.Match, m_close: regex.Match, tag_contents: List[str]
    ) -> RawSliceInfo:
        """Compute tracking info for Jinja templated region, e.g. {{ foo }}."""
        unique_alternate_id = self.next_slice_id()
        open_ = m_open.group(1)
        close_ = m_close.group(1)
        # Here, we still need to evaluate the original tag contents, e.g. in
        # case it has intentional side effects, but also return a slice ID
        # for tracking.
        alternate_code = (
            f"\0{unique_alternate_id} {open_} " f"{''.join(tag_contents)} {close_}"
        )
        return self.make_raw_slice_info(unique_alternate_id, alternate_code)

    def track_call(
        self, m_open: regex.Match, m_close: regex.Match, tag_contents: List[str]
    ):
        """Set up tracking for "{% call ... %}"."""
        unique_alternate_id = self.next_slice_id()
        open_ = m_open.group(1)
        close_ = m_close.group(1)
        # Here, we still need to evaluate the original tag contents, e.g. in
        # case it has intentional side effects, but also return a slice ID
        # for tracking.
        alternate_code = (
            f"\0{unique_alternate_id} {open_} " f"{''.join(tag_contents)} {close_}"
        )
        return self.make_raw_slice_info(unique_alternate_id, alternate_code)

    def track_literal(self, raw: str, block_idx: int) -> None:
        """Set up tracking for a Jinja literal."""
        self.raw_sliced.append(
            RawFileSlice(
                raw,
                "literal",
                self.idx_raw,
                None,
                block_idx,
            )
        )
        # Replace literal text with a unique ID.
        self.raw_slice_info[self.raw_sliced[-1]] = self.slice_info_for_literal(
            len(raw), ""
        )
        self.idx_raw += len(raw)

    @staticmethod
    def extract_block_type(tag_name, block_subtype):
        """Determine block type."""
        # :TRICKY: Syntactically, the Jinja {% include %} directive looks like
        # a block, but its behavior is basically syntactic sugar for
        # {{ open("somefile).read() }}. Thus, treat it as templated code.
        if tag_name == "include":
            block_type = "templated"
        elif tag_name.startswith("end"):
            block_type = "block_end"
        elif tag_name.startswith("el"):
            # else, elif
            block_type = "block_mid"
        else:
            block_type = "block_start"
            if tag_name == "for":
                block_subtype = "loop"
        return block_type, block_subtype

    @staticmethod
    def extract_tag_contents(
        str_parts: List[str],
        m_close: regex.Match,
        m_open: regex.Match,
        str_buff: str,
    ) -> List[str]:
        """Given Jinja tag info, return the stuff inside the braces.

        I.e. Trim off the brackets and the whitespace.
        """
        if len(str_parts) >= 3:
            # Handle a tag received as individual parts.
            trimmed_parts = str_parts[1:-1]
            if trimmed_parts[0].isspace():
                del trimmed_parts[0]
            if trimmed_parts[-1].isspace():
                del trimmed_parts[-1]
        else:
            # Handle a tag received in one go.
            trimmed_content = str_buff[len(m_open.group(0)) : -len(m_close.group(0))]
            trimmed_parts = trimmed_content.split()
        return trimmed_parts

    def track_block_start(self, block_type: str, tag_name: str) -> None:
        """On starting a 'call' block, set slice_type to "templated"."""
        if block_type == "block_start" and tag_name == "call":
            # Replace RawSliceInfo for this slice with one that has block_type
            # "templated".
            old_raw_file_slice = self.raw_sliced[-1]
            self.raw_sliced[-1] = old_raw_file_slice._replace(slice_type="templated")

            # Move existing raw_slice_info entry since it's keyed by RawFileSlice.
            self.raw_slice_info[self.raw_sliced[-1]] = self.raw_slice_info[
                old_raw_file_slice
            ]
            del self.raw_slice_info[old_raw_file_slice]

    def track_block_end(self, block_type: str, tag_name: str) -> None:
        """On ending a 'for' or 'if' block, set up tracking."""
        if block_type == "block_end" and tag_name in (
            "endfor",
            "endif",
        ):
            # Replace RawSliceInfo for this slice with one that has alternate ID
            # and code for tracking. This ensures, for instance, that if a file
            # ends with "{% endif %} (with no newline following), that we still
            # generate a TemplateSliceInfo for it.
            unique_alternate_id = self.next_slice_id()
            alternate_code = f"{self.raw_sliced[-1].raw}\0{unique_alternate_id}_0"
            self.raw_slice_info[self.raw_sliced[-1]] = self.make_raw_slice_info(
                unique_alternate_id, alternate_code
            )

    def update_next_slice_indices(
        self, slice_idx: int, block_type: str, tag_name: str
    ) -> None:
        """Based on block, update conditional jump info."""
        if block_type == "block_start" and tag_name in (
            "for",
            "if",
        ):
            self.stack.append(slice_idx)
        elif block_type == "block_mid":
            # Record potential forward jump over this block.
            self.raw_slice_info[
                self.raw_sliced[self.stack[-1]]
            ].next_slice_indices.append(slice_idx)
            self.stack.pop()
            self.stack.append(slice_idx)
        elif block_type == "block_end" and tag_name in (
            "endfor",
            "endif",
        ):
            if not self.inside_set_macro_or_call:
                # Record potential forward jump over this block.
                self.raw_slice_info[
                    self.raw_sliced[self.stack[-1]]
                ].next_slice_indices.append(slice_idx)
                if self.raw_sliced[self.stack[-1]].slice_subtype == "loop":
                    # Record potential backward jump to the loop beginning.
                    self.raw_slice_info[
                        self.raw_sliced[slice_idx]
                    ].next_slice_indices.append(self.stack[-1] + 1)
                self.stack.pop()

    def handle_left_whitespace_stripping(self, token: str, block_idx: int) -> None:
        """If block open uses whitespace stripping, record it.

        When a "begin" tag (whether block, comment, or data) uses whitespace
        stripping
        (https://jinja.palletsprojects.com/en/3.0.x/templates/#whitespace-control)
        the Jinja lex() function handles this by discarding adjacent whitespace
        from 'raw_str'. For more insight, see the tokeniter() function in this file:
        https://github.com/pallets/jinja/blob/main/src/jinja2/lexer.py

        We want to detect and correct for this in order to:
        - Correctly update "idx" (if this is wrong, that's a potential
          DISASTER because lint fixes use this info to update the source file,
          and incorrect values often result in CORRUPTING the user's file so
          it's no longer valid SQL. :-O
        - Guarantee that the slices we return fully "cover" the contents of
          'in_str'.

        We detect skipped characters by looking ahead in in_str for the token
        just returned from lex(). The token text will either be at the current
        'idx_raw' position (if whitespace stripping did not occur) OR it'll be
        farther along in 'raw_str', but we're GUARANTEED that lex() only skips
        over WHITESPACE; nothing else.
        """
        # Find the token returned. Did lex() skip over any characters?
        num_chars_skipped = self.raw_str.index(token, self.idx_raw) - self.idx_raw
        if not num_chars_skipped:
            return

        # Yes. It skipped over some characters. Compute a string
        # containing the skipped characters.
        skipped_str = self.raw_str[self.idx_raw : self.idx_raw + num_chars_skipped]

        # Sanity check: Verify that Jinja only skips over
        # WHITESPACE, never anything else.
        if not skipped_str.isspace():  # pragma: no cover
            templater_logger.warning(
                "Jinja lex() skipped non-whitespace: %s", skipped_str
            )
        # Treat the skipped whitespace as a literal.
        self.raw_sliced.append(
            RawFileSlice(skipped_str, "literal", self.idx_raw, None, block_idx)
        )
        self.raw_slice_info[self.raw_sliced[-1]] = self.slice_info_for_literal(0)
        self.idx_raw += num_chars_skipped
