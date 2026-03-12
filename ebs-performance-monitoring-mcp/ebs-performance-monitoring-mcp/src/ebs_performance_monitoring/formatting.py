"""CLI Output Formatting Utilities

Provides common formatting functions for CLI-friendly output of MCP tools.
"""

from typing import Optional


# Default output width (internal content area excluding borders)
DEFAULT_WIDTH = 58


class CLIFormatter:
    """CLI Output Formatter
    
    Utility class for generating box-style CLI output.
    
    Example:
        >>> fmt = CLIFormatter()
        >>> lines = fmt.header("Title")
        >>> lines.extend(fmt.section("Info", ["Key: Value"]))
        >>> print("\\n".join(lines))
    """
    
    def __init__(self, width: int = DEFAULT_WIDTH):
        """Initialize formatter
        
        Args:
            width: Internal content area width (default: 58)
        """
        self.width = width
    
    def header(self, title: str) -> list[str]:
        """Create header box (═ double border)
        
        Args:
            title: Header title
            
        Returns:
            list[str]: Formatted header lines
        """
        return [
            "╔" + "═" * self.width + "╗",
            "║" + title.center(self.width) + "║",
            "╚" + "═" * self.width + "╝"
        ]
    
    def section(self, title: str, content: list[str]) -> list[str]:
        """Create section box (─ single border)
        
        Args:
            title: Section title
            content: Section content lines (empty string treated as blank line)
            
        Returns:
            list[str]: Formatted section lines
        """
        lines = []
        header = f"┌─ {title} "
        lines.append(header + "─" * (self.width - len(header)) + "┐")
        
        for line in content:
            if line == "":
                lines.append("│" + " " * self.width + "│")
            else:
                lines.append("│ " + line.ljust(self.width - 2) + " │")
        
        lines.append("└" + "─" * self.width + "┘")
        return lines
    
    def divider(self, char: str = "─") -> str:
        """Create divider line
        
        Args:
            char: Divider character (default: ─)
            
        Returns:
            str: Divider string
        """
        return char * (self.width + 2)
    
    def key_value(self, key: str, value, key_width: int = 16) -> str:
        """Format key-value pair
        
        Args:
            key: Key name
            value: Value
            key_width: Key area width (default: 16)
            
        Returns:
            str: Formatted key-value string
        """
        return f"{key:<{key_width}} : {value}"
    
    def format_number(self, value: float, decimals: int = 2) -> str:
        """Format number (with thousand separators)
        
        Args:
            value: Numeric value
            decimals: Decimal places (default: 2)
            
        Returns:
            str: Formatted number string
        """
        if decimals == 0:
            return f"{int(value):,}"
        return f"{value:,.{decimals}f}"
    
    def format_bytes(self, bytes_value: int, unit: str = "GiB") -> str:
        """Convert bytes to specified unit
        
        Args:
            bytes_value: Byte value
            unit: Target unit (GiB, MiB, KiB)
            
        Returns:
            str: Formatted size string
        """
        divisors = {
            "GiB": 1024 ** 3,
            "MiB": 1024 ** 2,
            "KiB": 1024,
        }
        divisor = divisors.get(unit, 1)
        converted = bytes_value / divisor
        return f"{converted:.3f} {unit}"
    
    def progress_bar(
        self, 
        percent: float, 
        width: int = 20,
        filled: str = "█",
        empty: str = "░"
    ) -> str:
        """Create progress bar
        
        Args:
            percent: Percentage value (0-100)
            width: Bar width (default: 20)
            filled: Filled portion character
            empty: Empty portion character
            
        Returns:
            str: Progress bar string
        """
        percent = max(0, min(100, percent))
        filled_width = int(width * percent / 100)
        bar = filled * filled_width + empty * (width - filled_width)
        return f"[{bar}] {percent:.1f}%"


# Default instance for convenience
default_formatter = CLIFormatter()


def make_header(title: str, width: int = DEFAULT_WIDTH) -> list[str]:
    """Create header box (functional interface)"""
    return CLIFormatter(width).header(title)


def make_section(title: str, content: list[str], width: int = DEFAULT_WIDTH) -> list[str]:
    """Create section box (functional interface)"""
    return CLIFormatter(width).section(title, content)
