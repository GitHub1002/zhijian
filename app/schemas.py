"""HTTP 请求模型。"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=128)


class AskRequest(BaseModel):
    question: str
    conversation_id: Optional[int] = None


class FeedbackSourceMark(BaseModel):
    source_index: int = Field(ge=1, le=50)
    mark: Literal["wrong_citation", "irrelevant", "outdated", "missing_context"]


class FeedbackRequest(BaseModel):
    answer_id: int
    sentiment: Literal["positive", "negative"]
    reasons: list[str] = Field(default_factory=list)
    comment: str = Field(default="", max_length=2000)
    corrected_answer: str = Field(default="", max_length=4000)
    source_marks: list[FeedbackSourceMark] = Field(default_factory=list, max_length=20)
    client_version: str = Field(default="", max_length=40)


class FeedbackUpdateRequest(BaseModel):
    sentiment: Optional[Literal["positive", "negative"]] = None
    reasons: Optional[list[str]] = None
    comment: Optional[str] = Field(default=None, max_length=2000)
    corrected_answer: Optional[str] = Field(default=None, max_length=4000)
    source_marks: Optional[list[FeedbackSourceMark]] = None


class FeedbackTriageRequest(BaseModel):
    status: Literal["new", "triaged", "in_progress", "resolved", "dismissed"]
    category: str
    note: str = Field(default="", max_length=2000)


class SourceClickRequest(BaseModel):
    answer_id: int
    source: str = Field(default="", max_length=300)
    heading: str = Field(default="", max_length=300)
    anchor: str = Field(default="", max_length=300)
    library: str = Field(default="", max_length=40)
    source_index: int = Field(default=0, ge=0, le=50)


class ContentTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    source: str = Field(default="", max_length=300)
    heading: str = Field(default="", max_length=300)
    library: str = Field(default="", max_length=40)
    kind: str = "doc_fix"
    priority: str = "medium"
    owner_id: Optional[int] = None
    eval_run_id: Optional[int] = None


class ContentTaskUpdateRequest(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "dismissed"]] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    kind: Optional[str] = None
    owner_id: Optional[int] = None
    eval_run_id: Optional[int] = None
    resolution_note: Optional[str] = Field(default=None, max_length=2000)


class ContentTaskFromFeedbackRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    source: Optional[str] = Field(default=None, max_length=300)
    heading: Optional[str] = Field(default=None, max_length=300)
    library: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = None
    priority: Optional[str] = None


class CuratedExampleUpdateRequest(BaseModel):
    status: Optional[Literal["candidate", "approved", "rejected"]] = None
    use_as_few_shot: Optional[bool] = None
    eval_passed: Optional[bool] = None
    eval_run_id: Optional[int] = None


class ExperimentVariantRequest(BaseModel):
    variant_key: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=80)
    config: dict = Field(default_factory=dict)
    traffic_pct: int = Field(default=0, ge=0, le=100)
    is_control: bool = False


class ExperimentRequest(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    variants: list[ExperimentVariantRequest] = Field(min_length=1, max_length=10)
    guardrails: dict = Field(default_factory=dict)


class ExperimentUpdateRequest(BaseModel):
    status: Optional[Literal["draft", "running", "paused", "ended"]] = None
    variants: Optional[list[ExperimentVariantRequest]] = None
    guardrails: Optional[dict] = None


class DocRequest(BaseModel):
    path: str
    content: str


class ContentRequest(BaseModel):
    content: str


class SyncRequest(BaseModel):
    source_dir: str


class PermissionReviewRequest(BaseModel):
    status: str


class ProfileRequest(BaseModel):
    display_name: Optional[str] = None
    avatar: Optional[str] = None
