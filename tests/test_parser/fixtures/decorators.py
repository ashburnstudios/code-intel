"""Sample Python file with decorators for testing."""

from dataclasses import dataclass, field
from functools import wraps
from typing import Callable


def simple_decorator(func: Callable) -> Callable:
    """A simple decorator."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def decorator_with_args(value: int):
    """A decorator that takes arguments."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs) + value

        return wrapper

    return decorator


@simple_decorator
def decorated_function():
    """Function with single decorator."""
    return "decorated"


@simple_decorator
@decorator_with_args(10)
def multi_decorated_function() -> int:
    """Function with multiple decorators."""
    return 5


@dataclass
class DataClass:
    """A dataclass for testing dataclass extraction."""

    name: str
    value: int = 0
    items: list = field(default_factory=list)


@dataclass(frozen=True)
class FrozenDataClass:
    """A frozen dataclass."""

    id: int
    name: str


class MyClass:
    """Class with decorated methods."""

    @staticmethod
    def static_method():
        """A static method."""
        return "static"

    @classmethod
    def class_method(cls):
        """A class method."""
        return cls.__name__

    @property
    def my_property(self) -> str:
        """A property."""
        return "property_value"

    @my_property.setter
    def my_property(self, value: str) -> None:
        """Property setter."""
        pass
