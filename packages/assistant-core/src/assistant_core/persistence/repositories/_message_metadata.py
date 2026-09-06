from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    total_tokens: int = Field(0, alias="totalTokens")
    cost_usd: str = Field("0", alias="costUsd")

    @field_validator("cost_usd", mode="before")
    @classmethod
    def _coerce_cost(cls, value: object) -> str:
        if value is None:
            return "0"
        return str(value)

    def cost_decimal(self) -> Decimal:
        try:
            return Decimal(self.cost_usd)
        except InvalidOperation:
            return Decimal(0)


class MessageMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    trace_id: str | None = Field(None, alias="traceId")
    created_at: str | None = Field(None, alias="createdAt")
    site_id: str | None = Field(None, alias="siteId")
    mode: str | None = None
    usage: MessageUsage | None = None
    turn_completed: bool | None = Field(None, alias="turnCompleted")
