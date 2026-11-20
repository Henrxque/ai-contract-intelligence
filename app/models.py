from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=4000)


class ExtractedField(StrictModel):
    value: str | None
    evidence: list[Evidence] = Field(max_length=12)
    uncertain: bool
    reason: str | None


class ContractFields(StrictModel):
    party_a: ExtractedField
    party_b: ExtractedField
    effective_date: ExtractedField
    end_date: ExtractedField
    total_value: ExtractedField
    currency: ExtractedField
    payment_terms: ExtractedField
    governing_law: ExtractedField
    termination: ExtractedField
    confidentiality: ExtractedField
    liability: ExtractedField


class Extraction(StrictModel):
    fields: ContractFields


class SourcePage(StrictModel):
    number: int
    text: str


class ReviewField(StrictModel):
    key: str
    label: str
    group: str
    required: bool
    value: str | None
    evidence: list[Evidence]
    status: Literal["supported", "missing", "uncertain", "invalid"]
    issues: list[str]


class Finding(StrictModel):
    field: str
    severity: Literal["error", "warning", "info"]
    code: str
    message: str


class TokenUsage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)


class AnalysisResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    document_id: str
    filename: str
    page_count: int
    mode: Literal["local", "openai"]
    provider_model: str | None
    sample: bool
    analyzed_at: str
    elapsed_ms: int
    status: Literal["checks_passed", "needs_review"]
    fields: list[ReviewField] = Field(max_length=30)
    findings: list[Finding] = Field(max_length=100)
    pages: list[SourcePage] = Field(max_length=40)
    notices: list[str]
    token_usage: TokenUsage | None = None


# These are extraction-policy requirements, not legal requirements.
FIELD_SPECS = {
    "party_a": ("Service provider", "Parties", True),
    "party_b": ("Client", "Parties", True),
    "effective_date": ("Effective date", "Dates & value", True),
    "end_date": ("End date", "Dates & value", True),
    "total_value": ("Contract value", "Dates & value", True),
    "currency": ("Currency", "Dates & value", True),
    "payment_terms": ("Payment terms", "Terms & clauses", True),
    "governing_law": ("Governing law", "Terms & clauses", False),
    "termination": ("Termination", "Terms & clauses", False),
    "confidentiality": ("Confidentiality", "Terms & clauses", False),
    "liability": ("Liability", "Terms & clauses", False),
}
