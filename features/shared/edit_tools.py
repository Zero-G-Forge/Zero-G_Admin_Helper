## ==========================================
## ZERO-G ADMIN HELPER - EDIT TOOLS
## The checks and the diff the ECF and PDA editors use. Pure text work: nothing here reads or writes a file.
##   validate_text(file_name, text) -> problems, each {"line": number (1 = first line), "level": "error"/"warning", "message"}
##   make_diff(original, edited, file_name) -> unified diff lines (+ added, - removed), [] when nothing changed
## ==========================================

# region Imports

import csv
import difflib
import io

from features.shared.ecf_parser import BLOCK_HEADER_PATTERN, strip_comment

## PyYAML checks PDA.yaml. If it is missing, YAML files only get the tab check (fail soft: no crash).
try:
    import yaml
except ImportError:
    yaml = None

# endregion


# region Constants

## Lines of unchanged text shown around each change in the Changes Preview.
DIFF_CONTEXT_LINES = 2

## Problems listed at most, so a broken file doesn't flood the window.
MAX_PROBLEMS = 200

# endregion


# region Validate

def validate_text(file_name, text):
    """Checks a file's text by its type. Returns a list of problems; an empty list means it looks fine."""
    lower_name = str(file_name or "").lower()
    if lower_name.endswith(".ecf"):
        problems = validate_ecf(text)
    elif lower_name.endswith((".yaml", ".yml")):
        problems = validate_yaml(text)
    elif lower_name.endswith(".csv"):
        problems = validate_csv(text)
    else:
        problems = []
    return problems[:MAX_PROBLEMS]


def has_errors(problems):
    """True when at least one problem is an error (warnings alone don't count)."""
    return any(problem["level"] == "error" for problem in problems)


def validate_ecf(text):
    """ECF check: every { has its }, no } without a {, no open "quote", properties sit inside a block."""
    problems = []

    ## A stack of the line numbers where each still-open block started.
    open_blocks = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        ## strip_comment keeps a # that sits inside quotes, so an odd count here means a quote never closes.
        if strip_comment(raw_line).count('"') % 2 == 1:
            problems.append(_problem(line_number, "error", 'A "quote" is opened but never closed on this line.'))
        line_text = strip_comment(raw_line).strip()
        if not line_text:
            continue
        if BLOCK_HEADER_PATTERN.match(line_text):
            open_blocks.append(line_number)

            ## '{ Child 0 }' on one line opens and closes in one go.
            if line_text.endswith("}"):
                open_blocks.pop()
            continue
        if line_text.startswith("{"):
            problems.append(_problem(line_number, "error", "A block must start like '{ +Item Id: 1, Name: Example' or '{ Child 0'."))
            open_blocks.append(line_number)
            continue
        if line_text.startswith("}"):
            if open_blocks:
                open_blocks.pop()
            else:
                problems.append(_problem(line_number, "error", "This } closes a block that was never opened."))
            if line_text != "}":
                problems.append(_problem(line_number, "warning", "Text after } on the same line is ignored by the game."))
            continue
        if not open_blocks:
            problems.append(_problem(line_number, "error", "This line is outside every block."))
            continue
        if ":" not in line_text:
            problems.append(_problem(line_number, "warning", "This line is not 'Key: value'."))
    for start_line in open_blocks:
        problems.append(_problem(start_line, "error", "This block is never closed (a } is missing)."))
    problems.sort(key=lambda problem: problem["line"])
    return problems


def validate_yaml(text):
    """YAML check: no tab indents (YAML forbids them), then a full parse when PyYAML is available."""
    problems = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        indent = raw_line[:len(raw_line) - len(raw_line.lstrip())]
        if "\t" in indent:
            problems.append(_problem(line_number, "error", "YAML does not allow tabs for indenting; use spaces."))
    if yaml is not None and not problems:
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:

            ## problem_mark says where the parser gave up; its line count starts at 0.
            mark = getattr(e, "problem_mark", None)
            line_number = mark.line + 1 if mark is not None else 1
            message = str(getattr(e, "problem", None) or e).strip()
            problems.append(_problem(line_number, "error", "YAML: " + message + "."))
    return problems


def validate_csv(text):
    """CSV check: it parses, has a header, and no row has more columns than the header."""
    problems = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        header = next(reader, None)
        if not header:
            return [_problem(1, "error", "The file has no header row.")]
        for row in reader:
            if len(row) > len(header):
                problems.append(_problem(reader.line_num, "error",
                                         f"This row has {len(row)} columns but the header has {len(header)}."))
    except csv.Error as e:
        problems.append(_problem(getattr(reader, "line_num", 1) or 1, "error", "CSV: " + str(e) + "."))
    return problems


def _problem(line_number, level, message):
    return {"line": line_number, "level": level, "message": message}


def format_problems(problems):
    """Problems as plain text lines for the VALIDATE window, e.g. 'Line 12  ERROR  This block is never closed'."""
    return ["Line " + str(problem["line"]) + "  " + problem["level"].upper() + "  " + problem["message"] for problem in problems]

# endregion


# region Diff

def make_diff(original, edited, file_name="file"):
    """Unified diff from the downloaded copy to the edited text. [] when nothing changed."""
    if original == edited:
        return []
    return list(difflib.unified_diff(
        original.splitlines(keepends=True), edited.splitlines(keepends=True),
        fromfile="downloaded/" + file_name, tofile="edited/" + file_name,
        n=DIFF_CONTEXT_LINES, lineterm=""))


def diff_counts(diff_lines):
    """(added, removed) line counts of a diff, not counting the two file-name lines."""
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return added, removed

# endregion
