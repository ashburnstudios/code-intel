"""Sample Python file with function call chains for testing."""


def helper_a():
    """First helper function."""
    return "a"


def helper_b():
    """Second helper function that calls helper_a."""
    return helper_a() + "b"


def helper_c():
    """Third helper that calls helper_b."""
    return helper_b() + "c"


def main_processor():
    """Main function that calls multiple helpers."""
    a = helper_a()
    b = helper_b()
    c = helper_c()
    return a + b + c


class Processor:
    """Class with methods that call each other."""

    def step_one(self):
        """First step."""
        return "step1"

    def step_two(self):
        """Second step that calls step_one."""
        result = self.step_one()
        return result + "_step2"

    def step_three(self):
        """Third step that calls step_two."""
        result = self.step_two()
        helper_a()  # Also calls module-level function
        return result + "_step3"

    def process(self):
        """Main process that orchestrates all steps."""
        return self.step_three()


def module_level_call():
    """Function that makes module-level calls."""
    result = main_processor()
    processor = Processor()
    processor.process()
    return result
