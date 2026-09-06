"""The conformance suite an MCP tool server passes before a deployment admits it.

The families are pytest modules in this package. A runner points them at a URL
with ``pytest --pyargs mcp_conformance --mcp-endpoint ...`` and reads the report.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
