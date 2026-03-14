"""
ModelFactory — abstracción multi-LLM con fallback automático.

Uso:
    factory = ModelFactory()
    model = factory.get()           # usa AI_MODEL de config
    model = factory.get("groq")     # fuerza un tipo específico
    response = model.ask(system, user)
"""
from __future__ import annotations
import sys
from dataclasses import dataclass
from typing import Optional
import moondev.config as cfg


@dataclass
class ModelResponse:
    content: str
    model_used: str
    input_tokens: int = 0
    output_tokens: int = 0


class BaseModel:
    def ask(self, system: str, user: str, temperature: float = 0.7,
            max_tokens: int = 4096) -> ModelResponse:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError


# Opus 4.5 effort beta (effort-2025-11-24); use with claude-opus-4-5-20251101
_OPUS_45_MODEL = "claude-opus-4-5-20251101"


class ClaudeModel(BaseModel):
    def __init__(self, model_name: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY or None)
        self._model = model_name

    def ask(self, system, user, temperature=0.7, max_tokens=4096) -> ModelResponse:
        # Anthropic requires non-empty user content; if empty, merge into user
        if not user or not user.strip():
            user = system
            system = "You are an expert quantitative trading strategy developer."
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        msg = self._client.messages.create(**kwargs)
        content = msg.content[0].text
        return ModelResponse(
            content=content,
            model_used=self._model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )

    @property
    def name(self):
        return f"claude/{self._model}"


class OpenAIModel(BaseModel):
    def __init__(self, model_name: str, base_url: Optional[str] = None,
                 api_key: Optional[str] = None):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=api_key or cfg.OPENAI_API_KEY,
            base_url=base_url,
        )
        self._model = model_name

    def ask(self, system, user, temperature=0.7, max_tokens=4096) -> ModelResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = resp.choices[0].message.content
        usage = resp.usage
        return ModelResponse(
            content=content,
            model_used=self._model,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )

    @property
    def name(self):
        return f"openai/{self._model}"


class GroqModel(OpenAIModel):
    def __init__(self, model_name: str):
        super().__init__(
            model_name=model_name,
            base_url="https://api.groq.com/openai/v1",
            api_key=cfg.GROQ_API_KEY,
        )

    @property
    def name(self):
        return f"groq/{self._model}"


class DeepSeekModel(OpenAIModel):
    def __init__(self, model_name: str):
        super().__init__(
            model_name=model_name,
            base_url="https://api.deepseek.com",
            api_key=cfg.DEEPSEEK_API_KEY,
        )

    @property
    def name(self):
        return f"deepseek/{self._model}"


class OllamaModel(BaseModel):
    def __init__(self, model_name: str):
        from openai import OpenAI
        self._client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        self._model = model_name

    def ask(self, system, user, temperature=0.7, max_tokens=4096) -> ModelResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return ModelResponse(
            content=resp.choices[0].message.content,
            model_used=self._model,
        )

    @property
    def name(self):
        return f"ollama/{self._model}"


_BUILDERS = {
    "claude": ClaudeModel,
    "openai": OpenAIModel,
    "groq": GroqModel,
    "deepseek": DeepSeekModel,
    "ollama": OllamaModel,
}


class ModelFactory:
    """
    Crea el modelo configurado en config.AI_MODEL.
    Si falla, intenta cfg.AI_FALLBACKS en orden.
    """

    def get(self, model_type: Optional[str] = None,
            model_name: Optional[str] = None) -> BaseModel:
        if model_type:
            return self._build({"type": model_type,
                                "name": model_name or cfg.AI_MODEL["name"]})

        configs = [cfg.AI_MODEL] + cfg.AI_FALLBACKS
        last_err = None
        for conf in configs:
            try:
                model = self._build(conf)
                # Smoke test: asegura que la clase se instancia sin error
                return model
            except Exception as e:
                last_err = e
                print(f"[ModelFactory] {conf['type']} no disponible: {e}")

        raise RuntimeError(
            f"Ningún modelo disponible. Último error: {last_err}"
        ) from last_err

    def _build(self, conf: dict) -> BaseModel:
        t = conf["type"]
        n = conf.get("name", "")
        if t not in _BUILDERS:
            raise ValueError(f"Tipo de modelo desconocido: {t}")
        return _BUILDERS[t](n)


def clean_response(text: str) -> str:
    """Elimina thinking tags de DeepSeek-R1 y extrae código Python."""
    if "<think>" in text and "</think>" in text:
        text = text.split("</think>")[-1].strip()
    return text


def extract_code(text: str) -> str:
    """Extrae bloque ```python ... ``` de una respuesta LLM."""
    import re
    blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    # fallback: eliminar triple backtick genérico
    blocks = re.findall(r"```\n?(.*?)```", text, re.DOTALL)
    return blocks[0].strip() if blocks else text.strip()
