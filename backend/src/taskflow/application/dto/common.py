"""Shared DTO helpers."""

from __future__ import annotations

from typing import Any, Final, TypeGuard


class _Unset:
    """Sentinel meaning "the client did not mention this field".

    PATCH needs three states per field, not two: *set to a value*, *set to
    null*, and *untouched*. Using ``None`` for both of the last two makes it
    impossible to clear a nullable field such as ``due_date`` -- a bug you
    only notice when a user tries to remove a deadline and nothing happens.
    """

    __slots__ = ()
    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"

    def __copy__(self) -> _Unset:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _Unset:
        return self


UNSET: Final = _Unset()

type Maybe[T] = T | _Unset


def is_set[T](value: Maybe[T]) -> TypeGuard[T]:
    """Narrow ``Maybe[T]`` to ``T``; use instead of a bare truthiness check.

    ``if value:`` would wrongly skip legitimate falsy payloads such as an
    empty description or ``priority=0``.
    """
    return not isinstance(value, _Unset)
