from dataclasses import dataclass
from enum import Enum


class Category(Enum):
    EOL = "end of line"
    KEYWORD = "keyword"
    IDENT = "identifier"
    STRING = "string"
    PUNCT = "punctuation"
    ARROW = "arrow"
    BRACKET = "bracket"
    PAREN = "parenthesis"
    LAMBDA = "λ"


KEYWORDS = {"type", "signature", "structure", "field", "class"}
_PUNCT = {":", "∷", "×", "=", ","}


@dataclass(frozen=True)
class Token:
    category: Category
    text: str
    line: int
    column: int

    def __str__(self) -> str:
        return self.category.value if self.category is Category.EOL else f"{self.category.value} {self.text!r}"


class ParseError(Exception):
    def __init__(self, line: int, column: int, message: str):
        super().__init__(f"{line}:{column}: {message}")
        self.line, self.column = line, column


def is_ident_char(ch: str) -> bool:
    code = ord(ch)
    return (code <= 255 and ch.isalnum()) or 0x1D62 <= code < 0x1D66 or 0x2070 <= code < 0x20A0 \
        or 0x00B0 <= code < 0x00C0 or ch in "?_'%∅"


def tokenize(text: str) -> list[Token]:
    tokens = []
    i, line, line_start = 0, 1, 0

    while i < len(text):

        ch, column = text[i], i - line_start + 1
        if ch == "\n":
            tokens.append(Token(Category.EOL, ch, line, column))
            i, line, line_start = i + 1, line + 1, i + 1

        elif ch in " \t\r":
            i += 1

        elif ch == ";":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end

        elif ch == '"':
            end = text.find('"', i + 1)
            if end < 0 or "\n" in text[i:end]:
                raise ParseError(line, column, "unterminated string")
            tokens.append(Token(Category.STRING, text[i + 1:end], line, column))
            i = end + 1

        elif ch == "→" or text.startswith("->", i):
            arrow = "→" if ch == "→" else "->"
            tokens.append(Token(Category.ARROW, arrow, line, column))
            i += len(arrow)

        elif ch in _PUNCT or ch in "[]()λ":
            category = (Category.PUNCT if ch in _PUNCT else Category.BRACKET if ch in "[]"
                        else Category.PAREN if ch in "()" else Category.LAMBDA)
            tokens.append(Token(category, ch, line, column))
            i += 1

        elif is_ident_char(ch):
            end = i
            while end < len(text) and is_ident_char(text[end]):
                end += 1
            word = text[i:end]
            tokens.append(Token(Category.KEYWORD if word in KEYWORDS else Category.IDENT, word, line, column))
            i = end

        else:
            raise ParseError(line, column, f"unexpected character {ch!r}")

    return tokens
