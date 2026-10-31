"""
app/models.py
--------------------------------------------------------------------------
Pydantic models for the HTTP API's request and response bodies. FastAPI
uses these two things automatically:
  1. To validate incoming JSON (a request missing a required field, or
     with the wrong type, is rejected with a clear 422 error before any
     of our own code runs).
  2. To generate the interactive API docs at /docs.

These mirror the brief's "Structured API responses" section almost
field-for-field: answer, data, evidence[], proposed_actions, warnings,
request_id.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="A plain-English business question.")


class EvidenceEntry(BaseModel):
    tool: str
    arguments: dict[str, Any]
    status: str
    duration_ms: int
    result_id: str


class ChatResponse(BaseModel):
    answer: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceEntry] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    request_id: str


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")


class ToolRunOut(BaseModel):
    run_id: str
    request_id: str
    tool_name: str
    arguments: Any
    result_summary: Any
    status: str
    duration_ms: int
    started_at: str
