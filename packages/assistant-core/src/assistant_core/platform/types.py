from enum import StrEnum
from typing import Literal

from pydantic import JsonValue

type JSONObject = dict[str, JsonValue]
type JSONArray = list[JsonValue]

type ModelProvider = Literal["openai", "anthropic", "google", "ollama", "mock"]
type ReasoningEffort = Literal["none", "low", "medium", "high"]
TierName = Literal["default", "quality", "balanced", "fast", "custom"]


class PaidBy(StrEnum):
    """Whose provider key a usage row was spent on. The cap counts the deployment's."""

    DEPLOYMENT = "deployment"
    USER = "user"
