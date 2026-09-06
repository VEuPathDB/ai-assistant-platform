"""The extension point an operator's harness implements, because it is theirs.

"What this account holds" is the server's own idea, so the suite asks for it
rather than deciding it. A plugin the runner loads with ``-p`` answers.
"""

from __future__ import annotations

import pytest

from mcp_conformance._probe import AccountSnapshot


@pytest.hookspec(firstresult=True)
def pytest_mcp_account_state() -> AccountSnapshot | None:
    """Answer with a callable that lists what the credential's account holds.

    The identifiers are the server's own; the suite only compares them before a
    call and after it. Answer None to leave the comparison unsettled.
    """
