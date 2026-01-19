"""Condition parser: string → expression tree

Parses condition strings like:
- "Age >= 18"
- "BMI >= 18.5 AND BMI < 25"
- "Condition == 'Hypertension' OR Condition == 'Heart Disease'"
- "NOT Convicted == True"
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Optional, Any
from .types import Expr, BinaryOp, UnaryOp, Variable, Literal


class TokenType(Enum):
    """Token types for lexical analysis"""
    # Literals
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    BOOL = auto()

    # Operators
    GTE = auto()        # >=
    LTE = auto()        # <=
    EQ = auto()         # ==
    NEQ = auto()        # !=
    GT = auto()         # >
    LT = auto()         # <

    # Logical operators
    AND = auto()
    OR = auto()
    NOT = auto()

    # Parentheses
    LPAREN = auto()
    RPAREN = auto()

    # End of input
    EOF = auto()


@dataclass
class Token:
    """A lexical token"""
    type: TokenType
    value: Any
    position: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, pos={self.position})"


class LexerError(Exception):
    """Raised when lexer encounters invalid input"""
    pass


class ParseError(Exception):
    """Raised when parser encounters invalid syntax"""
    pass


class Lexer:
    """Tokenize condition strings"""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.current_char: Optional[str] = text[0] if text else None

    def advance(self) -> None:
        """Move to next character"""
        self.pos += 1
        if self.pos >= len(self.text):
            self.current_char = None
        else:
            self.current_char = self.text[self.pos]

    def peek(self, offset: int = 1) -> Optional[str]:
        """Look ahead at next character without consuming"""
        peek_pos = self.pos + offset
        if peek_pos >= len(self.text):
            return None
        return self.text[peek_pos]

    def skip_whitespace(self) -> None:
        """Skip whitespace characters"""
        while self.current_char is not None and self.current_char.isspace():
            self.advance()

    def read_number(self) -> Token:
        """Read integer or float number"""
        start_pos = self.pos
        num_str = ""

        # Read digits and at most one decimal point
        has_decimal = False
        while self.current_char is not None and (self.current_char.isdigit() or self.current_char == '.'):
            if self.current_char == '.':
                if has_decimal:
                    raise LexerError(f"Invalid number format at position {self.pos}")
                has_decimal = True
            num_str += self.current_char
            self.advance()

        # Parse as int or float
        try:
            if has_decimal:
                value = float(num_str)
            else:
                value = int(num_str)
        except ValueError:
            raise LexerError(f"Invalid number '{num_str}' at position {start_pos}")

        return Token(TokenType.NUMBER, value, start_pos)

    def read_string(self, quote_char: str) -> Token:
        """Read string literal with quotes"""
        start_pos = self.pos
        self.advance()  # Skip opening quote

        string_value = ""
        while self.current_char is not None and self.current_char != quote_char:
            string_value += self.current_char
            self.advance()

        if self.current_char != quote_char:
            raise LexerError(f"Unclosed string starting at position {start_pos}")

        self.advance()  # Skip closing quote
        return Token(TokenType.STRING, string_value, start_pos)

    def read_identifier_or_keyword(self) -> Token:
        """Read identifier or keyword (AND, OR, NOT, True, False)"""
        start_pos = self.pos
        identifier = ""

        # Read alphanumeric and underscores
        while self.current_char is not None and (self.current_char.isalnum() or self.current_char == '_'):
            identifier += self.current_char
            self.advance()

        # Check for keywords (case-insensitive)
        identifier_upper = identifier.upper()
        if identifier_upper == "AND":
            return Token(TokenType.AND, "AND", start_pos)
        elif identifier_upper == "OR":
            return Token(TokenType.OR, "OR", start_pos)
        elif identifier_upper == "NOT":
            return Token(TokenType.NOT, "NOT", start_pos)
        elif identifier_upper == "TRUE":
            return Token(TokenType.BOOL, True, start_pos)
        elif identifier_upper == "FALSE":
            return Token(TokenType.BOOL, False, start_pos)
        else:
            # Regular identifier (preserve original case)
            return Token(TokenType.IDENTIFIER, identifier, start_pos)

    def get_next_token(self) -> Token:
        """Get next token from input"""
        while self.current_char is not None:
            # Skip whitespace
            if self.current_char.isspace():
                self.skip_whitespace()
                continue

            # Numbers
            if self.current_char.isdigit():
                return self.read_number()

            # Strings
            if self.current_char in ('"', "'"):
                return self.read_string(self.current_char)

            # Identifiers and keywords
            if self.current_char.isalpha() or self.current_char == '_':
                return self.read_identifier_or_keyword()

            # Two-character operators
            if self.current_char == '>' and self.peek() == '=':
                pos = self.pos
                self.advance()
                self.advance()
                return Token(TokenType.GTE, ">=", pos)

            if self.current_char == '<' and self.peek() == '=':
                pos = self.pos
                self.advance()
                self.advance()
                return Token(TokenType.LTE, "<=", pos)

            if self.current_char == '=' and self.peek() == '=':
                pos = self.pos
                self.advance()
                self.advance()
                return Token(TokenType.EQ, "==", pos)

            if self.current_char == '!' and self.peek() == '=':
                pos = self.pos
                self.advance()
                self.advance()
                return Token(TokenType.NEQ, "!=", pos)

            # Single-character operators
            if self.current_char == '>':
                pos = self.pos
                self.advance()
                return Token(TokenType.GT, ">", pos)

            if self.current_char == '<':
                pos = self.pos
                self.advance()
                return Token(TokenType.LT, "<", pos)

            if self.current_char == '(':
                pos = self.pos
                self.advance()
                return Token(TokenType.LPAREN, "(", pos)

            if self.current_char == ')':
                pos = self.pos
                self.advance()
                return Token(TokenType.RPAREN, ")", pos)

            # Unknown character
            raise LexerError(f"Unexpected character '{self.current_char}' at position {self.pos}")

        # End of input
        return Token(TokenType.EOF, None, self.pos)

    def tokenize(self) -> List[Token]:
        """Tokenize entire input string"""
        tokens = []
        while True:
            token = self.get_next_token()
            tokens.append(token)
            if token.type == TokenType.EOF:
                break
        return tokens


class Parser:
    """Parse tokens into expression tree using recursive descent"""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.current_token = tokens[0] if tokens else Token(TokenType.EOF, None, 0)

    def advance(self) -> None:
        """Move to next token"""
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current_token = self.tokens[self.pos]
        else:
            self.current_token = Token(TokenType.EOF, None, self.pos)

    def expect(self, token_type: TokenType) -> Token:
        """Consume token of expected type or raise error"""
        if self.current_token.type != token_type:
            raise ParseError(
                f"Expected {token_type.name}, got {self.current_token.type.name} "
                f"at position {self.current_token.position}"
            )
        token = self.current_token
        self.advance()
        return token

    def parse(self) -> Expr:
        """Parse expression from tokens"""
        expr = self.parse_or_expr()
        if self.current_token.type != TokenType.EOF:
            raise ParseError(
                f"Unexpected token {self.current_token.type.name} at position {self.current_token.position}"
            )
        return expr

    def parse_or_expr(self) -> Expr:
        """Parse OR expression (lowest precedence)

        or_expr := and_expr ('OR' and_expr)*
        """
        left = self.parse_and_expr()

        while self.current_token.type == TokenType.OR:
            self.advance()
            right = self.parse_and_expr()
            left = BinaryOp(left, "OR", right)

        return left

    def parse_and_expr(self) -> Expr:
        """Parse AND expression

        and_expr := not_expr ('AND' not_expr)*
        """
        left = self.parse_not_expr()

        while self.current_token.type == TokenType.AND:
            self.advance()
            right = self.parse_not_expr()
            left = BinaryOp(left, "AND", right)

        return left

    def parse_not_expr(self) -> Expr:
        """Parse NOT expression

        not_expr := 'NOT' not_expr | comparison
        """
        if self.current_token.type == TokenType.NOT:
            self.advance()
            operand = self.parse_not_expr()  # Right-associative
            return UnaryOp("NOT", operand)

        return self.parse_comparison()

    def parse_comparison(self) -> Expr:
        """Parse comparison expression

        comparison := term (comp_op term)?
        comp_op := '>=' | '<=' | '==' | '!=' | '>' | '<'
        """
        left = self.parse_term()

        # Check for comparison operator
        if self.current_token.type in (
            TokenType.GTE, TokenType.LTE, TokenType.EQ,
            TokenType.NEQ, TokenType.GT, TokenType.LT
        ):
            operator = self.current_token.value
            self.advance()
            right = self.parse_term()
            return BinaryOp(left, operator, right)

        return left

    def parse_term(self) -> Expr:
        """Parse terminal expression

        term := IDENTIFIER | NUMBER | STRING | BOOL | '(' expression ')'
        """
        # Parentheses
        if self.current_token.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_or_expr()  # Reset precedence
            self.expect(TokenType.RPAREN)
            return expr

        # Identifier (variable)
        if self.current_token.type == TokenType.IDENTIFIER:
            name = self.current_token.value
            self.advance()
            return Variable(name)

        # Number literal
        if self.current_token.type == TokenType.NUMBER:
            value = self.current_token.value
            self.advance()
            return Literal(value)

        # String literal
        if self.current_token.type == TokenType.STRING:
            value = self.current_token.value
            self.advance()
            return Literal(value)

        # Boolean literal
        if self.current_token.type == TokenType.BOOL:
            value = self.current_token.value
            self.advance()
            return Literal(value)

        # Unexpected token
        raise ParseError(
            f"Unexpected token {self.current_token.type.name} at position {self.current_token.position}"
        )


def parse_condition(condition_str: str) -> Expr:
    """Parse condition string into expression tree

    Args:
        condition_str: Condition string (e.g., "Age >= 18 AND Smoker == True")

    Returns:
        Expression tree root node

    Raises:
        LexerError: If tokenization fails
        ParseError: If parsing fails

    Examples:
        >>> expr = parse_condition("Age >= 18")
        >>> isinstance(expr, BinaryOp)
        True
        >>> expr.operator
        '>='
    """
    if not condition_str or not condition_str.strip():
        raise ParseError("Empty condition string")

    # Tokenize
    lexer = Lexer(condition_str)
    tokens = lexer.tokenize()

    # Parse
    parser = Parser(tokens)
    return parser.parse()
