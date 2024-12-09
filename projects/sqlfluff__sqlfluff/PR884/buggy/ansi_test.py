"""Tests specific to the ansi dialect."""

import pytest
import logging

from sqlfluff.core import FluffConfig, Linter
from sqlfluff.core.parser import Lexer


@pytest.mark.parametrize(
    "raw,res",
    [
        ("a b", ["a", " ", "b"]),
        ("b.c", ["b", ".", "c"]),
        ("abc \n \t def  ;blah", ["abc", " ", "\n", " \t ", "def", "  ", ";", "blah"]),
    ],
)
def test__dialect__ansi__file_lex(raw, res, caplog):
    """Test we don't drop bits on simple examples."""
    config = FluffConfig(overrides=dict(dialect="ansi"))
    lexer = Lexer(config=config)
    with caplog.at_level(logging.DEBUG):
        tokens, _ = lexer.lex(raw)
    # From just the initial parse, check we're all there
    raw_list = [token.raw for token in tokens]
    assert "".join(token.raw for token in tokens) == raw
    assert raw_list == res


# Develop test to check specific elements against specific grammars.
@pytest.mark.parametrize(
    "segmentref,raw",
    [
        ("SelectKeywordSegment", "select"),
        ("NakedIdentifierSegment", "online_sales"),
        ("BareFunctionSegment", "current_timestamp"),
        ("FunctionSegment", "current_timestamp()"),
        ("NumericLiteralSegment", "1000.0"),
        ("ExpressionSegment", "online_sales / 1000.0"),
        ("IntervalExpressionSegment", "INTERVAL 1 YEAR"),
        ("ExpressionSegment", "CASE WHEN id = 1 THEN 'nothing' ELSE 'test' END"),
        # Nested Case Expressions
        # https://github.com/sqlfluff/sqlfluff/issues/172
        (
            "ExpressionSegment",
            (
                "CASE WHEN id = 1 THEN CASE WHEN true THEN 'something' "
                "ELSE 'nothing' END ELSE 'test' END"
            ),
        ),
        # Casting expressions
        # https://github.com/sqlfluff/sqlfluff/issues/161
        ("ExpressionSegment", "CAST(ROUND(online_sales / 1000.0) AS varchar)"),
        # Like expressions
        # https://github.com/sqlfluff/sqlfluff/issues/170
        ("ExpressionSegment", "name NOT LIKE '%y'"),
        # Functions with a space
        # https://github.com/sqlfluff/sqlfluff/issues/171
        ("SelectTargetElementSegment", "MIN (test.id) AS min_test_id"),
        # Interval literals
        # https://github.com/sqlfluff/sqlfluff/issues/148
        (
            "ExpressionSegment",
            "DATE_ADD(CURRENT_DATE('America/New_York'), INTERVAL 1 year)",
        ),
        # Array accessors
        ("ExpressionSegment", "my_array[1]"),
        ("ExpressionSegment", "my_array[OFFSET(1)]"),
        ("ExpressionSegment", "my_array[5:8]"),
        ("ExpressionSegment", "4 + my_array[OFFSET(1)]"),
        ("ExpressionSegment", "bits[OFFSET(0)] + 7"),
        (
            "SelectTargetElementSegment",
            (
                "(count_18_24 * bits[OFFSET(0)])"
                " / audience_size AS relative_abundance"
            ),
        ),
        ("ExpressionSegment", "count_18_24 * bits[OFFSET(0)] + count_25_34"),
        (
            "SelectTargetElementSegment",
            (
                "(count_18_24 * bits[OFFSET(0)] + count_25_34)"
                " / audience_size AS relative_abundance"
            ),
        ),
        # Dense math expressions
        # https://github.com/sqlfluff/sqlfluff/issues/178
        # https://github.com/sqlfluff/sqlfluff/issues/179
        ("SelectStatementSegment", "SELECT t.val/t.id FROM test WHERE id*1.0/id > 0.8"),
        ("SelectTargetElementSegment", "t.val/t.id"),
        # Issue with casting raise as part of PR #177
        ("SelectTargetElementSegment", "CAST(num AS INT64)"),
        # Casting as datatype with arguments
        ("SelectTargetElementSegment", "CAST(num AS numeric(8,4))"),
        # Wildcard field selection
        ("SelectTargetElementSegment", "a.*"),
        ("SelectTargetElementSegment", "a.b.*"),
        ("SelectTargetElementSegment", "a.b.c.*"),
        # Default Element Syntax
        ("ObjectReferenceSegment", "a..c.*"),
        # Negative Elements
        ("SelectTargetElementSegment", "-some_variable"),
        ("SelectTargetElementSegment", "- some_variable"),
        # Complex Functions
        (
            "ExpressionSegment",
            "concat(left(uaid, 2), '|', right(concat('0000000', SPLIT_PART(uaid, '|', 4)), 10), '|', '00000000')",
        ),
        # Notnull and Isnull
        ("ExpressionSegment", "c notnull"),
        ("ExpressionSegment", "c is null"),
        ("ExpressionSegment", "c isnull"),
        # Shorthand casting
        ("ExpressionSegment", "NULL::INT"),
        ("SelectTargetElementSegment", "NULL::INT AS user_id"),
    ],
)
def test__dialect__ansi_specific_segment_parses(
    segmentref, raw, caplog, dialect_specific_segment_parses
):
    """Test that specific segments parse as expected.

    NB: We're testing the PARSE function not the MATCH function
    although this will be a recursive parse and so the match
    function of SUBSECTIONS will be tested if present. The match
    function of the parent will not be tested.
    """
    dialect_specific_segment_parses("ansi", segmentref, raw, caplog)


@pytest.mark.parametrize(
    "segmentref,raw",
    [
        # Check we don't match empty whitespace as a reference
        ("ObjectReferenceSegment", "\n     ")
    ],
)
def test__dialect__ansi_specific_segment_not_match(
    segmentref, raw, caplog, dialect_specific_segment_not_match
):
    """Test that specific segments do not match.

    NB: We're testing the MATCH function not the PARSE function.
    This is the opposite to the above.
    """
    dialect_specific_segment_not_match("ansi", segmentref, raw, caplog)


@pytest.mark.parametrize(
    "raw,err_locations",
    [
        # Missing Closing bracket. Error should be raised
        # on the starting bracket.
        ("SELECT 1 + (2 ", [(1, 12)])
    ],
)
def test__dialect__ansi_specific_segment_not_parse(raw, err_locations, caplog):
    """Test queries do not parse, with parsing errors raised properly."""
    lnt = Linter()
    parsed = lnt.parse_string(raw)
    assert len(parsed.violations) > 0
    locs = [(v.line_no(), v.line_pos()) for v in parsed.violations]
    assert locs == err_locations
