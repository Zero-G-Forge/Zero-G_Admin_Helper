## ==========================================
## ZERO-G ADMIN HELPER - PDA YAML HIGHLIGHTER
## Colour rules for Empyrion PDA files (PDA.yaml), used by the PDA Editor's code view.
## Same colours as the ECF editor so both editors look alike:
##   keys (ChapterTitle:), list dashes (-), 'text', numbers, true/false, pda_ text ids and # comments.
## ==========================================

# region Imports

import re

from PyQt6.QtGui import QSyntaxHighlighter

## Reuse the ECF editor's colour builder and comment finder so the two editors match.
from features.ecf_editor.ecf_code_editor import _make_format, _find_comment_start

# endregion


# region PdaYamlHighlighter Class

class PdaYamlHighlighter(QSyntaxHighlighter):
    """Colours PDA.yaml one line at a time. Qt calls highlightBlock for every line that changes."""

    def __init__(self, document):
        super().__init__(document)

        ## (pattern, style, which group to colour). Later rules paint over earlier ones.
        self.rules = [

            ## Numbers, e.g. PlayerLevel: 1 or DelaySeconds: 1
            (re.compile(r"\b\d+(\.\d+)?\b"), _make_format("number"), 0),

            ## true / false
            (re.compile(r"\b(true|false)\b", re.IGNORECASE), _make_format("keyword", bold=True), 0),

            ## Text ids that point into PDA.csv, e.g. pda_uW0W4W4
            (re.compile(r"\bpda_\w+"), _make_format("block"), 0),

            ## Keys: a word followed by ':' at the start of a line (after any spaces or a list dash)
            (re.compile(r"^\s*(?:-\s+)?([A-Za-z_][\w\.]*)\s*:"), _make_format("key"), 1),

            ## List dash at the start of a line, e.g. '  - ChapterTitle:'
            (re.compile(r"^\s*(-)\s"), _make_format("brace", bold=True), 1),

            ## 'single' or "double" quoted text
            (re.compile(r"'(?:[^']|'')*'|\"(?:[^\"\\\\]|\\\\.)*\""), _make_format("string"), 0),
        ]
        self.comment_format = _make_format("comment", italic=True)

    def highlightBlock(self, text: str):
        for pattern, text_format, group in self.rules:
            for match in pattern.finditer(text):
                start, end = match.span(group)
                if start >= 0:
                    self.setFormat(start, end - start, text_format)

        ## Comments last: everything from the first # that is not inside "quotes".
        comment_start = _find_comment_start(text)
        if comment_start >= 0:
            self.setFormat(comment_start, len(text) - comment_start, self.comment_format)

# endregion
