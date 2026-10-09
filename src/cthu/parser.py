from dataclasses import dataclass, field

from .lexer import Category, ParseError, Token, tokenize

OpType = tuple[list[str], list[str]]  # input types, output types
Reference = tuple[str, list[str]]  # a signature, with its arguments


@dataclass
class Signature:
    name: str
    params: list[str]
    parents: list[Reference]  # the signatures it extends
    operations: dict[str, OpType]


@dataclass
class Instruction:
    structure: str
    op: str
    ins: list[str]
    outs: list[str]


@dataclass
class LambdaDef:
    params: list[str]
    outs: list[str]
    body: list[Instruction]


@dataclass
class StructureDef:
    name: str
    implements: list[Reference]
    builtins: dict[str, str] = field(default_factory=dict)  # operation = builtin
    lambdas: dict[str, LambdaDef] = field(default_factory=dict)  # operation = λ …


@dataclass
class Module:
    types: list[str] = field(default_factory=list)
    signatures: dict[str, Signature] = field(default_factory=dict)
    structures: dict[str, StructureDef] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)  # `field T "name"`: name → T, in order
    classes: list[str] = field(default_factory=list)  # `class "name"`, in order


def parse(text: str) -> Module:
    return _Parser(tokenize(text)).module()


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0
        self.parsed = Module()

    # --- tokens -------------------------------------------------------------

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def accept(self, category: Category, text: str | None = None) -> Token | None:
        token = self.peek()
        if token is None or token.category is not category or (text is not None and token.text != text):
            return None
        self.i += 1
        return token

    def expect(self, category: Category, text: str | None = None) -> Token:
        token = self.accept(category, text)
        if token is None:
            self.fail(f"expected {repr(text) if text else category.value}, found {self.peek() or 'the end'}")
        return token

    def fail(self, message: str, token: Token | None = None):
        token = token or self.peek() or (self.tokens[-1] if self.tokens else Token(Category.EOL, "", 1, 1))
        raise ParseError(token.line, token.column, message)

    def lines(self) -> None:
        while self.accept(Category.EOL):
            pass

    def end_of_line(self) -> None:
        if self.peek() is not None:
            self.expect(Category.EOL)

    def name(self) -> str:
        return self.expect(Category.IDENT).text

    def names(self) -> list[str]:
        names = []
        while token := self.accept(Category.IDENT):
            names.append(token.text)
        return names

    def open(self) -> None:
        self.lines()
        self.expect(Category.PAREN, "(")

    def closed(self) -> bool:
        """Whether the block ends here. Its items are separated by lines."""
        self.lines()
        if self.peek() is None:
            self.fail("expected ')', found the end")
        return self.accept(Category.PAREN, ")") is not None

    # --- declarations -------------------------------------------------------

    def module(self) -> Module:
        self.lines()
        while self.peek() is not None:
            keyword = self.expect(Category.KEYWORD).text
            if keyword == "type":
                self.parsed.types.append(self.name())
            elif keyword == "signature":
                self.signature()
            elif keyword == "structure":
                self.structure()
            elif keyword == "field":
                type_ = self.name()
                self.parsed.fields[self.expect(Category.STRING).text] = type_
            else:
                self.parsed.classes.append(self.expect(Category.STRING).text)
            self.end_of_line()
            self.lines()
        return self.parsed

    def arguments(self) -> list[str]:
        """`[ T, S, B ]`"""
        self.expect(Category.BRACKET, "[")
        args = []
        while not self.accept(Category.BRACKET, "]"):
            if args:
                self.expect(Category.PUNCT, ",")
            args.append(self.name())
        return args

    def references(self) -> list[Reference]:
        """`simple[ T, S, B ], bitwise[ T, I ]`"""
        refs = [(self.name(), self.arguments())]
        while self.accept(Category.PUNCT, ","):
            self.lines()
            refs.append((self.name(), self.arguments()))
        return refs

    def product(self) -> list[str]:
        """`T × T`, or `∅` for none."""
        if self.accept(Category.IDENT, "∅"):
            return []
        types = [self.name()]
        while self.accept(Category.PUNCT, "×"):
            types.append(self.name())
        return types

    def signature(self) -> None:
        name = self.expect(Category.IDENT)
        if name.text in self.parsed.signatures:
            self.fail(f"signature {name.text} is defined twice", name)

        params = self.arguments()
        parents = self.references() if self.accept(Category.PUNCT, ":") else []
        operations = {}
        self.open()

        while not self.closed():
            op = self.expect(Category.IDENT)
            if op.text in operations:
                self.fail(f"{name.text} declares {op.text} twice", op)
            self.expect(Category.PUNCT, "∷")
            ins = self.product()
            self.expect(Category.ARROW)
            operations[op.text] = (ins, self.product())

        self.parsed.signatures[name.text] = Signature(name.text, params, parents, operations)

    def structure(self) -> None:
        name = self.expect(Category.IDENT)
        if name.text in self.parsed.structures:
            self.fail(f"structure {name.text} is defined twice", name)

        structure = StructureDef(name.text, self.references() if self.accept(Category.PUNCT, ":") else [])
        self.open()

        while not self.closed():
            member = self.expect(Category.IDENT)
            if member.text in structure.builtins or member.text in structure.lambdas:
                self.fail(f"{name.text} defines {member.text} twice", member)
            self.expect(Category.PUNCT, "=")
            if self.accept(Category.LAMBDA):
                structure.lambdas[member.text] = self.lambda_()
            else:
                structure.builtins[member.text] = self.name()
        self.parsed.structures[name.text] = structure

    def lambda_(self) -> LambdaDef:
        """`λ p0 h → hout`, then its instructions in parentheses."""
        params = self.names()
        self.expect(Category.ARROW)
        lam = LambdaDef(params, self.names(), [])
        self.open()
        while not self.closed():
            structure, op = self.name(), self.name()
            ins = self.names()
            lam.body.append(Instruction(structure, op, ins, self.names() if self.accept(Category.ARROW) else []))
        return lam
