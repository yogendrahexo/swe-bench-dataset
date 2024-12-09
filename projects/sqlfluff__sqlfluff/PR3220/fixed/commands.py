"""Contains the CLI."""

from itertools import chain
import os
import sys
import json
import logging
import time
from logging import LogRecord
from typing import Callable, Tuple, Optional, List, cast

import yaml

import click

# For the profiler
import pstats
from io import StringIO

# To enable colour cross platform
import colorama
from tqdm import tqdm
from sqlfluff.cli.autocomplete import shell_completion_enabled, dialect_shell_complete

from sqlfluff.cli.formatters import (
    format_rules,
    format_violation,
    format_linting_result_header,
    format_linting_stats,
    colorize,
    format_dialect_warning,
    format_dialects,
    OutputStreamFormatter,
)
from sqlfluff.cli.helpers import cli_table, get_package_version
from sqlfluff.cli.outputstream import make_output_stream, OutputStream

# Import from sqlfluff core.
from sqlfluff.core import (
    Linter,
    FluffConfig,
    SQLLintError,
    SQLTemplaterError,
    SQLFluffUserError,
    dialect_selector,
    dialect_readout,
    TimingSummary,
)
from sqlfluff.core.config import progress_bar_configuration

from sqlfluff.core.enums import FormatType, Color
from sqlfluff.core.linter import ParsedString
from sqlfluff.core.plugin.host import get_plugin_manager
from sqlfluff.core.linter import LintingResult


class RedWarningsFilter(logging.Filter):
    """This filter makes all warnings or above red."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter any warnings (or above) to turn them red."""
        if record.levelno >= logging.WARNING:
            record.msg = f"{colorize(record.msg, Color.red)} "
        return True


class StreamHandlerTqdm(logging.StreamHandler):
    """Modified StreamHandler which takes care of writing within `tqdm` context.

    It uses `tqdm` write which takes care of conflicting prints with progressbar.
    Without it, there were left artifacts in DEBUG mode (not sure about another ones,
    but probably would happen somewhere).
    """

    def emit(self, record: LogRecord) -> None:
        """Behaves like original one except uses `tqdm` to write."""
        try:
            msg = self.format(record)
            tqdm.write(msg, file=self.stream)
            self.flush()
        except Exception:  # pragma: no cover
            self.handleError(record)


def set_logging_level(
    verbosity: int, logger: Optional[logging.Logger] = None, stderr_output: bool = False
) -> None:
    """Set up logging for the CLI.

    We either set up global logging based on the verbosity
    or, if `logger` is specified, we only limit to a single
    sqlfluff logger. Verbosity is applied in the same way.

    Implementation: If `logger` is not specified, the handler
    is attached to the `sqlfluff` logger. If it is specified
    then it attaches the the logger in question. In addition
    if `logger` is specified, then that logger will also
    not propagate.
    """
    fluff_logger = logging.getLogger("sqlfluff")
    # Don't propagate logging
    fluff_logger.propagate = False

    # Enable colorama
    colorama.init()

    # Set up the log handler which is able to print messages without overlapping
    # with progressbars.
    handler = StreamHandlerTqdm(stream=sys.stderr if stderr_output else sys.stdout)
    # NB: the unicode character at the beginning is to squash any badly
    # tamed ANSI colour statements, and return us to normality.
    handler.setFormatter(logging.Formatter("\u001b[0m%(levelname)-10s %(message)s"))
    # Set up a handler to colour warnings red.
    handler.addFilter(RedWarningsFilter())
    if logger:
        focus_logger = logging.getLogger(f"sqlfluff.{logger}")
        focus_logger.addHandler(handler)
    else:
        fluff_logger.addHandler(handler)

    # NB: We treat the parser logger slightly differently because it's noisier.
    # It's important that we set levels for all each time so
    # that we don't break tests by changing the granularity
    # between tests.
    parser_logger = logging.getLogger("sqlfluff.parser")
    if verbosity < 3:
        fluff_logger.setLevel(logging.WARNING)
        parser_logger.setLevel(logging.NOTSET)
    elif verbosity == 3:
        fluff_logger.setLevel(logging.INFO)
        parser_logger.setLevel(logging.WARNING)
    elif verbosity == 4:
        fluff_logger.setLevel(logging.DEBUG)
        parser_logger.setLevel(logging.INFO)
    elif verbosity > 4:
        fluff_logger.setLevel(logging.DEBUG)
        parser_logger.setLevel(logging.DEBUG)


def common_options(f: Callable) -> Callable:
    """Add common options to commands via a decorator.

    These are applied to all of the cli commands.
    """
    f = click.version_option()(f)
    f = click.option(
        "-v",
        "--verbose",
        count=True,
        default=None,
        help=(
            "Verbosity, how detailed should the output be. This is *stackable*, so "
            "`-vv` is more verbose than `-v`. For the most verbose option try `-vvvv` "
            "or `-vvvvv`."
        ),
    )(f)
    f = click.option(
        "-n",
        "--nocolor",
        is_flag=True,
        default=None,
        help="No color - output will be without ANSI color codes.",
    )(f)

    return f


def core_options(f: Callable) -> Callable:
    """Add core operation options to commands via a decorator.

    These are applied to the main (but not all) cli commands like
    `parse`, `lint` and `fix`.
    """
    # Only enable dialect completion if on version of click
    # that supports it
    if shell_completion_enabled:
        f = click.option(
            "--dialect",
            default=None,
            help="The dialect of SQL to lint",
            shell_complete=dialect_shell_complete,
        )(f)
    else:  # pragma: no cover
        f = click.option(
            "--dialect",
            default=None,
            help="The dialect of SQL to lint",
        )(f)
    f = click.option(
        "--templater",
        default=None,
        help="The templater to use (default=jinja)",
        type=click.Choice(
            [
                templater.name
                for templater in chain.from_iterable(
                    get_plugin_manager().hook.get_templaters()
                )
            ]
        ),
    )(f)
    f = click.option(
        "--rules",
        default=None,
        help=(
            "Narrow the search to only specific rules. For example "
            "specifying `--rules L001` will only search for rule `L001` (Unnecessary "
            "trailing whitespace). Multiple rules can be specified with commas e.g. "
            "`--rules L001,L002` will specify only looking for violations of rule "
            "`L001` and rule `L002`."
        ),
    )(f)
    f = click.option(
        "--exclude-rules",
        default=None,
        help=(
            "Exclude specific rules. For example "
            "specifying `--exclude-rules L001` will remove rule `L001` (Unnecessary "
            "trailing whitespace) from the set of considered rules. This could either "
            "be the allowlist, or the general set if there is no specific allowlist. "
            "Multiple rules can be specified with commas e.g. "
            "`--exclude-rules L001,L002` will exclude violations of rule "
            "`L001` and rule `L002`."
        ),
    )(f)
    f = click.option(
        "--config",
        "extra_config_path",
        default=None,
        help=(
            "Include additional config file. By default the config is generated "
            "from the standard configuration files described in the documentation. "
            "This argument allows you to specify an additional configuration file that "
            "overrides the standard configuration files. N.B. cfg format is required."
        ),
        type=click.Path(),
    )(f)
    f = click.option(
        "--ignore-local-config",
        is_flag=True,
        help=(
            "Ignore config files in default search path locations. "
            "This option allows the user to lint with the default config "
            "or can be used in conjunction with --config to only "
            "reference the custom config file."
        ),
    )(f)
    f = click.option(
        "--encoding",
        default=None,
        help=(
            "Specify encoding to use when reading and writing files. Defaults to "
            "autodetect."
        ),
    )(f)
    f = click.option(
        "--ignore",
        default=None,
        help=(
            "Ignore particular families of errors so that they don't cause a failed "
            "run. For example `--ignore parsing` would mean that any parsing errors "
            "are ignored and don't influence the success or fail of a run. "
            "`--ignore` behaves somewhat like `noqa` comments, except it "
            "applies globally. Multiple options are possible if comma separated: "
            "e.g. `--ignore parsing,templating`."
        ),
    )(f)
    f = click.option(
        "--bench",
        is_flag=True,
        help="Set this flag to engage the benchmarking tool output.",
    )(f)
    f = click.option(
        "--logger",
        type=click.Choice(
            ["templater", "lexer", "parser", "linter", "rules"], case_sensitive=False
        ),
        help="Choose to limit the logging to one of the loggers.",
    )(f)
    f = click.option(
        "--disable-noqa",
        is_flag=True,
        default=None,
        help="Set this flag to ignore inline noqa comments.",
    )(f)
    return f


def get_config(
    extra_config_path: Optional[str] = None,
    ignore_local_config: bool = False,
    **kwargs,
) -> FluffConfig:
    """Get a config object from kwargs."""
    if kwargs.get("dialect"):
        try:
            # We're just making sure it exists at this stage.
            # It will be fetched properly in the linter.
            dialect_selector(kwargs["dialect"])
        except SQLFluffUserError as err:
            click.echo(
                colorize(
                    f"Error loading dialect '{kwargs['dialect']}': {str(err)}",
                    color=Color.red,
                )
            )
            sys.exit(66)
        except KeyError:
            click.echo(
                colorize(
                    f"Error: Unknown dialect '{kwargs['dialect']}'", color=Color.red
                )
            )
            sys.exit(66)
    from_root_kwargs = {}
    if "require_dialect" in kwargs:
        from_root_kwargs["require_dialect"] = kwargs.pop("require_dialect")
    # Instantiate a config object (filtering out the nulls)
    overrides = {k: kwargs[k] for k in kwargs if kwargs[k] is not None}
    try:
        return FluffConfig.from_root(
            extra_config_path=extra_config_path,
            ignore_local_config=ignore_local_config,
            overrides=overrides,
            **from_root_kwargs,
        )
    except SQLFluffUserError as err:  # pragma: no cover
        click.echo(
            colorize(
                f"Error loading config: {str(err)}",
                color=Color.red,
            )
        )
        sys.exit(66)


def get_linter_and_formatter(
    cfg: FluffConfig, output_stream: Optional[OutputStream] = None
) -> Tuple[Linter, OutputStreamFormatter]:
    """Get a linter object given a config."""
    try:
        # We're just making sure it exists at this stage.
        # It will be fetched properly in the linter.
        dialect = cfg.get("dialect")
        if dialect:
            dialect_selector(dialect)
    except KeyError:  # pragma: no cover
        click.echo(f"Error: Unknown dialect '{cfg.get('dialect')}'")
        sys.exit(66)
    formatter = OutputStreamFormatter(
        output_stream=output_stream or make_output_stream(cfg),
        verbosity=cfg.get("verbose"),
        output_line_length=cfg.get("output_line_length"),
    )
    return Linter(config=cfg, formatter=formatter), formatter


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option()
def cli():
    """Sqlfluff is a modular sql linter for humans."""


@cli.command()
@common_options
def version(**kwargs) -> None:
    """Show the version of sqlfluff."""
    c = get_config(**kwargs, require_dialect=False)
    if c.get("verbose") > 0:
        # Instantiate the linter
        lnt, formatter = get_linter_and_formatter(c)
        # Dispatch the detailed config from the linter.
        formatter.dispatch_config(lnt)
    else:
        # Otherwise just output the package version.
        click.echo(get_package_version(), color=c.get("color"))


@cli.command()
@common_options
def rules(**kwargs) -> None:
    """Show the current rules in use."""
    c = get_config(**kwargs, dialect="ansi")
    lnt, _ = get_linter_and_formatter(c)
    click.echo(format_rules(lnt), color=c.get("color"))


@cli.command()
@common_options
def dialects(**kwargs) -> None:
    """Show the current dialects available."""
    c = get_config(**kwargs, require_dialect=False)
    click.echo(format_dialects(dialect_readout), color=c.get("color"))


def dump_file_payload(filename: Optional[str], payload: str):
    """Write the output file content to stdout or file."""
    # If there's a file specified to write to, write to it.
    if filename:
        with open(filename, "w") as out_file:
            out_file.write(payload)
    # Otherwise write to stdout
    else:
        click.echo(payload)


@cli.command()
@common_options
@core_options
@click.option(
    "-f",
    "--format",
    "format",
    default="human",
    type=click.Choice([ft.value for ft in FormatType], case_sensitive=False),
    help="What format to return the lint result in (default=human).",
)
@click.option(
    "--write-output",
    help=(
        "Optionally provide a filename to write the results to, mostly used in "
        "tandem with --format. NB: Setting an output file re-enables normal "
        "stdout logging."
    ),
)
@click.option(
    "--annotation-level",
    default="notice",
    type=click.Choice(["notice", "warning", "failure", "error"], case_sensitive=False),
    help=(
        "When format is set to github-annotation or github-annotation-native, "
        "default annotation level (default=notice). failure and error are equivalent."
    ),
)
@click.option(
    "--nofail",
    is_flag=True,
    help=(
        "If set, the exit code will always be zero, regardless of violations "
        "found. This is potentially useful during rollout."
    ),
)
@click.option(
    "--disregard-sqlfluffignores",
    is_flag=True,
    help="Perform the operation regardless of .sqlfluffignore configurations",
)
@click.option(
    "-p",
    "--processes",
    type=int,
    default=1,
    help="The number of parallel processes to run.",
)
@click.option(
    "--disable_progress_bar",
    is_flag=True,
    help="Disables progress bars.",
)
@click.argument("paths", nargs=-1, type=click.Path(allow_dash=True))
def lint(
    paths: Tuple[str],
    processes: int,
    format: str,
    write_output: Optional[str],
    annotation_level: str,
    nofail: bool,
    disregard_sqlfluffignores: bool,
    logger: Optional[logging.Logger] = None,
    bench: bool = False,
    disable_progress_bar: Optional[bool] = False,
    extra_config_path: Optional[str] = None,
    ignore_local_config: bool = False,
    **kwargs,
) -> None:
    """Lint SQL files via passing a list of files or using stdin.

    PATH is the path to a sql file or directory to lint. This can be either a
    file ('path/to/file.sql'), a path ('directory/of/sql/files'), a single ('-')
    character to indicate reading from *stdin* or a dot/blank ('.'/' ') which will
    be interpreted like passing the current working directory as a path argument.

    Linting SQL files:

        sqlfluff lint path/to/file.sql
        sqlfluff lint directory/of/sql/files

    Linting a file via stdin (note the lone '-' character):

        cat path/to/file.sql | sqlfluff lint -
        echo 'select col from tbl' | sqlfluff lint -

    """
    config = get_config(
        extra_config_path, ignore_local_config, require_dialect=False, **kwargs
    )
    non_human_output = (format != FormatType.human.value) or (write_output is not None)
    file_output = None
    output_stream = make_output_stream(config, format, write_output)
    lnt, formatter = get_linter_and_formatter(config, output_stream)

    verbose = config.get("verbose")
    progress_bar_configuration.disable_progress_bar = disable_progress_bar

    formatter.dispatch_config(lnt)

    # Set up logging.
    set_logging_level(verbosity=verbose, logger=logger, stderr_output=non_human_output)
    # add stdin if specified via lone '-'
    if ("-",) == paths:
        result = lnt.lint_string_wrapped(sys.stdin.read(), fname="stdin")
    else:
        # Output the results as we go
        if verbose >= 1:
            click.echo(format_linting_result_header())
        try:
            result = lnt.lint_paths(
                paths,
                ignore_non_existent_files=False,
                ignore_files=not disregard_sqlfluffignores,
                processes=processes,
            )
        except OSError:
            click.echo(
                colorize(
                    f"The path(s) '{paths}' could not be accessed. Check it/they "
                    "exist(s).",
                    Color.red,
                )
            )
            sys.exit(1)
        # Output the final stats
        if verbose >= 1:
            click.echo(format_linting_stats(result, verbose=verbose))

    if format == FormatType.json.value:
        file_output = json.dumps(result.as_records())
    elif format == FormatType.yaml.value:
        file_output = yaml.dump(result.as_records(), sort_keys=False)
    elif format == FormatType.github_annotation.value:
        if annotation_level == "error":
            annotation_level = "failure"

        github_result = []
        for record in result.as_records():
            filepath = record["filepath"]
            for violation in record["violations"]:
                # NOTE: The output format is designed for this GitHub action:
                # https://github.com/yuzutech/annotations-action
                # It is similar, but not identical, to the native GitHub format:
                # https://docs.github.com/en/rest/reference/checks#annotations-items
                github_result.append(
                    {
                        "file": filepath,
                        "line": violation["line_no"],
                        "start_column": violation["line_pos"],
                        "end_column": violation["line_pos"],
                        "title": "SQLFluff",
                        "message": f"{violation['code']}: {violation['description']}",
                        "annotation_level": annotation_level,
                    }
                )
        file_output = json.dumps(github_result)
    elif format == FormatType.github_annotation_native.value:
        if annotation_level == "failure":
            annotation_level = "error"

        github_result_native = []
        for record in result.as_records():
            filepath = record["filepath"]
            for violation in record["violations"]:
                # NOTE: The output format is designed for GitHub action:
                # https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-a-notice-message
                line = f"::{annotation_level} "
                line += "title=SQLFluff,"
                line += f"file={filepath},"
                line += f"line={violation['line_no']},"
                line += f"col={violation['line_pos']}"
                line += "::"
                line += f"{violation['code']}: {violation['description']}"

                github_result_native.append(line)

        file_output = "\n".join(github_result_native)

    if file_output:
        dump_file_payload(write_output, cast(str, file_output))

    output_stream.close()
    if bench:
        click.echo("==== overall timings ====")
        click.echo(cli_table([("Clock time", result.total_time)]))
        timing_summary = result.timing_summary()
        for step in timing_summary:
            click.echo(f"=== {step} ===")
            click.echo(cli_table(timing_summary[step].items()))

    if not nofail:
        if not non_human_output:
            _completion_message(config)
        sys.exit(result.stats()["exit code"])
    else:
        sys.exit(0)


def _handle_files_with_tmp_or_prs_errors(lint_result: LintingResult) -> int:
    """Discard lint fixes for files with templating or parse errors.

    Returns 1 if there are any files with templating or parse errors after
    filtering, else 0. (Intended as a process exit code.)
    """
    total_errors, num_filtered_errors = lint_result.count_tmp_prs_errors()
    lint_result.discard_fixes_for_lint_errors_in_files_with_tmp_or_prs_errors()
    if total_errors:
        click.echo(
            colorize(f"  [{total_errors} templating/parsing errors found]", Color.red)
        )
        if num_filtered_errors < total_errors:
            color = Color.red if num_filtered_errors else Color.green
            click.echo(
                colorize(
                    f"  [{num_filtered_errors} templating/parsing errors "
                    f'remaining after "ignore"]',
                    color,
                )
            )
    return 1 if num_filtered_errors else 0


def do_fixes(lnt, result, formatter=None, **kwargs):
    """Actually do the fixes."""
    click.echo("Persisting Changes...")
    res = result.persist_changes(formatter=formatter, **kwargs)
    if all(res.values()):
        click.echo("Done. Please check your files to confirm.")
        return True
    # If some failed then return false
    click.echo(
        "Done. Some operations failed. Please check your files to confirm."
    )  # pragma: no cover
    click.echo(
        "Some errors cannot be fixed or there is another error blocking it."
    )  # pragma: no cover
    return False  # pragma: no cover


@cli.command()
@common_options
@core_options
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help=(
        "skip the confirmation prompt and go straight to applying "
        "fixes. **Use this with caution.**"
    ),
)
@click.option(
    "--fixed-suffix", default=None, help="An optional suffix to add to fixed files."
)
@click.option(
    "-p",
    "--processes",
    type=int,
    default=1,
    help="The number of parallel processes to run.",
)
@click.option(
    "--disable_progress_bar",
    is_flag=True,
    help="Disables progress bars.",
)
@click.option(
    "--FIX-EVEN-UNPARSABLE",
    is_flag=True,
    default=None,
    help=(
        "Enables fixing of files that have templating or parse errors. "
        "Note that the similar-sounding '--ignore' or 'noqa' features merely "
        "prevent errors from being *displayed*. For safety reasons, the 'fix'"
        "command will not make any fixes in files that have templating or parse "
        "errors unless '--FIX-EVEN-UNPARSABLE' is enabled on the command line"
        "or in the .sqlfluff config file."
    ),
)
@click.argument("paths", nargs=-1, type=click.Path(allow_dash=True))
def fix(
    force: bool,
    paths: Tuple[str],
    processes: int,
    bench: bool = False,
    fixed_suffix: str = "",
    logger: Optional[logging.Logger] = None,
    disable_progress_bar: Optional[bool] = False,
    extra_config_path: Optional[str] = None,
    ignore_local_config: bool = False,
    **kwargs,
) -> None:
    """Fix SQL files.

    PATH is the path to a sql file or directory to lint. This can be either a
    file ('path/to/file.sql'), a path ('directory/of/sql/files'), a single ('-')
    character to indicate reading from *stdin* or a dot/blank ('.'/' ') which will
    be interpreted like passing the current working directory as a path argument.
    """
    # some quick checks
    fixing_stdin = ("-",) == paths

    config = get_config(
        extra_config_path, ignore_local_config, require_dialect=False, **kwargs
    )
    fix_even_unparsable = config.get("fix_even_unparsable")
    output_stream = make_output_stream(
        config, None, os.devnull if fixing_stdin else None
    )
    lnt, formatter = get_linter_and_formatter(config, output_stream)

    verbose = config.get("verbose")
    progress_bar_configuration.disable_progress_bar = disable_progress_bar

    exit_code = 0

    formatter.dispatch_config(lnt)

    # Set up logging.
    set_logging_level(verbosity=verbose, logger=logger, stderr_output=fixing_stdin)

    # handle stdin case. should output formatted sql to stdout and nothing else.
    if fixing_stdin:
        stdin = sys.stdin.read()

        result = lnt.lint_string_wrapped(stdin, fname="stdin", fix=True)
        templater_error = result.num_violations(types=SQLTemplaterError) > 0
        unfixable_error = result.num_violations(types=SQLLintError, fixable=False) > 0
        if not fix_even_unparsable:
            exit_code = _handle_files_with_tmp_or_prs_errors(result)

        if result.num_violations(types=SQLLintError, fixable=True) > 0:
            stdout = result.paths[0].files[0].fix_string()[0]
        else:
            stdout = stdin

        if templater_error:
            click.echo(
                colorize(
                    "Fix aborted due to unparseable template variables.",
                    Color.red,
                ),
                err=True,
            )
            click.echo(
                colorize(
                    "Use --FIX-EVEN-UNPARSABLE' to attempt to fix the SQL anyway.",
                    Color.red,
                ),
                err=True,
            )

        if unfixable_error:
            click.echo(colorize("Unfixable violations detected.", Color.red), err=True)

        click.echo(stdout, nl=False)
        sys.exit(1 if templater_error or unfixable_error else exit_code)

    # Lint the paths (not with the fix argument at this stage), outputting as we go.
    click.echo("==== finding fixable violations ====")
    try:
        result = lnt.lint_paths(
            paths,
            fix=True,
            ignore_non_existent_files=False,
            processes=processes,
        )
    except OSError:
        click.echo(
            colorize(
                f"The path(s) '{paths}' could not be accessed. Check it/they exist(s).",
                Color.red,
            ),
            err=True,
        )
        sys.exit(1)

    if not fix_even_unparsable:
        exit_code = _handle_files_with_tmp_or_prs_errors(result)

    # NB: We filter to linting violations here, because they're
    # the only ones which can be potentially fixed.
    if result.num_violations(types=SQLLintError, fixable=True) > 0:
        click.echo("==== fixing violations ====")
        click.echo(
            f"{result.num_violations(types=SQLLintError, fixable=True)} fixable "
            "linting violations found"
        )
        if force:
            click.echo(f"{colorize('FORCE MODE', Color.red)}: Attempting fixes...")
            success = do_fixes(
                lnt,
                result,
                formatter,
                types=SQLLintError,
                fixed_file_suffix=fixed_suffix,
            )
            if not success:
                sys.exit(1)  # pragma: no cover
        else:
            click.echo(
                "Are you sure you wish to attempt to fix these? [Y/n] ", nl=False
            )
            c = click.getchar().lower()
            click.echo("...")
            if c in ("y", "\r", "\n"):
                click.echo("Attempting fixes...")
                success = do_fixes(
                    lnt,
                    result,
                    formatter,
                    types=SQLLintError,
                    fixed_file_suffix=fixed_suffix,
                )
                if not success:
                    sys.exit(1)  # pragma: no cover
                else:
                    _completion_message(config)
            elif c == "n":
                click.echo("Aborting...")
                exit_code = 1
            else:  # pragma: no cover
                click.echo("Invalid input, please enter 'Y' or 'N'")
                click.echo("Aborting...")
                exit_code = 1
    else:
        click.echo("==== no fixable linting violations found ====")
        _completion_message(config)

    error_types = [
        (
            dict(types=SQLLintError, fixable=False),
            "  [{} unfixable linting violations found]",
            1,
        ),
    ]
    for num_violations_kwargs, message_format, error_level in error_types:
        num_violations = result.num_violations(**num_violations_kwargs)
        if num_violations > 0:
            click.echo(message_format.format(num_violations))
            exit_code = max(exit_code, error_level)

    if bench:
        click.echo("==== overall timings ====")
        click.echo(cli_table([("Clock time", result.total_time)]))
        timing_summary = result.timing_summary()
        for step in timing_summary:
            click.echo(f"=== {step} ===")
            click.echo(cli_table(timing_summary[step].items()))

    sys.exit(exit_code)


def _completion_message(config: FluffConfig) -> None:
    click.echo(
        "All Finished"
        f"{'' if (config.get('nocolor') or not sys.stdout.isatty()) else ' 📜 🎉'}!"
    )


def quoted_presenter(dumper, data):
    """Re-presenter which always double quotes string values needing escapes."""
    if "\n" in data or "\t" in data or "'" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    else:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="")


@cli.command()
@common_options
@core_options
@click.argument("path", nargs=1, type=click.Path(allow_dash=True))
@click.option(
    "--recurse", default=0, help="The depth to recursively parse to (0 for unlimited)"
)
@click.option(
    "-c",
    "--code-only",
    is_flag=True,
    help="Output only the code elements of the parse tree.",
)
@click.option(
    "-m",
    "--include-meta",
    is_flag=True,
    help=(
        "Include meta segments (indents, dedents and placeholders) in the output. "
        "This only applies when outputting json or yaml."
    ),
)
@click.option(
    "-f",
    "--format",
    default=FormatType.human.value,
    type=click.Choice(
        [
            FormatType.human.value,
            FormatType.json.value,
            FormatType.yaml.value,
        ],
        case_sensitive=False,
    ),
    help="What format to return the parse result in.",
)
@click.option(
    "--write-output",
    help=(
        "Optionally provide a filename to write the results to, mostly used in "
        "tandem with --format. NB: Setting an output file re-enables normal "
        "stdout logging."
    ),
)
@click.option(
    "--profiler", is_flag=True, help="Set this flag to engage the python profiler."
)
@click.option(
    "--nofail",
    is_flag=True,
    help=(
        "If set, the exit code will always be zero, regardless of violations "
        "found. This is potentially useful during rollout."
    ),
)
def parse(
    path: str,
    code_only: bool,
    include_meta: bool,
    format: str,
    write_output: Optional[str],
    profiler: bool,
    bench: bool,
    nofail: bool,
    logger: Optional[logging.Logger] = None,
    extra_config_path: Optional[str] = None,
    ignore_local_config: bool = False,
    **kwargs,
) -> None:
    """Parse SQL files and just spit out the result.

    PATH is the path to a sql file or directory to lint. This can be either a
    file ('path/to/file.sql'), a path ('directory/of/sql/files'), a single ('-')
    character to indicate reading from *stdin* or a dot/blank ('.'/' ') which will
    be interpreted like passing the current working directory as a path argument.
    """
    c = get_config(
        extra_config_path, ignore_local_config, require_dialect=False, **kwargs
    )
    # We don't want anything else to be logged if we want json or yaml output
    # unless we're writing to a file.
    non_human_output = (format != FormatType.human.value) or (write_output is not None)
    output_stream = make_output_stream(c, format, write_output)
    lnt, formatter = get_linter_and_formatter(c, output_stream)
    verbose = c.get("verbose")
    recurse = c.get("recurse")

    progress_bar_configuration.disable_progress_bar = True

    formatter.dispatch_config(lnt)

    # Set up logging.
    set_logging_level(verbosity=verbose, logger=logger, stderr_output=non_human_output)

    # TODO: do this better

    if profiler:
        # Set up the profiler if required
        try:
            import cProfile
        except ImportError:  # pragma: no cover
            click.echo("The cProfiler is not available on your platform.")
            sys.exit(1)
        pr = cProfile.Profile()
        pr.enable()

    try:
        t0 = time.monotonic()

        # handle stdin if specified via lone '-'
        if "-" == path:
            parsed_strings = [
                lnt.parse_string(
                    sys.stdin.read(),
                    "stdin",
                    recurse=recurse,
                    config=lnt.config,
                ),
            ]
        else:
            # A single path must be specified for this command
            parsed_strings = list(lnt.parse_path(path, recurse=recurse))

        total_time = time.monotonic() - t0
        violations_count = 0

        # iterative print for human readout
        if format == FormatType.human.value:
            violations_count = _print_out_violations_and_timing(
                output_stream, bench, code_only, total_time, verbose, parsed_strings
            )
        else:
            parsed_strings_dict = [
                dict(
                    filepath=linted_result.fname,
                    segments=linted_result.tree.as_record(
                        code_only=code_only, show_raw=True, include_meta=include_meta
                    )
                    if linted_result.tree
                    else None,
                )
                for linted_result in parsed_strings
            ]

            if format == FormatType.yaml.value:
                # For yaml dumping always dump double quoted strings if they contain
                # tabs or newlines.
                yaml.add_representer(str, quoted_presenter)
                file_output = yaml.dump(parsed_strings_dict, sort_keys=False)
            elif format == FormatType.json.value:
                file_output = json.dumps(parsed_strings_dict)

            # Dump the output to stdout or to file as appropriate.
            dump_file_payload(write_output, file_output)

    except OSError:  # pragma: no cover
        click.echo(
            colorize(
                f"The path '{path}' could not be accessed. Check it exists.",
                Color.red,
            ),
            err=True,
        )
        sys.exit(1)

    if profiler:
        pr.disable()
        profiler_buffer = StringIO()
        ps = pstats.Stats(pr, stream=profiler_buffer).sort_stats("cumulative")
        ps.print_stats()
        click.echo("==== profiler stats ====")
        # Only print the first 50 lines of it
        click.echo("\n".join(profiler_buffer.getvalue().split("\n")[:50]))

    if violations_count > 0 and not nofail:
        sys.exit(66)  # pragma: no cover
    else:
        sys.exit(0)


def _print_out_violations_and_timing(
    output_stream: OutputStream,
    bench: bool,
    code_only: bool,
    total_time: float,
    verbose: int,
    parsed_strings: List[ParsedString],
) -> int:
    """Used by human formatting during the parse."""
    violations_count = 0
    timing = TimingSummary()

    for parsed_string in parsed_strings:
        timing.add(parsed_string.time_dict)

        if parsed_string.tree:
            output_stream.write(parsed_string.tree.stringify(code_only=code_only))
        else:
            # TODO: Make this prettier
            output_stream.write("...Failed to Parse...")  # pragma: no cover

        violations_count += len(parsed_string.violations)
        if parsed_string.violations:
            output_stream.write("==== parsing violations ====")  # pragma: no cover
        for v in parsed_string.violations:
            output_stream.write(format_violation(v))  # pragma: no cover
        if parsed_string.violations and parsed_string.config.get("dialect") == "ansi":
            output_stream.write(format_dialect_warning())  # pragma: no cover

        if verbose >= 2:
            output_stream.write("==== timings ====")
            output_stream.write(cli_table(parsed_string.time_dict.items()))

    if verbose >= 2 or bench:
        output_stream.write("==== overall timings ====")
        output_stream.write(cli_table([("Clock time", total_time)]))
        timing_summary = timing.summary()
        for step in timing_summary:
            output_stream.write(f"=== {step} ===")
            output_stream.write(cli_table(timing_summary[step].items()))

    return violations_count


# This "__main__" handler allows invoking SQLFluff using "python -m", which
# simplifies the use of cProfile, e.g.:
# python -m cProfile -s cumtime -m sqlfluff.cli.commands lint slow_file.sql
if __name__ == "__main__":
    cli.main(sys.argv[1:])  # pragma: no cover
