"""'Trace' Jinja template execution to map output back to the raw template.

This is a newer slicing algorithm that handles cases heuristic.py does not.
"""

import logging
import regex
from typing import Callable, cast, Dict, List, NamedTuple, Optional

from jinja2 import Environment
from jinja2.environment import Template

from sqlfluff.core.templaters.base import (
    RawFileSlice,
    TemplatedFileSlice,
)


# Instantiate the templater logger
templater_logger = logging.getLogger("sqlfluff.templater")


class JinjaTrace(NamedTuple):
    """Returned by JinjaTracer.process()."""

    # Template output
    templated_str: str
    # Raw (i.e. before rendering) Jinja template sliced into tokens
    raw_sliced: List[RawFileSlice]
    # Rendered Jinja template (i.e. output) mapped back to rwa_str source
    sliced_file: List[TemplatedFileSlice]


class RawSliceInfo(NamedTuple):
    """JinjaTracer-specific info about each RawFileSlice."""

    unique_alternate_id: Optional[str]
    alternate_code: Optional[str]
    next_slice_indices: List[int]


class JinjaTracer:
    """Deduces and records execution path of a Jinja template."""

    re_open_tag = regex.compile(r"^\s*({[{%])[\+\-]?\s*")
    re_close_tag = regex.compile(r"\s*[\+\-]?([}%]})\s*$")

    def __init__(
        self, raw_str: str, env: Environment, make_template: Callable[[str], Template]
    ):
        self.raw_str: str = raw_str
        self.env = env
        self.make_template: Callable[[str], Template] = make_template
        self.program_counter: int = 0
        self.slice_id: int = 0
        self.raw_slice_info: Dict[RawFileSlice, RawSliceInfo] = {}
        self.raw_sliced: List[RawFileSlice] = self._slice_template()
        self.sliced_file: List[TemplatedFileSlice] = []
        self.source_idx: int = 0

    def trace(self) -> JinjaTrace:
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
            is_set_or_macro = p[:3] == "set"
            if is_set_or_macro:
                p = p[3:]
            m_id = regex.match(r"^([0-9a-f]+)(_(\d+))?", p)
            if not m_id:
                raise ValueError(  # pragma: no cover
                    "Internal error. Trace template output does not match expected "
                    "format."
                )
            if m_id.group(3):
                # E.g. "2e8577c1d045439ba8d3b9bf47561de3_83". The number after
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
            if not is_set_or_macro:
                self.move_to_slice(target_slice_idx, slice_length)
            else:
                # If we find output from a {% set %} directive or a macro,
                # record a trace without reading or updating the program
                # counter. Such slices are always treated as "templated"
                # because they are inserted during expansion of templated
                # code (i.e. {% set %} variable or macro defined within the
                # file).
                self.record_trace(
                    slice_length, target_slice_idx, slice_type="templated"
                )
        return JinjaTrace(
            self.make_template(self.raw_str).render(), self.raw_sliced, self.sliced_file
        )

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

    def next_slice_id(self) -> str:
        """Returns a new, unique slice ID."""
        result = "{0:#0{1}x}".format(self.slice_id, 34)[2:]
        self.slice_id += 1
        return result

    def _slice_template(self) -> List[RawFileSlice]:
        """Slice template in jinja.

        NB: Starts and ends of blocks are not distinguished.
        """
        str_buff = ""
        idx = 0
        # We decide the "kind" of element we're dealing with
        # using it's _closing_ tag rather than it's opening
        # tag. The types here map back to similar types of
        # sections in the python slicer.
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

        # https://jinja.palletsprojects.com/en/2.11.x/api/#jinja2.Environment.lex
        stack = []
        result = []
        set_idx = None
        unique_alternate_id: Optional[str]
        alternate_code: Optional[str]
        for _, elem_type, raw in self.env.lex(self.raw_str):
            # Replace literal text with a unique ID.
            if elem_type == "data":
                if set_idx is None:
                    unique_alternate_id = self.next_slice_id()
                    alternate_code = f"\0{unique_alternate_id}_{len(raw)}"
                else:
                    unique_alternate_id = self.next_slice_id()
                    alternate_code = f"\0set{unique_alternate_id}_{len(raw)}"
                result.append(
                    RawFileSlice(
                        raw,
                        "literal",
                        idx,
                    )
                )
                self.raw_slice_info[result[-1]] = RawSliceInfo(
                    unique_alternate_id, alternate_code, []
                )
                idx += len(raw)
                continue
            str_buff += raw

            if elem_type.endswith("_begin"):
                # When a "begin" tag (whether block, comment, or data) uses
                # whitespace stripping (
                # https://jinja.palletsprojects.com/en/3.0.x/templates/#whitespace-control
                # ), the Jinja lex() function handles this by discarding adjacent
                # whitespace from in_str. For more insight, see the tokeniter()
                # function in this file:
                # https://github.com/pallets/jinja/blob/main/src/jinja2/lexer.py
                # We want to detect and correct for this in order to:
                # - Correctly update "idx" (if this is wrong, that's a
                #   potential DISASTER because lint fixes use this info to
                #   update the source file, and incorrect values often result in
                #   CORRUPTING the user's file so it's no longer valid SQL. :-O
                # - Guarantee that the slices we return fully "cover" the
                #   contents of in_str.
                #
                # We detect skipped characters by looking ahead in in_str for
                # the token just returned from lex(). The token text will either
                # be at the current 'idx' position (if whitespace stripping did
                # not occur) OR it'll be farther along in in_str, but we're
                # GUARANTEED that lex() only skips over WHITESPACE; nothing else.

                # Find the token returned. Did lex() skip over any characters?
                num_chars_skipped = self.raw_str.index(raw, idx) - idx
                if num_chars_skipped:
                    # Yes. It skipped over some characters. Compute a string
                    # containing the skipped characters.
                    skipped_str = self.raw_str[idx : idx + num_chars_skipped]

                    # Sanity check: Verify that Jinja only skips over
                    # WHITESPACE, never anything else.
                    if not skipped_str.isspace():  # pragma: no cover
                        templater_logger.warning(
                            "Jinja lex() skipped non-whitespace: %s", skipped_str
                        )
                    # Treat the skipped whitespace as a literal.
                    result.append(RawFileSlice(skipped_str, "literal", idx))
                    self.raw_slice_info[result[-1]] = RawSliceInfo("", "", [])
                    idx += num_chars_skipped

            # raw_end and raw_begin behave a little differently in
            # that the whole tag shows up in one go rather than getting
            # parts of the tag at a time.
            unique_alternate_id = None
            alternate_code = None
            trimmed_content = ""
            if elem_type.endswith("_end") or elem_type == "raw_begin":
                block_type = block_types[elem_type]
                block_subtype = None
                # Handle starts and ends of blocks
                if block_type in ("block", "templated"):
                    # Trim off the brackets and then the whitespace
                    m_open = self.re_open_tag.search(str_buff)
                    m_close = self.re_close_tag.search(str_buff)
                    if m_open and m_close:
                        trimmed_content = str_buff[
                            len(m_open.group(0)) : -len(m_close.group(0))
                        ]
                    # :TRICKY: Syntactically, the Jinja {% include %} directive looks
                    # like a block, but its behavior is basically syntactic sugar for
                    # {{ open("somefile).read() }}. Thus, treat it as templated code.
                    if block_type == "block" and trimmed_content.startswith("include "):
                        block_type = "templated"
                    if block_type == "block":
                        if trimmed_content.startswith("end"):
                            block_type = "block_end"
                        elif trimmed_content.startswith("el"):
                            # else, elif
                            block_type = "block_mid"
                        else:
                            block_type = "block_start"
                            if trimmed_content.split()[0] == "for":
                                block_subtype = "loop"
                    else:
                        # For "templated", evaluate the content in case of side
                        # effects, but return a unique slice ID.
                        if trimmed_content:
                            assert m_open and m_close
                            unique_id = self.next_slice_id()
                            unique_alternate_id = unique_id
                            prefix = "set" if set_idx is not None else ""
                            open_ = m_open.group(1)
                            close_ = m_close.group(1)
                            alternate_code = (
                                f"\0{prefix}{unique_alternate_id} {open_} "
                                f"{trimmed_content} {close_}"
                            )
                if block_type == "block_start" and trimmed_content.split()[0] in (
                    "macro",
                    "set",
                ):
                    # Jinja supports two forms of {% set %}:
                    # - {% set variable = value %}
                    # - {% set variable %}value{% endset %}
                    # https://jinja.palletsprojects.com/en/2.10.x/templates/#block-assignments
                    # When the second format is used, set the variable 'is_set'
                    # to a non-None value. This info is used elsewhere, as
                    # literals inside a {% set %} block require special handling
                    # during the trace.
                    trimmed_content_parts = trimmed_content.split(maxsplit=2)
                    if len(trimmed_content_parts) <= 2 or not trimmed_content_parts[
                        2
                    ].startswith("="):
                        set_idx = len(result)
                elif block_type == "block_end" and set_idx is not None:
                    # Exiting a {% set %} block. Clear the indicator variable.
                    set_idx = None
                m = regex.search(r"\s+$", raw, regex.MULTILINE | regex.DOTALL)
                if raw.startswith("-") and m:
                    # Right whitespace was stripped. Split off the trailing
                    # whitespace into a separate slice. The desired behavior is
                    # to behave similarly as the left stripping case above.
                    # Note that the stakes are a bit different, because lex()
                    # hasn't *omitted* any characters from the strings it
                    # returns, it has simply grouped them differently than we
                    # want.
                    trailing_chars = len(m.group(0))
                    if block_type.startswith("block_"):
                        alternate_code = self._remove_block_whitespace_control(
                            str_buff[:-trailing_chars]
                        )
                    result.append(
                        RawFileSlice(
                            str_buff[:-trailing_chars],
                            block_type,
                            idx,
                            block_subtype,
                        )
                    )
                    self.raw_slice_info[result[-1]] = RawSliceInfo(
                        unique_alternate_id, alternate_code, []
                    )
                    block_idx = len(result) - 1
                    idx += len(str_buff) - trailing_chars
                    result.append(
                        RawFileSlice(
                            str_buff[-trailing_chars:],
                            "literal",
                            idx,
                        )
                    )
                    self.raw_slice_info[result[-1]] = RawSliceInfo("", "", [])
                    idx += trailing_chars
                else:
                    if block_type.startswith("block_"):
                        alternate_code = self._remove_block_whitespace_control(str_buff)
                    result.append(
                        RawFileSlice(
                            str_buff,
                            block_type,
                            idx,
                            block_subtype,
                        )
                    )
                    self.raw_slice_info[result[-1]] = RawSliceInfo(
                        unique_alternate_id, alternate_code, []
                    )
                    block_idx = len(result) - 1
                    idx += len(str_buff)
                if block_type == "block_start" and trimmed_content.split()[0] in (
                    "for",
                    "if",
                ):
                    stack.append(block_idx)
                elif block_type == "block_mid":
                    # Record potential forward jump over this block.
                    self.raw_slice_info[result[stack[-1]]].next_slice_indices.append(
                        block_idx
                    )
                    stack.pop()
                    stack.append(block_idx)
                elif block_type == "block_end" and trimmed_content.split()[0] in (
                    "endfor",
                    "endif",
                ):
                    # Record potential forward jump over this block.
                    self.raw_slice_info[result[stack[-1]]].next_slice_indices.append(
                        block_idx
                    )
                    if result[stack[-1]].slice_subtype == "loop":
                        # Record potential backward jump to the loop beginning.
                        self.raw_slice_info[
                            result[block_idx]
                        ].next_slice_indices.append(stack[-1] + 1)
                    stack.pop()
                str_buff = ""
        return result

    @classmethod
    def _remove_block_whitespace_control(cls, in_str: str) -> Optional[str]:
        """Removes whitespace control from a Jinja block start or end.

        Use of Jinja whitespace stripping (e.g. `{%-` or `-%}`) causes the
        template to produce less output. This makes JinjaTracer's job harder,
        because it uses the "bread crumb trail" of output to deduce the
        execution path through the template. This change has no impact on the
        actual Jinja output, which uses the original, unmodified code.
        """
        result = regex.sub(r"^{%-", "{%", in_str)
        result = regex.sub(r"-%}$", "%}", result)
        return result if result != in_str else None
