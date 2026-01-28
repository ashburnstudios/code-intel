"""Parser registry for managing language-specific parsers."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_intel.parser.base import BaseParser


class ParserRegistry:
    """Registry for language-specific parsers.

    Manages parser instances and provides lookup by language name or file extension.
    """

    def __init__(self) -> None:
        """Initialise an empty parser registry."""
        self._parsers: dict[str, "BaseParser"] = {}
        self._extension_map: dict[str, str] = {}

    def register(self, parser: "BaseParser") -> None:
        """Register a parser for a language.

        Args:
            parser: Parser instance to register. Must implement BaseParser.

        Raises:
            ValueError: If a parser for this language is already registered.
        """
        language = parser.language_name

        if language in self._parsers:
            raise ValueError(f"Parser already registered for language: {language}")

        self._parsers[language] = parser

        # Map file extensions to language
        for ext in parser.file_extensions:
            # Normalise extension to lowercase with leading dot
            ext = ext.lower()
            if not ext.startswith("."):
                ext = f".{ext}"

            if ext in self._extension_map:
                existing = self._extension_map[ext]
                raise ValueError(
                    f"Extension '{ext}' already mapped to '{existing}', "
                    f"cannot map to '{language}'"
                )
            self._extension_map[ext] = language

    def unregister(self, language: str) -> None:
        """Unregister a parser for a language.

        Args:
            language: Language name to unregister.

        Raises:
            KeyError: If no parser is registered for the language.
        """
        if language not in self._parsers:
            raise KeyError(f"No parser registered for language: {language}")

        parser = self._parsers.pop(language)

        # Remove extension mappings
        for ext in parser.file_extensions:
            ext = ext.lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            self._extension_map.pop(ext, None)

    def get_parser(self, language: str) -> "BaseParser | None":
        """Get a parser by language name.

        Args:
            language: Language name (e.g., 'python', 'typescript').

        Returns:
            Parser instance, or None if not registered.
        """
        return self._parsers.get(language)

    def get_parser_for_extension(self, extension: str) -> "BaseParser | None":
        """Get a parser by file extension.

        Args:
            extension: File extension (with or without leading dot).

        Returns:
            Parser instance, or None if no parser handles this extension.
        """
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"

        language = self._extension_map.get(ext)
        if language is None:
            return None
        return self._parsers.get(language)

    def get_parser_for_file(self, path: Path | str) -> "BaseParser | None":
        """Get a parser suitable for a file based on its extension.

        Args:
            path: Path to the file.

        Returns:
            Parser instance, or None if no parser handles files of this type.
        """
        path = Path(path)
        return self.get_parser_for_extension(path.suffix)

    @property
    def languages(self) -> list[str]:
        """List of registered language names."""
        return list(self._parsers.keys())

    @property
    def extensions(self) -> list[str]:
        """List of registered file extensions."""
        return list(self._extension_map.keys())

    def __contains__(self, language: str) -> bool:
        """Check if a parser is registered for a language."""
        return language in self._parsers

    def __len__(self) -> int:
        """Return the number of registered parsers."""
        return len(self._parsers)


# Global registry instance
_global_registry: ParserRegistry | None = None


def get_global_registry() -> ParserRegistry:
    """Get the global parser registry.

    Creates the registry on first call.

    Returns:
        The global ParserRegistry instance.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ParserRegistry()
    return _global_registry


def register_parser(parser: "BaseParser") -> None:
    """Register a parser in the global registry.

    Args:
        parser: Parser instance to register.
    """
    get_global_registry().register(parser)


def get_parser_for_file(path: Path | str) -> "BaseParser | None":
    """Get a parser for a file from the global registry.

    Args:
        path: Path to the file.

    Returns:
        Parser instance, or None if no parser handles files of this type.
    """
    return get_global_registry().get_parser_for_file(path)


def get_parser(language: str) -> "BaseParser | None":
    """Get a parser by language name from the global registry.

    Args:
        language: Language name.

    Returns:
        Parser instance, or None if not registered.
    """
    return get_global_registry().get_parser(language)
