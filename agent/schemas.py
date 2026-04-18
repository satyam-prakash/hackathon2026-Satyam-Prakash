from pydantic import BaseModel, Field
from typing import Literal, Dict, Any, List

class ToolCall(BaseModel):
    thought: str = Field(..., description="Step-by-step reasoning")
    action: str = Field(..., description="Name of the tool to call")
    action_input: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this tool decision")

class FinalResolution(BaseModel):
    ticket_id: str
    decision: Literal["refund", "reply", "cancel", "escalate"]
    reasoning: List[str]
    tool_calls: List[str]
    final_action: str
    confidence: float = Field(..., ge=0.0, le=1.0)
