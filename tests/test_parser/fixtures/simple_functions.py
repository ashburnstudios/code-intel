"""Sample Python file with simple function definitions for testing."""


def simple_function():
    """A simple function with no parameters."""
    pass


def function_with_params(a: int, b: str = "default") -> str:
    """Function with typed parameters and return type."""
    return f"{a}: {b}"


async def async_function():
    """An async function."""
    pass


def outer_function():
    """Outer function containing a nested function."""

    def nested_function():
        """This should not be extracted at module level."""
        pass

    return nested_function
