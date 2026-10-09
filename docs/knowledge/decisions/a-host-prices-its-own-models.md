---
type: Decision
title: A host prices its own models, and a run costs the sum of its requests
description: assistant_core.pricing.install_model_prices puts a host's prices for named models ahead of the packaged genai-prices snapshot, as a custom snapshot that every price reader of the process reads, and cost_for_run returns the per-request cost sum pydantic-ai accumulates before it prices summed tokens. The Claude provider lays the measured request surface of the Claude 5.5 models over the packaged pydantic-ai profile. Waiting for a snapshot release, a price argument on cost_for_run, and pricing a run from its summed tokens were rejected.
tags: [assistant-core, pricing, quota, models]
generated: { by: claude-code/opus-5-5, at: 2026-10-08T00:00:00Z }
verified: { by: claude-code/opus-5-5, at: 2026-10-08T00:00:00Z }
status: stable
---

# What was decided

**A host's prices come first.** `assistant_core.pricing.install_model_prices`
takes `HostModelPrice` rows (a provider, a model id, a `TokenPrices` of input,
cache read, cache write and output per 1M tokens, and an optional `LongPrompt`
that every token of a request pays once its prompt passes `above_tokens`). It
builds a `genai_prices` custom snapshot from the packaged providers with each
host model placed first in its provider, matched by its exact id, and installs
it with `genai_prices.data_snapshot.set_custom_snapshot`. A later install
replaces an earlier one, `reset_model_prices` restores the packaged snapshot,
and a provider the snapshot does not name is refused with `LookupError`. Every
price reader of the process reads the result: `cost_for_run`,
`lookup_per_mtok_prices`, and the cost pydantic-ai fills on each
`ModelResponse`. A host that installs nothing is priced by the packaged
snapshot alone.

**A run costs the sum of its requests.** pydantic-ai prices each response when
it joins the history and adds the cost to the run's `RunUsage.cost`.
`cost_for_run` returns that sum when it is set, and prices the summed tokens
only for a usage that carries no cost. A long-prompt price is decided by one
request's prompt, so only the per-request sum is right for it.

**The measured Claude request surface.** The packaged pydantic-ai profile (2.41)
sends `claude-haiku-5-5` a token-budget thinking setting, which the API answers
with a 400 at every effort, and forces a tool on `claude-sonnet-5-5` and
`claude-opus-5-5`, which they answer with a 400. `assistant_core.models.claude_profiles`
lays what each model answered over the packaged profile: Haiku 5.5 thinks
adaptively at an effort (up to `xhigh`), takes no budget and no sampling
settings, and takes a JSON schema output; Sonnet 5.5 and Opus 5.5 are never
forced to a tool. `ClaudeProvider` is an `AnthropicProvider` whose models carry
that profile; a host builds its Anthropic models on it.

# What was rejected

- **Waiting for a snapshot release.** `genai-prices` 0.1.9, the latest, has no
  `claude-haiku-5-5`, so a run on it costs nothing, and it prices
  `claude-sonnet-5-5` as Sonnet 5, whose cache read costs twice as much.
- **A price argument on `cost_for_run`.** The stock single-agent graph and the
  compactor call it with no host in reach, and pydantic-ai's own per-response
  cost would still read the snapshot.
- **Pricing a run from its summed tokens.** A run of several requests passes a
  long-prompt threshold before any one prompt does.

# Anchor

`tests/unit/quota/test_host_prices.py` (a model the snapshot lacks is priced
from the host table, a registered price wins over the snapshot, a prompt over
the threshold pays the long prices, a response is priced from the host table, a
reset and a second install, an unknown provider refused);
`tests/unit/quota/test_cost_for_run.py`; `tests/unit/models/test_claude_profiles.py`.
