"""Sample Python file with module-level variables for testing."""

# Simple constants
MY_CONSTANT = 42
STRING_CONSTANT = "hello"
FLOAT_CONSTANT = 3.14

# Type annotated constants
TYPED_INT: int = 100
TYPED_STR: str = "typed"

# Container types
MY_LIST = [1, 2, 3]
MY_DICT = {"key": "value"}
MY_SET = {1, 2, 3}
MY_TUPLE = (1, 2, 3)

# Tuple unpacking
a, b, c = 1, 2, 3
x, y = "hello", "world"

# Computed values
COMPUTED = MY_CONSTANT * 2

# Constants from other modules (typical pattern)
from os import sep as PATH_SEP
from sys import version_info as VERSION


# Class-level variables are NOT module level
class ConfigClass:
    """Class with class-level variables."""

    class_var = "class_level"

    def __init__(self):
        self.instance_var = "instance_level"
