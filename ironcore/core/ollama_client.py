import urllib.request
import json
from pydantic import BaseModel
from typing import List, Generator

class OllamaError(Exception):
    pass

class OllamaModel(BaseModel):
    name: str

class OllamaClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 11434):
        self.base_url = f"http://{host}:{port}"
        
    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def list_models(self) -> List[OllamaModel]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=5) as r:
                data = json.loads(r.read().decode())
                return [OllamaModel(name=m["name"]) for m in data.get("models", [])]
        except Exception as e:
            raise OllamaError(f"Failed to fetch models from Ollama: {e}")

    def resolve_model(self, requested: str | None) -> str:
        if not requested:
            raise OllamaError("No model requested.")
        models = self.list_models()
        if not any(m.name == requested for m in models):
            raise OllamaError(f"Model '{requested}' not found in local Ollama.")
        return requested

    def chat(self, model: str, messages: list[dict], stream: bool = True) -> Generator[str, None, None]:
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps({"model": model, "messages": messages, "stream": stream}).encode(),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as r:
                for line in r:
                    if line:
                        chunk = json.loads(line)
                        yield chunk.get("message", {}).get("content", "")
        except Exception as e:
            raise OllamaError(f"Ollama chat error: {e}")
