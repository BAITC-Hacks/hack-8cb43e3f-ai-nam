from dataclasses import asdict, dataclass, field


@dataclass
class Clause:
    id: str
    doc_id: str
    number: str
    text: str
    location: str
    section: str = ""
    actor: str = ""
    actor_source: str = ""
    context: str = ""
    parent_id: str = ""
    kind: str = "other"
    modality: str = "statement"

    def to_dict(self):
        return asdict(self)


@dataclass
class Document:
    id: str
    name: str
    side: str
    format: str
    size: int
    digest: str
    clauses: list[Clause] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self):
        return asdict(self)
