"""fal.ai over its queue REST API (https://docs.fal.ai/model-endpoints/queue)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time

import httpx

from ..config import Settings
from .base import ImageResult, ProviderError, TrainingStatus, Usage
from .pricing import image_usage, training_usage

log = logging.getLogger("purrpost.fal")

QUEUE = "https://queue.fal.run"


def data_uri(data: bytes, content_type: str = "image/jpeg") -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode()}"


class FalClient:
    def __init__(self, settings: Settings, key: str, billed_to: str = "shared",
                 http: httpx.AsyncClient | None = None, poll_every: float = 2.0, timeout: float = 600.0) -> None:
        self.settings = settings
        self.billed_to = billed_to
        self.key = key
        self.http = http or httpx.AsyncClient(timeout=60.0)
        self.poll_every = poll_every
        self.timeout = timeout

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Key {self.key}"}

    async def _req(self, method: str, url: str, **kw) -> dict:
        try:
            r = await self.http.request(method, url, headers=self._headers, **kw)
        except httpx.HTTPError as e:
            raise ProviderError("fal_unreachable", str(e), retryable=True) from e
        if r.status_code in (401, 403):
            raise ProviderError("fal_auth", "fal.ai key is invalid")
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError("fal_busy", f"fal.ai {r.status_code}", retryable=True)
        if r.status_code >= 400:
            raise ProviderError("fal_bad_request", r.text[:500])
        return r.json()

    async def submit(self, model: str, payload: dict) -> dict:
        """Queue a request; returns {request_id, status_url, response_url}."""
        return await self._req("POST", f"{QUEUE}/{model}", json=payload)

    async def run(self, model: str, payload: dict) -> dict:
        h = await self.submit(model, payload)
        deadline = time.monotonic() + self.timeout
        while True:
            st = await self._req("GET", h["status_url"])
            if st.get("status") == "COMPLETED":
                break
            if time.monotonic() > deadline:
                raise ProviderError("fal_timeout", f"{model} took too long", retryable=True)
            await asyncio.sleep(self.poll_every)
        res = await self._req("GET", h["response_url"])
        if "detail" in res and "images" not in res:
            raise ProviderError("fal_failed", str(res["detail"])[:500])
        return res

    async def _download(self, urls: list[str]) -> list[bytes]:
        out = []
        for u in urls:
            if u.startswith("data:"):
                out.append(base64.b64decode(u.split(",", 1)[1]))
                continue
            r = await self.http.get(u)
            if r.status_code != 200:
                raise ProviderError("fal_download", f"image download {r.status_code}", retryable=True)
            out.append(r.content)
        return out

    def _usage(self, u: Usage) -> Usage:
        u.billed_to = self.billed_to
        return u

    # ---- ImageGen ----

    async def generate(self, prompt, n, width, height, seed=None) -> ImageResult:
        model = self.settings.fal_model_candidates
        images: list[bytes] = []
        while len(images) < n:  # flux/dev returns up to 4 images per request
            k = min(4, n - len(images))
            res = await self.run(model, {"prompt": prompt, "num_images": k, "image_size": {"width": width, "height": height},
                                         "enable_safety_checker": True, **({"seed": seed + len(images)} if seed is not None else {})})
            images += await self._download([i["url"] for i in res.get("images", [])])
        return ImageResult(images, self._usage(image_usage(model, n, width, height, "image.candidates")))

    async def edit(self, image, prompt, seed=None) -> ImageResult:
        model = self.settings.fal_model_edit
        res = await self.run(model, {"prompt": prompt, "image_url": data_uri(image), "num_images": 1,
                                     "aspect_ratio": "4:5", **({"seed": seed} if seed is not None else {})})
        images = await self._download([i["url"] for i in res.get("images", [])])
        return ImageResult(images, self._usage(image_usage(model, 1, 1024, 1280, "image.refsheet")))

    async def generate_lora(self, prompt, lora_url, n, width, height, seed=None) -> ImageResult:
        model = self.settings.fal_model_lora
        res = await self.run(model, {"prompt": prompt, "loras": [{"path": lora_url, "scale": 1.0}], "num_images": n,
                                     "image_size": {"width": width, "height": height}, "enable_safety_checker": True,
                                     **({"seed": seed} if seed is not None else {})})
        images = await self._download([i["url"] for i in res.get("images", [])])
        return ImageResult(images, self._usage(image_usage(model, n, width, height, "image.lora")))


class FalTrainer:
    def __init__(self, client: FalClient) -> None:
        self.client = client
        self.billed_to = client.billed_to

    async def submit(self, zip_url: str, trigger_word: str) -> tuple[dict, Usage]:
        s = self.client.settings
        h = await self.client.submit(s.fal_model_training, {
            "images_data_url": zip_url, "trigger_word": trigger_word, "steps": s.fal_training_steps,
            "create_masks": True, "is_style": False})
        u = training_usage()
        u.billed_to = self.billed_to
        return {"request_id": h["request_id"], "status_url": h["status_url"], "response_url": h["response_url"],
                "trigger": trigger_word}, u

    async def status(self, handle: dict) -> TrainingStatus:
        st = await self.client._req("GET", handle["status_url"])
        state = st.get("status")
        if state == "IN_QUEUE":
            return TrainingStatus("queued")
        if state == "IN_PROGRESS":
            return TrainingStatus("running", logs=[x.get("message", "") for x in st.get("logs") or []][-3:])
        if state != "COMPLETED":
            return TrainingStatus("failed", error=str(st)[:300])
        res = await self.client._req("GET", handle["response_url"])
        url = (res.get("diffusers_lora_file") or {}).get("url")
        if not url:
            return TrainingStatus("failed", error=str(res.get("detail") or "no weights in response")[:300])
        return TrainingStatus("done", lora_url=url)
