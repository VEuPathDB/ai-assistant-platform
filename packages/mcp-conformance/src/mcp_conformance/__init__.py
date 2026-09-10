"""The conformance suite an MCP tool server passes before a deployment admits it.

The families are pytest modules in this package. A runner points them at a URL
with ``pytest --pyargs mcp_conformance --mcp-endpoint ...`` and reads the report.
"""

from __future__ import annotations

from importlib.metadata import version

# The distribution's own number, so the report an operator signs cannot name a
# version the package is not.
__version__ = version("veupathdb-mcp-conformance")

__all__ = ["__version__"]
