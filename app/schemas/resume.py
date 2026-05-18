from dataclasses import dataclass

from pydantic import BaseModel, Field


class JobEntry(BaseModel):
    title: str
    company: str
    location: str
    dates: str
    bullets: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str
    dates: str
    bullets: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str
    school: str
    location: str
    dates: str


class ResumeStructure(BaseModel):
    name: str = ""
    contact: str = ""
    summary: str = ""
    jobs: list[JobEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)


class RewrittenResume(BaseModel):
    summary: str = ""
    jobs: list[JobEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


@dataclass
class RewriteResult:
    markdown: str
    docx_bytes: bytes
    gaps: list[str]


class RewriteError(RuntimeError):
    def __init__(self, message: str, raw_output: object | None = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output
