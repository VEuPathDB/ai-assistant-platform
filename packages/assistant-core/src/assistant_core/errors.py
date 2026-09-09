"""The errors this runtime raises for a host to map onto its own transport."""

from uuid import UUID


class AssistantCoreError(Exception):
    """Base of every error the runtime raises across its public surface."""


class ConversationNotFoundError(AssistantCoreError):
    """No conversation with this id is visible to the caller."""

    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(f"conversation {conversation_id} not found")
        self.conversation_id = conversation_id


class ConversationForbiddenError(AssistantCoreError):
    """The conversation belongs to another user or another application."""

    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(f"conversation {conversation_id} belongs to another caller")
        self.conversation_id = conversation_id


class TurnStillRunningError(AssistantCoreError):
    """The worker did not close the thread's turn inside the stop window."""

    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(
            f"conversation {conversation_id} has a turn in flight; stop it first"
        )
        self.conversation_id = conversation_id
