/**
 * Deprecated since protocol 1.1.0. The thread now carries a durable task's
 * whole lifecycle, in its durable-task section, so the core ring reads everything
 * this ring reads. Import it only to follow a task at the worker's own rate;
 * PROTOCOL.md section 13 specifies the dialect.
 */
export { readTypedEvents } from "./legacy/typedEventFrames.ts";
