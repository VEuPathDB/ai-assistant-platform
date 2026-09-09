---
type: Decision
title: Input screening is configured by the host, not by the environment
description: The screening scanner takes its model directory as a constructor argument, raises a plain ScreeningRejectionError, and pulls the ONNX runtime through the optional `screening` extra, so a host owns the path, the HTTP answer and the download.
tags: [assistant-core, capabilities, security, packaging]
generated: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
verified: { by: claude-code/opus-5, at: 2026-09-08T00:00:00Z }
status: stable
---

# What was decided

`assistant_core.capabilities.piguard` holds the two text scanners and
`assistant_core.capabilities.input_screening` holds the turn's trust boundary.
Three things about them are the host's, not the runtime's.

**The model directory is a constructor argument.** `PIGuardScanner(model_dir)`
and `UserInputScanner(model_dir=...)` are told where `model.onnx` and
`tokenizer.json` are. The runtime reads no environment variable for it, so a
deployment that keeps the model somewhere else needs no runtime change, and two
assistants in one process can screen against two models.

**The rejection is a plain exception.** `ScreeningRejectionError(RuntimeError)`
carries the scanner name and the risk score and nothing else. The runtime serves
no HTTP, so it does not know what status, title or wording a refusal should
carry; the host catches the error at its own entry point and answers in its own
error shape. The message the exception carries names the scanner and the risk
score, which is diagnostic text: a host writes its own sentence for the person
who sent the message, and never renders `str(exc)`.

**The ONNX runtime is an optional extra.** A consumer that screens input
declares `assistant-core[screening]`, which adds `onnxruntime` and `tokenizers`.
An assistant that screens nothing carries neither. The package's own dev group
names the extra, because the boundary suite imports every module. A host that
forgets the extra learns it at import: `assistant_core.capabilities.piguard`
raises `ModuleNotFoundError` naming `assistant-core[screening]`, from the
missing package.

# What was rejected

**Reading `PIGUARD_MODEL_DIR` from the environment**, which is what the code did
in the application it came from. It is fewer lines at the one call site that
exists today, and it was rejected because a library that reads the environment
decides a deployment's layout: the value cannot be overridden per assistant, it
does not appear in the host's settings model, and it is invisible to the host's
own configuration gate.

**Keeping an HTTP-shaped error class.** The scanner used to raise an error
carrying a status of 403, a title and a user-facing sentence. It was rejected
because those three values are a wire contract of the application that serves
the turn, and a second host would inherit a refusal worded for the first.

**Making `onnxruntime` a required dependency.** One line simpler, and rejected
because it puts a hundred megabytes and a native wheel in front of every
assistant, including the ones that never screen a message.

# Anchor

`packages/assistant-core/tests/unit/capabilities/test_input_screening.py`: the
two scanners, the approval bypass, the rejection carrying scanner and score, the
offload to a thread, and the scanners being built once.
`.../tests/unit/capabilities/test_piguard_import.py`: an absent screening
package names the extra.
`.../tests/packaging/test_wheel_declares_the_screening_extra.py`: the wheel
offers the extra, and the base dependencies carry neither package.
