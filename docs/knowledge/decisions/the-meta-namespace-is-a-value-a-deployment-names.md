---
type: Decision
title: The tool-hint namespace is a value, and its default names this organisation
description: A tool server declares a typed part under <namespace>/streamPart. The namespace is org.veupathdb.assistant by default and a host installs its own. Hard-coding the key in two distributions was rejected, and so was parsing it from the environment.
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

The conformance suite carries the same namespace as its own constant,
`mcp_conformance._evidence.MCP_META_NAMESPACE`, and builds
`STREAM_PART_META_KEY` and `MAX_CALL_SECONDS_META_KEY` from it. The two
distributions may not depend on each other, so the namespace is written twice
and the copies name one default.

The consequence is written down rather than removed: a suite run reads the
suite's namespace, so a server that declares its hints under another one is
read as a server that declares none, which is a shape the suite already
allows. What such a deployment learns from a run is that its servers declare no
typed part and no budget, not that they declared one wrongly.

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

**A second override on the conformance suite.** Rejected while nothing reads
it: the suite's checks on a declaration are checks on a server that made one,
and a server that declares under another namespace is already answered as one
that declared nothing. An option would have to change what the suite reports,
not only which key it reads.
