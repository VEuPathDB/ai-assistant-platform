import captured from "./captured.json" with { type: "json" };

/** The wire protocol version this client is built from. */
export const PROTOCOL_VERSION: string = captured.version;
