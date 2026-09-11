---
type: Decision
title: The tool-hint namespace is a value, and its default names this organisation
description: A tool server declares a typed part under <namespace>/streamPart. The namespace is org.veupathdb.assistant by default, a host installs its own and a conformance run names its own. Hard-coding the key in two distributions was rejected, and so was parsing it from the environment in the runtime.
tags: [assistant-core, mcp-conformance, mcp, naming]
generated: { by: claude-code/opus-5, at: 2026-09-11T00:00:00Z }
status: stable
---

# What was decided

The reverse-DNS namespace a tool server declares its runtime hints under is a
value. `assistant_core.mcp.untrusted.DEFAULT_MCP_META_NAMESPACE` is
`org.veupathdb.assistant`, `install_mcp_meta_namespace(namespace)` names
another one for a process, and `stream_part_meta_key()` is the key the wrapper
reads a declaration under. A deployment that names its own namespace reads
`<namespace>/streamPart` and nothing else, so a server annotated for that
deployment gets its typed part.

The conformance suite takes the namespace from the runner, as
`--mcp-meta-namespace` with the `MCP_CONFORMANCE_META_NAMESPACE` fallback the
other options have. `mcp_conformance._options.DEFAULT_META_NAMESPACE` is the
same default, and `stream_part_meta_key(namespace)` and
`max_call_seconds_meta_key(namespace)` build the two keys from the namespace
the run states. The two distributions may not depend on each other, so the
default is written twice and the copies name one namespace.

A run reads the hints under the namespace it was told, so a server annotated
for its own deployment is reported on what it declared. A run that names
nothing reads the default, and a server annotated under some third namespace is
read as a server that declares none, which is a shape the suite already
allows.

# Why

Reverse-DNS `_meta` namespacing is ordinary MCP practice, so the shape was
never the problem: the owner was. A third-party server had to annotate its
public tool definitions with a key naming an organisation it has no
relationship with, and a server serving two deployments carried one
deployment's vendor key for both. A default keeps every server that works today
working, and the override is what makes a second organisation's runtime its
own.

The namespace is installed, not read from the environment, for the reason
[admission is](admitted-tool-sources-are-installed-by-the-host.md): what a
deployment admits and how it reads a server's hints are composition, and a
process that parses them from its environment has two sources of truth for one
question.

# What was rejected

**Leaving the key a literal in both distributions.** Rejected: it is the
requirement that a foreign vendor key appear in a third party's tool
definitions, with no way out but a fork.

**A setting parsed from the environment.** Rejected: the admitted set beside it
is installed, and one of the two being configuration would split how a
deployment describes its tool servers.

**Leaving the suite on its own constant.** Rejected: a deployment that runs
its own runtime annotates its servers under its own namespace, and a suite that
reads only the default reports those servers as declaring no typed part and no
budget. The run is the place that knows which namespace the servers under test
were annotated for, so the runner states it.
