# Log

## 2026-09-08

Input screening arrived: `assistant_core/capabilities/piguard.py` and
`assistant_core/capabilities/input_screening.py`, with the model directory as a
constructor argument, `ScreeningRejectionError` in place of an HTTP-shaped
error, and the ONNX runtime behind the `screening` extra. `setup_logging` now
assigns its handler onto the root logger, so a second call leaves one handler.
Two decisions are new: input screening is configured by the host; the process
logging setup is written once per served distribution.


Bundle created. The runtime, protocol, client and conformance decisions that had
been living in the consuming application's bundle moved here, and their
`verified` stamps were refreshed against the code as it stands today. Three
decisions are new: `site_id`, `mode` and `phase` are core request fields;
the runtime's stored defaults name no product; the settings-source scaffold is
written once per distribution.

`conventions/verification-gates.md` carries the three package gate sets, which
had been three sections of the consuming application's own gates page.

PROTOCOL 1.7.1: the product-extension table of section 12.2 is empty and the
request examples carry a neutral site, mode and tool name.
