"""JMESPath with the few string functions response mapping needs beyond the standard set."""

from __future__ import annotations

from typing import Any

import jmespath
import jmespath.exceptions
from jmespath import functions


class _Functions(functions.Functions):
    @functions.signature({"types": ["string"]}, {"types": ["string"]})
    def _func_split(self, text: str, separator: str) -> list[str]:
        return text.split(separator)

    @functions.signature({"types": ["string"]})
    def _func_lower(self, text: str) -> str:
        return text.lower()


_OPTIONS = jmespath.Options(custom_functions=_Functions())


def compile(expression: str):  # noqa: A001 — mirrors jmespath.compile
    return jmespath.compile(expression)


def search(expression: str, data: Any) -> Any:
    return jmespath.search(expression, data, options=_OPTIONS)


def unknown_function(expression: str) -> None:
    """Raise if the expression calls a function that does not exist. Compiling alone
    does not catch that; evaluating against nothing does, and any other complaint
    about the empty input is ignored."""
    try:
        search(expression, {})
    except jmespath.exceptions.UnknownFunctionError:
        raise
    except jmespath.exceptions.JMESPathError:
        pass
