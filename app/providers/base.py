from dataclasses import dataclass, field
from pathlib import Path


class ProviderError(Exception):
    pass


class SafetyRejected(ProviderError):
    """Dostawca odrzucil tresc. Program NIE ponawia z innym ustawieniem filtra."""


@dataclass
class GenRequest:
    kind: str                       # image | edit | video
    prompt: str
    fmt: str = "16:9"
    model: str | None = None
    refs: list[Path] = field(default_factory=list)
    source_image: Path | None = None
    end_image: Path | None = None   # ostatnia klatka klipu (MiniMax H3 first/last frame)
    duration: int = 5
    voice: dict = field(default_factory=dict)   # mowa: {mode: voice|clone|design, voice, description, ref_path, transcript, language}
    idem_key: str = ""
    safe_filter: bool = True
    resume_id: str | None = None
    billing_mode: str | None = None   # per zadanie: "tokens" dla modelu poza planem; None = z konfiguracji


@dataclass
class GenResult:
    files: list[tuple[bytes, str]]  # (bajty, rozszerzenie)
    remote_id: str | None = None
    meta: dict = field(default_factory=dict)


class Provider:
    name = "base"

    def generate(self, req: GenRequest, on_remote_id=None) -> GenResult:
        raise NotImplementedError

    def estimate(self, req: GenRequest) -> dict:
        return {"supported": False}
