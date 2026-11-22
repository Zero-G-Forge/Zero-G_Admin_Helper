## ==========================================
## ZERO-G ADMIN HELPER - ECF CODE EDITOR
## A text editor made for Empyrion .ecf files, so they look like code instead of plain text:
##   - line numbers down the left side
##   - colours: { } braces, block names (Trader, Item, Child), keys, "text", numbers, true/false, # comments
##   - the line the cursor is on is softly highlighted
##   - the brace matching the one next to the cursor lights up
## Built only from PyQt6 pieces, so nothing extra needs installing.
## ==========================================

# region Imports

import re

from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QSyntaxHighlighter,
                         QTextCharFormat, QTextFormat, QTextCursor)
from PyQt6.QtWidgets import QPlainTextEdit, QWidget, QTextEdit

# endregion


# region Colours

## One colour per kind of code. Picked to sit well on the cockpit's dark blue background.
ECF_COLORS = {
    "brace": "#33d6ff",
    "block": "#c792ea",
    "key": "#82aaff",
    "string": "#f2b880",
    "number": "#9be38a",
    "keyword": "#ff7eb6",
    "comment": "#6c8396",
}

## Editor background, line number strip, current line and matched brace colours.
EDITOR_LINE_NUMBER_BG = QColor(6, 14, 24)
EDITOR_LINE_NUMBER_TEXT = QColor("#4f6a80")
EDITOR_LINE_NUMBER_CURRENT = QColor("#33d6ff")
EDITOR_CURRENT_LINE = QColor(51, 214, 255, 18)
EDITOR_BRACE_MATCH = QColor(51, 214, 255, 70)

# endregion


# region Highlighter

def _make_format(color_name, bold=False, italic=False):
    """Builds one text style: a colour, plus bold or italic if asked."""
    text_format = QTextCharFormat()
    text_format.setForeground(QColor(ECF_COLORS[color_name]))
    if bold:
        text_format.setFontWeight(QFont.Weight.Bold)
    if italic:
        text_format.setFontItalic(True)
    return text_format


class EcfHighlighter(QSyntaxHighlighter):
    """Colours .ecf text one line at a time. Qt calls highlightBlock for every line that changes."""

    def __init__(self, document):
        super().__init__(document)

        ## (pattern, style, which group to colour). Later rules paint over earlier ones.
        self.rules = [

            ## Numbers, including ranges like 10-50 and decimals like 0.4
            (re.compile(r"\b\d+(\.\d+)?\b"), _make_format("number"), 0),

            ## true / false
            (re.compile(r"\b(true|false)\b", re.IGNORECASE), _make_format("keyword", bold=True), 0),

            ## Keys: a word followed by ':' at the start of a line or after a comma, e.g. 'SellingText:' or ', Name:'
            (re.compile(r"(?:^|,)\s*([+]?[A-Za-z_][\w\.]*)\s*:"), _make_format("key"), 1),

            ## Key right after the block word on a header line, e.g. 'Name:' in '{ Trader Name: Bob'
            (re.compile(r"\{\s*[+]?\s*[A-Za-z_]\w*\s+([A-Za-z_]\w*)\s*:"), _make_format("key"), 1),

            ## Block opener: '{ +Item' or '{ Trader' or '{ Child' -> the block type word
            (re.compile(r"\{\s*[+]?\s*([A-Za-z_]\w*)"), _make_format("block", bold=True), 1),

            ## Braces
            (re.compile(r"[{}]"), _make_format("brace", bold=True), 0),

            ## "Quoted text" (a \" inside does not end it)
            (re.compile(r'"(?:[^"\\]|\\.)*"'), _make_format("string"), 0),
        ]
        self.comment_format = _make_format("comment", italic=True)

    def highlightBlock(self, text):
        for pattern, text_format, group in self.rules:
            for match in pattern.finditer(text):
                start, end = match.span(group)
                if start >= 0:
                    self.setFormat(start, end - start, text_format)

        ## Comments last: everything from the first # that is not inside "quotes" to the end of the line.
        comment_start = _find_comment_start(text)
        if comment_start >= 0:
            self.setFormat(comment_start, len(text) - comment_start, self.comment_format)


def _find_comment_start(text):
    """Returns where a # comment starts on this line, or -1. A # inside "quotes" (like "#ZONE#") doesn't count."""
    in_quotes = False
    previous_char = ""
    for index, char in enumerate(text):
        if char == '"' and previous_char != "\\":
            in_quotes = not in_quotes
        elif char == "#" and not in_quotes:
            return index
        previous_char = char
    return -1

# endregion


# region Line Number Strip

class LineNumberArea(QWidget):
    """The strip down the left side of the editor. The editor does the drawing; this just asks it to."""

    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self):
        return QSize(self.code_editor.line_number_width(), 0)

    def paintEvent(self, event):
        self.code_editor.paint_line_numbers(event)

# endregion


# region EcfCodeEditor Class

class EcfCodeEditor(QPlainTextEdit):
    """The ECF code editor: a QPlainTextEdit with line numbers, colours, current line and brace matching."""

    def __init__(self, parent=None, highlighter_class=None):
        super().__init__(parent)

        ## Name that ZAH_main.css can use to style the editor.
        self.setObjectName("EcfCodeEditor")

        ## Monospace font, so columns line up like in a real code editor.
        code_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        code_font.setPointSize(11)
        self.setFont(code_font)

        ## Long lines scroll sideways instead of wrapping, like most code editors.
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        ## Tab moves 2 spaces' width, matching how .ecf files are indented.
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 2)
        self.setPlaceholderText("No file loaded.")

        ## Which colour rules to use. .ecf by default; the PDA Editor passes its YAML highlighter instead.
        self.highlighter = (highlighter_class or EcfHighlighter)(self.document())
        self.line_number_area = LineNumberArea(self)

        ## Keep the line numbers and highlights in step with typing and scrolling.
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._update_highlights)
        self._update_line_number_width()
        self._update_highlights()

    # region Line Numbers

    def line_number_width(self):
        """How wide the number strip must be for the biggest line number, plus some padding."""
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_width(self, new_block_count=0):

        ## Push the text right so it starts after the number strip.
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, scrolled_by):
        if scrolled_by:
            self.line_number_area.scroll(0, scrolled_by)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        ## Keep the number strip the full height of the editor.
        content = self.contentsRect()
        self.line_number_area.setGeometry(QRect(content.left(), content.top(), self.line_number_width(), content.height()))

    def paint_line_numbers(self, event):
        """Draws the number for every line that is on screen. The cursor's line number is cyan."""
        painter = QPainter(self.line_number_area)
        try:
            painter.fillRect(event.rect(), EDITOR_LINE_NUMBER_BG)
            painter.setFont(self.font())
            current_line = self.textCursor().blockNumber()
            block = self.firstVisibleBlock()
            block_number = block.blockNumber()
            top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
            bottom = top + round(self.blockBoundingRect(block).height())
            line_height = self.fontMetrics().height()
            while block.isValid() and top <= event.rect().bottom():
                if block.isVisible() and bottom >= event.rect().top():
                    painter.setPen(EDITOR_LINE_NUMBER_CURRENT if block_number == current_line else EDITOR_LINE_NUMBER_TEXT)
                    painter.drawText(0, top, self.line_number_area.width() - 8, line_height,
                                     Qt.AlignmentFlag.AlignRight, str(block_number + 1))
                block = block.next()
                top = bottom
                bottom = top + round(self.blockBoundingRect(block).height())
                block_number += 1

        ## finally: always runs, so the painter is closed even if drawing fails.
        finally:
            painter.end()

    # endregion

    # region Highlights

    def _update_highlights(self):
        """Highlights the cursor's line and, if the cursor is next to a { or }, its matching brace."""
        selections = []

        ## Soft band across the whole current line.
        line_selection = QTextEdit.ExtraSelection()
        line_selection.format.setBackground(EDITOR_CURRENT_LINE)
        line_selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        line_selection.cursor = self.textCursor()
        line_selection.cursor.clearSelection()
        selections.append(line_selection)

        ## Brace pair: the brace by the cursor and the one it matches.
        for brace_position in self._matching_brace_positions():
            brace_selection = QTextEdit.ExtraSelection()
            brace_selection.format.setBackground(EDITOR_BRACE_MATCH)
            brace_cursor = self.textCursor()
            brace_cursor.setPosition(brace_position)
            brace_cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            brace_selection.cursor = brace_cursor
            selections.append(brace_selection)
        self.setExtraSelections(selections)

        ## Repaint the numbers so the cyan current-line number follows the cursor.
        self.line_number_area.update()

    def _matching_brace_positions(self):
        """Returns [brace, match] positions if the cursor is right before or after a brace, otherwise []."""
        full_text = self.toPlainText()
        cursor_position = self.textCursor().position()
        for brace_position in (cursor_position, cursor_position - 1):
            if 0 <= brace_position < len(full_text) and full_text[brace_position] in "{}":
                match_position = _find_matching_brace(full_text, brace_position)
                if match_position >= 0:
                    return [brace_position, match_position]
                return []
        return []

    # endregion

    # region Loading

    def load_text(self, file_text):
        """Puts a whole .ecf file into the editor and moves to the top."""
        self.setPlainText(file_text)
        self.moveCursor(QTextCursor.MoveOperation.Start)

    # endregion

# endregion


# region Helpers

def _find_matching_brace(full_text, brace_position):
    """Walks forward from { or backward from } counting nesting until the partner brace is found. -1 if none."""
    opening = full_text[brace_position] == "{"
    step = 1 if opening else -1
    depth = 0
    position = brace_position
    while 0 <= position < len(full_text):
        char = full_text[position]
        if char == "{":
            depth += step
        elif char == "}":
            depth -= step
        if depth == 0:
            return position
        position += step
    return -1

# endregion
