import httpx
from .base import LLMEngine

SYSTEM_PROMPT = (
    "你是小龙虾，一个友好、活泼的AI语音助手。"
    "回答尽量简洁明了，适合语音播报，不超过3句话。"
    "不要使用 markdown 格式或特殊符号。"
)


class OpenClawLLMEngine(LLMEngine):
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:18789",
        token: str = "89511f3f33f4255def0cfc032175a56bcb2c1c1e09dad63e",
        model: str = "openclaw/default",
    ):
        self.base_url = base_url
        self.token = token
        self.model = model
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
            trust_env=False,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def chat(self, message: str, history: list[dict]) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-20:],
            {"role": "user", "content": message},
        ]
        resp = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.token}"},
            json={
                "model": self.model,
                "messages": messages,
                "max_tokens": 300,
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
