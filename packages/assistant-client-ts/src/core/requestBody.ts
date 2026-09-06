export interface TurnRequestBodyArgs<MESSAGE> {
  conversationId: string;
  id: string;
  trigger: string;
  messages: readonly MESSAGE[];
  baseBody?: Record<string, unknown> | undefined;
  extra?: Record<string, unknown> | undefined;
}

export interface TurnRequestBody<MESSAGE> {
  conversationId: string;
  id: string;
  trigger: string;
  messages: readonly MESSAGE[];
  [field: string]: unknown;
}

function isEmptyMap(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.keys(value).length === 0
  );
}

function statedFields(extra: Record<string, unknown>): Record<string, unknown> {
  const stated: Record<string, unknown> = {};
  for (const [field, value] of Object.entries(extra)) {
    if (value === undefined || isEmptyMap(value)) continue;
    stated[field] = value;
  }
  return stated;
}

/** Build the body that opens a turn. A field with nothing to say is omitted. */
export function buildTurnRequestBody<MESSAGE>(
  args: TurnRequestBodyArgs<MESSAGE>,
): TurnRequestBody<MESSAGE> {
  return {
    ...args.baseBody,
    ...statedFields(args.extra ?? {}),
    conversationId: args.conversationId,
    id: args.id,
    trigger: args.trigger,
    messages: args.messages,
  };
}
