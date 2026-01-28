"""Sample Python file with class definitions for testing."""

from abc import ABC, abstractmethod


class SimpleClass:
    """A simple class with methods."""

    def __init__(self, value: int):
        """Initialise the class."""
        self.value = value

    def get_value(self) -> int:
        """Return the value."""
        return self.value

    def set_value(self, value: int) -> None:
        """Set the value."""
        self.value = value


class ChildClass(SimpleClass):
    """A class that inherits from SimpleClass."""

    def __init__(self, value: int, name: str):
        """Initialise with extra name field."""
        super().__init__(value)
        self.name = name

    def get_name(self) -> str:
        """Return the name."""
        return self.name


class MultipleInheritance(SimpleClass, ABC):
    """Class with multiple inheritance."""

    @abstractmethod
    def abstract_method(self) -> None:
        """An abstract method."""
        pass


class Outer:
    """Outer class with nested class."""

    class Inner:
        """Nested inner class."""

        def inner_method(self) -> str:
            """Method in nested class."""
            return "inner"
