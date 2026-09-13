---
type: Decision
title: Input screening is configured by the host, and an injection is defined by the runtime
description: A model judges the text against the runtime's definition of a prompt injection, the host supplies the model and a paragraph of product context, and the refusal stays a plain ScreeningRejectionError. A local classifier, a phrase whitelist and an environment-read model path were all rejected.
tags: [assistant-core, capabilities, security, packaging]
generated: { by: claude-code/opus-5, at: 2026-09-13T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-13T00:00:00Z }
status: stable
---

# What was decided

`assistant_core.capabilities.injection_judge` holds the definition of a prompt
injection and the model call that applies it,
`capabilities.invisible_text` the Unicode scan,
`capabilities.input_screening` the turn's trust boundary, and
`capabilities.tool_result_screen` the same judgement over a tool source's
result. Three things about them are the host's, and one is not.

**The judge is a model the host names.** `ModelInjectionJudge(model, context)`
takes any pydantic-ai model or model string and a paragraph that says what
normal messages look like in that product. The runtime resolves the string with
`infer_model` and runs an agent with no tools and no history over one text of
at most `MAX_JUDGED_CHARS`. Two assistants in one process judge against two
contexts, and a deployment that changes model changes an argument.

**The runtime bounds the call and the host bounds the policy.** The judge runs
with `timeout_seconds`, 20 seconds by default, on its model settings, because
the screen sits on the request path in front of the user's own message: a
provider that stops answering must fail the turn in seconds, not hold a
connection for the provider's own default. The error that arrives propagates
like any other model error, and what a failed judgement means to a turn stays
the host's decision. A host that wants another bound passes another number; a
host that passes a model string still gets one.

**The definition of an injection is the runtime's.** `JUDGE_INSTRUCTIONS`
names the six shapes: overriding the assistant's instructions, impersonating
the system or an operator or the vendor, extracting a secret or a hidden
prompt, disabling an approval or a safety rule, redirecting output to a third
party, and inducing an unbounded loop or spend. Everything else passes,
including a blunt or destructive request about the product's own work. A host
that could write that list would write a different one per deployment, and a
screener that varies per deployment is not a boundary.

**The rejection is a plain exception.** `ScreeningRejectionError(RuntimeError)`
carries the scanner name and the risk score and nothing else, where the score
is the judge's own confidence. The runtime serves no HTTP, so it does not know
what status, title or wording a refusal should carry; the host catches the
error at its own entry point and answers in its own error shape. The message
the exception carries is diagnostic text: a host writes its own sentence for
the person who sent the message, and never renders `str(exc)`.

**A judged tool result is replaced, not dropped, and it is read whole.**
`tool_result_screen.screened_output(judge)` answers the `OutputScan` the MCP
wrapper takes, and a result the judge calls an injection reaches the model as
one fixed sentence saying a result carried instructions and was not passed on.
The user's message is one judgement of at most `MAX_JUDGED_CHARS`, because a
message that long is not a message; a tool result is not, so the screen cuts it
into windows of `MAX_JUDGED_CHARS`, judges them together, and calls the result
an injection when any window is one, at the highest confidence any injected
window carried. `MAX_JUDGED_WINDOWS` bounds how many windows one result may
cost, and a result longer than that product is withheld unjudged: a boundary
that cannot read a text does not pass it. Verdicts are cached by the digest of
the whole text, bounded, because one turn reads the same result more than
once.

# What was rejected

**A local classifier.** The package shipped a DeBERTa-v3 ONNX model behind a
`screening` extra, and it was rejected on the numbers. Over the 88 labelled
messages of `packages/assistant-core/tests/fixtures/injection_corpus.jsonl`, at
its 0.90 threshold, it refused 8 of the 73 benign messages, missed 2 of the 15
injections, and spent 1.6 s of CPU per message. The three worst refusals were
ordinary product sentences that ask to remove or stop something. Meta's Prompt
Guard 2, both sizes, refused 2 to 3 and missed 10 to 14 of the same corpus. The
judge refused none and missed none, at $0.00006 and 1.15 s per message. A
hundred-megabyte wheel, a native runtime and an extra were the price of the
worse result.

**A phrase whitelist in front of the classifier.** The boundary carried a
regular expression that let "yes", "ok" and "approved" past the model, because
the classifier scored short affirmatives above its threshold. It is deleted:
it existed to work around one classifier, it was a documented hole in the
boundary for any text short enough to match, and the judge scores those
sentences as benign on their own.

**Reading a model path from the environment.** A library that reads the
environment decides a deployment's layout: the value cannot be overridden per
assistant, it does not appear in the host's settings model, and it is invisible
to the host's own configuration gate.

**Keeping an HTTP-shaped error class.** The scanner used to raise an error
carrying a status of 403, a title and a user-facing sentence. Those three
values are a wire contract of the application that serves the turn, and a
second host would inherit a refusal worded for the first.

# Anchor

`packages/assistant-core/tests/unit/capabilities/test_injection_judge.py`: the
verdict a model answers, the clip, the instructions, and the run that carries
no tools and no history.
`.../test_input_screening.py`: the Unicode scan running first, and the refusal
carrying the scanner name and the judge's confidence.
`.../test_tool_result_screen.py`: the withheld sentence, the untouched benign
result, the second read answered from the cache, an injection in the second
window of a long result, and a result past the window cap withheld with no
model call.
`.../tests/unit/mcp/test_untrusted_output.py`: the screen installed on a
toolset, where a withheld result reaches the model as the sentence and binds no
part.
`.../tests/unit/capabilities/test_injection_corpus.py`: the corpus keeps its 88
lines, 73 benign and 15 injections.
`.../tests/live/test_live_injection_judge.py`: the whole corpus against a real
model, opt-in, asserting no false positive and no miss.
