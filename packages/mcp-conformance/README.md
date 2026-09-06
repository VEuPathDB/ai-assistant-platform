# veupathdb-mcp-conformance

The conformance suite an MCP tool server passes before a VEuPathDB assistant
deployment admits it. It is a pytest plugin plus the families themselves, and
it imports nothing of the deployment: point it at a URL, give it a credential,
read the report.

```
pip install veupathdb-mcp-conformance
pytest --pyargs mcp_conformance \
  --mcp-endpoint https://example.org/mcp \
  --mcp-bearer "$MCP_CONFORMANCE_BEARER" \
  --mcp-report report.json
```

`--mcp-endpoint`, `--mcp-bearer` and `--mcp-bearer-second` also read
`MCP_CONFORMANCE_ENDPOINT`, `MCP_CONFORMANCE_BEARER` and
`MCP_CONFORMANCE_BEARER_SECOND`, so a credential never has to appear on a
command line.

Run one family with its module name: `pytest --pyargs mcp_conformance.test_shape`.

## Options

| Option | Meaning |
|---|---|
| `--mcp-endpoint` | The streamable-HTTP MCP endpoint under test. Without it every family skips. |
| `--mcp-bearer` | The credential the calls carry. |
| `--mcp-bearer-second` | A second identity, which turns on the isolation check. |
| `--mcp-report` | Where the admission report JSON is written. |
| `--mcp-sample-args` | JSON object, or a path to one, mapping a tool name to the arguments a call may use. Tools that need no arguments are called without it. |
| `--mcp-slow-tool` | The tool the timeout family drives past its budget. |
| `--mcp-max-call-seconds` | The budget for a tool that declares none. Default 60. |
| `--mcp-isolation-tool` | The tool the isolation check drives, naming a resource the second identity owns. |

## The families

| # | Module | What it settles |
|---|---|---|
| 1 | `test_shape` | `initialize` negotiates a revision the report names; tool names are unique and prefix-safe; descriptions are non-empty; every `inputSchema` is an object schema; a tool declaring `org.veupathdb.assistant/streamPart` also declares an `outputSchema`. |
| 2 | `test_auth` | No credential and a wrong credential both fail as protocol errors, never as results; a 401 carries `WWW-Authenticate` with `resource_metadata`; no credential appears in any result or error; one identity cannot read another's resource. |
| 3 | `test_annotations` | Every tool declares `readOnlyHint` explicitly; a tool claiming `readOnlyHint: true` leaves the account unchanged across two calls; `idempotentHint: true` returns the same result twice. |
| 4 | `test_errors` | A bad argument is a tool error that names the offending field, never a transport error and never a stack trace. Only tools declaring `readOnlyHint: true` are probed: the probe exists to find out what a server does when its own validation is broken. |
| 5 | `test_timeouts` | `initialize` answers inside the client's 5 second budget; a call driven past its budget times out on the client and the session survives. |
| 6 | `test_stability` | `tools/list` is identical across two fresh connections. |

## Two extension points, because two checks are server-domain-specific

**Account state.** Family 3 proves `readOnlyHint` by comparing the account
before and after two calls, and what "the account" is belongs to the server.
Write a small plugin that answers the `pytest_mcp_account_state` hook with a
callable listing the identifiers this account holds, and load it with
`-p your_hook`. Without it the comparisons skip and the report says so.

```python
# your_hook.py, loaded with: pytest --pyargs mcp_conformance -p your_hook
def pytest_mcp_account_state():
    async def snapshot() -> list[str]:
        ...  # the identifiers of what this account holds, in any stable order
    return snapshot
```

The hook is a pytest hook rather than a fixture on purpose: a fixture defined in
your `conftest.py` is not visible to tests that live inside this package, and one
defined in a `-p` plugin loses to the plugin this package installs.

**A foreign resource.** Family 2's isolation check needs a resource the second
identity owns. Name the tool with `--mcp-isolation-tool` and its arguments
through `--mcp-sample-args`; the arguments name a resource of the
`--mcp-bearer-second` identity, and the check refuses to pass unless that
identity can read it. A fabricated identifier is refused for both callers, and
that is not isolation.

## The report

`--mcp-report` writes the admission record: what answered, what it declared,
and what each family settled. Credentials are redacted from every message the
report carries.

```json
{
  "suite": { "name": "veupathdb-mcp-conformance", "version": "0.1.0" },
  "generatedAt": "2026-08-25T00:00:00+00:00",
  "verdict": "pass",
  "target": { "endpoint": "https://example.org/mcp", "credential": "one" },
  "server": {
    "protocolVersion": "2025-11-25",
    "instructions": "What this server is for.",
    "serverInfo": { "name": "example-mcp", "version": "1.0.0" },
    "capabilities": { "tools": { "listChanged": false } }
  },
  "tools": [
    {
      "name": "summary_report",
      "description": "A structured summary that renders as a typed part.",
      "outputSchema": { "type": "object", "properties": {} },
      "annotations": { "readOnlyHint": true, "openWorldHint": false },
      "_meta": {
        "org.veupathdb.assistant/streamPart": {
          "kind": "data-example.summary",
          "version": 1
        }
      }
    }
  ],
  "families": [
    {
      "id": "shape",
      "number": 1,
      "title": "Shape",
      "passed": 9,
      "failed": 0,
      "skipped": 0,
      "checks": [
        {
          "id": "test_shape.py::test_tool_names_are_unique",
          "outcome": "passed",
          "message": null
        }
      ]
    }
  ]
}
```

A tool row carries what the server declared and nothing the SDK filled in, so an
absent annotation is absent here too. The one field left out is `inputSchema`:
what a tool returns is what an operator signs for, and what it takes is the
server's own document.

`verdict` is `pass` only when every family ran and every check passed. A family
that could not run leaves the verdict `incomplete`: a skipped check is not a
passed one, and an admission record must not read as though it were.

## Developing the suite

```
uv run ruff check src tests
uv run mypy --strict src
uv run pytest
```

The suite's own tests run each family against fixture MCP servers this package
ships: one compliant, and one per planted defect. A family that cannot fail is
not a gate, so every family has a defect that it, and only it, catches.
