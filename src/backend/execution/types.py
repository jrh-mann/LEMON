"""Expression tree types for parsed conditions"""

from dataclasses import dataclass
from typing import Any


class Expr:
    """Base class for all expression nodes"""
    pass


@dataclass
class BinaryOp(Expr):
    """Binary operation: left operator right"""
    left: Expr
    operator: str  # "AND", "OR", ">=", "<=", "==", "!=", ">", "<"
    right: Expr

    def __repr__(self) -> str:
        return f"BinaryOp({self.left} {self.operator} {self.right})"


@dataclass
class UnaryOp(Expr):
    """Unary operation: operator operand"""
    operator: str  # "NOT"
    operand: Expr

    def __repr__(self) -> str:
        return f"UnaryOp({self.operator} {self.operand})"


@dataclass
class Variable(Expr):
    """Variable reference (e.g., Age, Smoker)"""
    name: str

    def __repr__(self) -> str:
        return f"Variable({self.name})"


@dataclass
class Literal(Expr):
    """Literal value (number, string, boolean)"""
    value: Any  # int, float, str, bool

    def __repr__(self) -> str:
        if isinstance(self.value, str):
            return f"Literal('{self.value}')"
        return f"Literal({self.value})"
