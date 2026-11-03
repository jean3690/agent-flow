"""Restricted expression evaluation used by condition nodes and templates.

Only a whitelisted subset of Python AST is allowed: literals, names, attribute/key
access, arithmetic, comparisons, boolean logic, conditionals, containers and a small
set of pure builtins. No imports, no lambdas, no comprehensions, no calls to
arbitrary objects.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from app.core.errors import FlowValidationError

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

_SAFE_FUNCS: dict[str, Any] = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "any": any,
    "all": all,
    "lower": lambda v: str(v).lower(),
    "upper": lambda v: str(v).upper(),
    "contains": lambda haystack, needle: needle in haystack,
}


def evaluate(expression: str, names: dict[str, Any]) -> Any:
    expression = (expression or "").strip()
    if not expression:
        return None
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise FlowValidationError(f"表达式语法错误: {expression}") from exc
    return _eval(tree.body, names)


def _eval(node: ast.AST, names: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        if node.id in _SAFE_FUNCS:
            return _SAFE_FUNCS[node.id]
        raise FlowValidationError(f"未知变量: {node.id}")
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise FlowValidationError("不允许访问私有属性")
        target = _eval(node.value, names)
        if isinstance(target, dict):
            return target.get(node.attr)
        return getattr(target, node.attr, None)
    if isinstance(node, ast.Subscript):
        target = _eval(node.value, names)
        key = _eval(node.slice, names)
        try:
            return target[key]
        except (KeyError, IndexError, TypeError):
            return None
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, names) for v in node.values]
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in values:
                result = value
                if not value:
                    return value
            return result
        for value in values:
            if value:
                return value
        return values[-1] if values else False
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, names)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise FlowValidationError("不支持的一元运算符")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if not op:
            raise FlowValidationError("不支持的二元运算符")
        return op(_eval(node.left, names), _eval(node.right, names))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, names)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _CMP_OPS.get(type(op_node))
            if not op:
                raise FlowValidationError("不支持的比较运算符")
            right = _eval(comparator, names)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, names) if _eval(node.test, names) else _eval(node.orelse, names)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS:
            raise FlowValidationError("只允许调用内置安全函数")
        func = _SAFE_FUNCS[node.func.id]
        return func(*[_eval(a, names) for a in node.args], **{k.arg: _eval(k.value, names) for k in node.keywords if k.arg})
    if isinstance(node, ast.List):
        return [_eval(e, names) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, names) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {_eval(k, names): _eval(v, names) for k, v in zip(node.keys, node.values)}
    raise FlowValidationError(f"不支持的表达式节点: {type(node).__name__}")


def truthy(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"false", "0", "no", "off", "null", "none", ""}:
            return False
        return True
    return bool(value)
