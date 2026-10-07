"""환경 설정. 외부 패키지 없이 .env를 읽는다 (OpenShell 샌드박스에서 pip 없이 실행 가능하도록)."""
import os
from dataclasses import dataclass
from pathlib import Path


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
    chat_model: str
    rerank_url: str
    rerank_model: str
    timeout: int

    @property
    def online(self) -> bool:
        return bool(self.nvidia_api_key)


def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    return Settings(
        nvidia_api_key=os.environ.get("NVIDIA_API_KEY", ""),
        chat_url=os.environ.get("NVIDIA_CHAT_URL", "https://integrate.api.nvidia.com/v1/chat/completions"),
        chat_model=os.environ.get("NEMOTRON_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
        rerank_url=os.environ.get(
            "NVIDIA_RERANK_URL",
            "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-1b-v2/reranking",
        ),
        rerank_model=os.environ.get("RERANK_MODEL", "nvidia/llama-nemotron-rerank-1b-v2"),
        timeout=int(os.environ.get("NVIDIA_TIMEOUT", "60")),
    )
