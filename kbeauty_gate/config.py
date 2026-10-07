"""환경 설정. 외부 패키지 없이 .env를 읽는다 (OpenShell 샌드박스에서 pip 없이 실행 가능하도록)."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    nvidia_api_key: str
    chat_url: str
    chat_models: List[str]
    embed_url: str
    embed_model: str
    timeout: int
    last_chat_model: str = field(default="")

    @property
    def online(self) -> bool:
        return bool(self.nvidia_api_key)

    @property
    def chat_model(self) -> str:
        return self.last_chat_model or self.chat_models[0]


def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    primary = os.environ.get("NEMOTRON_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    fallback = os.environ.get("NEMOTRON_FALLBACK_MODELS", "nvidia/nemotron-3-super-120b-a12b")
    models = [primary] + [m.strip() for m in fallback.split(",") if m.strip() and m.strip() != primary]
    return Settings(
        nvidia_api_key=os.environ.get("NVIDIA_API_KEY", ""),
        chat_url=os.environ.get("NVIDIA_CHAT_URL", "https://integrate.api.nvidia.com/v1/chat/completions"),
        chat_models=models,
        embed_url=os.environ.get("NVIDIA_EMBED_URL", "https://integrate.api.nvidia.com/v1/embeddings"),
        embed_model=os.environ.get("EMBED_MODEL", "nvidia/nemotron-3-embed-1b"),
        timeout=int(os.environ.get("NVIDIA_TIMEOUT", "90")),
    )
