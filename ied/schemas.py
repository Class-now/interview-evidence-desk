"""Data shapes shared by every stage. Every LLM output is validated against one of these."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Kind = Literal["pain", "workaround", "willingness_to_pay", "counter"]
Strength = Literal["said", "did", "paid"]
Decision = Literal["accept", "reject", "doubt"]

STRENGTH_WEIGHT = {"said": 1, "did": 2, "paid": 3}


class Hypothesis(BaseModel):
    id: str
    statement: str


class Interview(BaseModel):
    id: str
    title: str
    lines: list[str]

    def numbered(self) -> str:
        return "\n".join(f"{i + 1}: {t}" for i, t in enumerate(self.lines))


class EvidenceDraft(BaseModel):
    """What the model is asked to return for one interview."""
    hypothesis_id: str
    kind: Kind
    strength: Strength
    supports: bool = Field(description="true if the quote supports the hypothesis, false if it weakens it")
    quote: str
    line: int

    @field_validator("quote")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip().strip('"').strip()
        if len(v) < 8:
            raise ValueError("quote too short")
        return v


class ExtractResult(BaseModel):
    evidence: list[EvidenceDraft]


class Evidence(EvidenceDraft):
    interview_id: str
    verified: bool = False
    verify_note: str = ""
    judge_reason: str = ""


class Judgement(BaseModel):
    """Second, narrower look at one verified quote (small models judge stance far better one quote at a time)."""
    reasoning: str = Field(description="one sentence: what the speaker means, in context of the question asked")
    stance: Literal["for", "against", "irrelevant"]
    strength: Strength


class Challenge(BaseModel):
    devils_advocate: str = Field(description="the strongest reading against the current majority view")
    would_change_mind: str = Field(description="one concrete observation that would flip the conclusion")


class HypothesisSummary(BaseModel):
    hypothesis: Hypothesis
    supporting: list[Evidence]
    weakening: list[Evidence]
    score_for: int
    score_against: int
    interviews_covered: int
    challenge: Optional[Challenge] = None

    @property
    def lean(self) -> str:
        if self.score_for == 0 and self.score_against == 0:
            return "no evidence"
        if self.score_for >= 2 * max(self.score_against, 1):
            return "supported"
        if self.score_against >= 2 * max(self.score_for, 1):
            return "contradicted"
        return "mixed"


class HumanDecision(BaseModel):
    hypothesis_id: str
    decision: Decision
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_required(cls, v: str) -> str:
        if len(v.strip()) < 3:
            raise ValueError("a short reason is required for every decision")
        return v.strip()


class NextQuestions(BaseModel):
    questions: list[str]
