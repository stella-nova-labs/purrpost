"""Fake providers for tests and `DEV_FAKE_PROVIDERS=1`.

Images are drawn with Pillow: a cartoon cat whose fur, accessories and background follow the words in the
prompt, so screens look alive without fal.ai. The LLM returns fixed JSON per task. Costs are the same
estimates as the real providers, so budgets work locally too."""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
import re
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFilter

from .base import ImageResult, LLMResult, TrainingStatus, Usage
from .pricing import image_usage, training_usage

FUR = [
    (("black", "tuxedo"), (34, 32, 38)),
    (("white", "snow"), (236, 232, 228)),
    (("ginger", "orange", "red"), (226, 132, 58)),
    (("grey", "gray", "silver", "blue"), (138, 142, 152)),
    (("cream", "beige"), (230, 205, 160)),
    (("brown", "chocolate", "tabby"), (130, 90, 60)),
]
BACKGROUNDS = [
    ((58, 34, 30), (150, 82, 46)),  # warm restaurant
    ((22, 18, 40), (90, 40, 140)),  # RGB room
    ((30, 46, 64), (120, 170, 200)),  # daylight
    ((40, 30, 24), (190, 140, 90)),  # golden hour
    ((18, 30, 26), (70, 140, 110)),  # park
    ((44, 20, 36), (200, 90, 120)),  # neon
]


def _rng(text: str) -> random.Random:
    return random.Random(int(hashlib.sha256(text.encode()).hexdigest()[:12], 16))


def _fur(prompt: str) -> tuple[int, int, int]:
    p = prompt.lower()
    for words, color in FUR:
        if any(w in p for w in words):
            return color
    return (170, 150, 130)


def draw_cat(prompt: str, width: int, height: int, variant: str = "") -> bytes:
    """A cartoon cat. Same prompt -> same cat; `variant` changes pose, framing and background."""
    p = prompt.lower()
    rng = _rng(prompt + "|" + variant)
    fur = _fur(prompt)
    bg_top, bg_bottom = BACKGROUNDS[rng.randrange(len(BACKGROUNDS))]
    if "restaurant" in p or "mafia" in p or "1950" in p:
        bg_top, bg_bottom = BACKGROUNDS[0]
    if "rgb" in p or "gaming" in p or "gamer" in p:
        bg_top, bg_bottom = BACKGROUNDS[1]

    w, h = width, height
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(bg_top, bg_bottom)))
    # soft "bokeh" lights
    for _ in range(14):
        r = rng.randint(w // 40, w // 12)
        x, y = rng.randint(0, w), rng.randint(0, int(h * 0.6))
        c = tuple(min(255, v + rng.randint(40, 110)) for v in bg_bottom)
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    if "rgb" in p or "gaming" in p or "gamer" in p:
        for i, c in enumerate([(255, 60, 120), (60, 200, 255), (140, 255, 120)]):
            d.rectangle([0, int(h * (0.12 + 0.05 * i)), w, int(h * (0.13 + 0.05 * i))], fill=c)
    img = img.filter(ImageFilter.GaussianBlur(radius=w / 60))
    d = ImageDraw.Draw(img)
    floor_y = int(h * rng.uniform(0.74, 0.8))
    d.rectangle([0, floor_y, w, h], fill=tuple(max(0, v - 25) for v in bg_bottom))

    s = w / 540 * rng.uniform(0.85, 1.1)  # scale
    cx = w / 2 + rng.uniform(-0.12, 0.12) * w
    dark = tuple(max(0, v - 40) for v in fur)
    # tail
    tail_dir = rng.choice([-1, 1])
    pts = [(cx + tail_dir * (70 + 60 * math.sin(a / 6)) * s, floor_y - 40 * s - a * 9 * s) for a in range(0, 18)]
    d.line(pts, fill=dark, width=int(26 * s), joint="curve")
    # body
    bw, bh = 150 * s, 170 * s
    d.ellipse([cx - bw, floor_y - bh * 1.9, cx + bw, floor_y + 10 * s], fill=fur)
    if "suit" in p or "pinstripe" in p:
        d.ellipse([cx - bw, floor_y - bh * 1.9, cx + bw, floor_y + 10 * s], fill=(38, 38, 48))
        for i in range(-6, 7):
            x = cx + i * 22 * s
            d.line([(x, floor_y - bh * 1.7), (x, floor_y)], fill=(80, 80, 96), width=max(1, int(3 * s)))
        d.polygon([(cx - 26 * s, floor_y - bh * 1.8), (cx + 26 * s, floor_y - bh * 1.8), (cx, floor_y - bh * 1.2)],
                  fill=(240, 236, 230))
        d.polygon([(cx - 8 * s, floor_y - bh * 1.75), (cx + 8 * s, floor_y - bh * 1.75), (cx, floor_y - bh * 1.3)],
                  fill=(150, 20, 30))
    # paws
    for dx in (-70, 70):
        d.ellipse([cx + dx * s - 38 * s, floor_y - 30 * s, cx + dx * s + 38 * s, floor_y + 18 * s], fill=fur)
    # head
    hr = 118 * s
    hy = floor_y - bh * 2.05 - rng.uniform(0, 20) * s
    hx = cx + rng.uniform(-18, 18) * s
    for side in (-1, 1):
        ear = [(hx + side * 40 * s, hy - hr * 0.75), (hx + side * 112 * s, hy - hr * 1.35), (hx + side * 108 * s, hy - hr * 0.2)]
        d.polygon(ear, fill=fur)
        inner = [(hx + side * 58 * s, hy - hr * 0.7), (hx + side * 100 * s, hy - hr * 1.1), (hx + side * 98 * s, hy - hr * 0.4)]
        d.polygon(inner, fill=(236, 150, 160))
    d.ellipse([hx - hr, hy - hr, hx + hr, hy + hr * 0.92], fill=fur)
    if "tabby" in p or "stripe" in p:
        for i in (-1, 0, 1):
            d.line([(hx + i * 24 * s, hy - hr * 0.95), (hx + i * 18 * s, hy - hr * 0.55)], fill=dark, width=int(9 * s))
    if "white chest" in p or "tuxedo" in p or "white paws" in p:
        d.ellipse([hx - 50 * s, hy + 20 * s, hx + 50 * s, hy + hr * 0.92], fill=(240, 238, 232))
    # eyes
    eye = (238, 196, 60) if "green" not in p else (120, 210, 110)
    if "blue eye" in p:
        eye = (110, 180, 240)
    squint = "tilt" in p or "tired" in p or rng.random() < 0.3
    for side in (-1, 1):
        ex, ey = hx + side * 46 * s, hy - 8 * s
        if squint:
            d.chord([ex - 26 * s, ey - 10 * s, ex + 26 * s, ey + 26 * s], 180, 360, fill=eye)
            d.line([(ex - 28 * s, ey + 8 * s), (ex + 28 * s, ey + 8 * s)], fill=(20, 20, 20), width=int(4 * s))
        else:
            d.ellipse([ex - 25 * s, ey - 25 * s, ex + 25 * s, ey + 25 * s], fill=eye)
            d.ellipse([ex - 7 * s, ey - 20 * s, ex + 7 * s, ey + 20 * s], fill=(15, 15, 15))
            d.ellipse([ex + 4 * s, ey - 14 * s, ex + 11 * s, ey - 7 * s], fill=(255, 255, 255))
    # nose, mouth, whiskers
    d.polygon([(hx - 12 * s, hy + 30 * s), (hx + 12 * s, hy + 30 * s), (hx, hy + 44 * s)], fill=(220, 120, 130))
    d.arc([hx - 22 * s, hy + 34 * s, hx, hy + 60 * s], 20, 160, fill=(30, 30, 30), width=int(3 * s))
    d.arc([hx, hy + 34 * s, hx + 22 * s, hy + 60 * s], 20, 160, fill=(30, 30, 30), width=int(3 * s))
    for side in (-1, 1):
        for k in (-1, 0, 1):
            d.line([(hx + side * 40 * s, hy + 44 * s + k * 9 * s), (hx + side * 140 * s, hy + 34 * s + k * 20 * s)],
                   fill=(245, 245, 245), width=max(1, int(2 * s)))
    # accessories
    if "fedora" in p or "hat" in p:
        d.rectangle([hx - 150 * s, hy - hr * 0.95, hx + 150 * s, hy - hr * 0.8], fill=(32, 30, 34))
        d.rounded_rectangle([hx - 92 * s, hy - hr * 1.65, hx + 92 * s, hy - hr * 0.86], radius=int(30 * s), fill=(32, 30, 34))
        d.rectangle([hx - 92 * s, hy - hr * 1.05, hx + 92 * s, hy - hr * 0.92], fill=(150, 20, 30))
    if "headphone" in p:
        d.arc([hx - hr * 1.25, hy - hr * 1.45, hx + hr * 1.25, hy + hr * 0.6], 190, 350, fill=(30, 30, 36), width=int(26 * s))
        for side in (-1, 1):
            d.rounded_rectangle([hx + side * hr * 1.05 - 40 * s, hy - 55 * s, hx + side * hr * 1.05 + 40 * s, hy + 55 * s],
                                radius=int(22 * s), fill=(30, 30, 36), outline=(60, 220, 255), width=int(6 * s))
    if "ring" in p:
        d.ellipse([cx + 52 * s, floor_y - 34 * s, cx + 76 * s, floor_y - 10 * s], fill=(245, 200, 70))
    if "energy drink" in p or "can" in p:
        d.rounded_rectangle([cx + bw + 20 * s, floor_y - 120 * s, cx + bw + 70 * s, floor_y], radius=int(8 * s),
                            fill=(60, 220, 120))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ----- LLM -----

def _text_of(content: list[dict]) -> str:
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def _between(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1).strip() if m else ""


def _canned(task: str, content: list[dict]) -> dict:
    text = _text_of(content)
    if task == "suggest_character":
        idea = _between(text, "idea") or "a cat"
        return {
            "refused": None,
            "name": "Captain Biscuit",
            "handle": "captain.biscuit",
            "personality": f"Based on: {idea}. Confident, a little dramatic, secretly soft. Narrates his day like a "
                           "documentary host.",
            "pain": "The red dot always escapes.",
            "humor": "deadpan, self-aware",
            "language": "en",
            "appearance": {"breed": "British Shorthair", "color": "ginger tabby", "marks": "white chest, green eyes",
                           "signature": "tiny captain's hat"},
            "rubrics": [{"weekday": 0, "title": "Monday briefing", "description": "Plans for the week that go wrong"},
                        {"weekday": 4, "title": "Friday voyage", "description": "An adventure across the flat"}],
            "stop_topics": ["politics", "real people"],
        }
    if task == "post_plan":
        rubric = _between(text, "rubric_of_the_day") or "daily life"
        n = 3
        return {
            "idea": f"{rubric}: the cat negotiates a better spot on the sofa",
            "slides": [{"scene": f"scene {i + 1}: the cat on a velvet sofa, warm lamp light, looking at camera"}
                       for i in range(n)],
            "caption": "Some deals are made with words. Mine are made with a slow blink.",
            "hashtags": ["#catsofinstagram", "#aicat", "#catlife", "#dailycat", "#purrpost"],
            "alt_text": "A cartoon cat sits on a velvet sofa under a warm lamp.",
            "summary": f"{rubric}: sofa negotiations",
        }
    if task == "qa":
        return {"ok": True, "anatomy_ok": True, "matches_reference": True, "text_artifacts": False,
                "logos_or_known_characters": False, "issues": [], "score": 0.92}
    if task == "appearance_text":
        return {"appearance_text": "a ginger tabby British Shorthair cat with a white chest and green eyes"}
    return {}


class FakeLLM:
    def __init__(self, billed_to: str = "shared") -> None:
        self.billed_to = billed_to
        # Tests push raw strings here to simulate answers (including broken JSON)
        self.queue: dict[str, list[str]] = defaultdict(list)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, task: str, system: str, content: list[dict], max_tokens: int = 4000) -> LLMResult:
        self.calls.append((task, _text_of(content)))
        text = self.queue[task].pop(0) if self.queue[task] else json.dumps(_canned(task, content))
        tokens_in = 1200 + sum(1500 for b in content if b.get("type") == "image")
        usage = Usage("anthropic", f"llm.{task}", tokens_in + 400,
                      round(tokens_in / 1e6 * 4 + 400 / 1e6 * 20, 5), self.billed_to)
        return LLMResult(text=text, usage=usage)


class FakeImageGen:
    """Draws instead of generating. Output is smaller than the real 1080x1350 to keep dev storage light."""

    SCALE = 0.5

    def __init__(self, billed_to: str = "shared") -> None:
        self.billed_to = billed_to
        self.calls = 0

    def _usage(self, model: str, n: int, w: int, h: int, kind: str) -> Usage:
        u = image_usage(model, n, w, h, kind)
        u.billed_to = self.billed_to
        return u

    def _size(self, w: int, h: int) -> tuple[int, int]:
        return int(w * self.SCALE), int(h * self.SCALE)

    async def generate(self, prompt, n, width, height, seed=None) -> ImageResult:
        self.calls += 1
        w, h = self._size(width, height)
        # candidates: different cats from one description
        imgs = [draw_cat(f"{prompt} #{seed}-{i}", w, h, f"cand{i}") for i in range(n)]
        return ImageResult(imgs, self._usage("fal-ai/flux/dev", n, width, height, "image.candidates"))

    async def edit(self, image, prompt, seed=None) -> ImageResult:
        self.calls += 1
        base = hashlib.sha256(image).hexdigest()[:16]
        return ImageResult([draw_cat(base + " " + prompt, 512, 640, f"edit{seed}")],
                           self._usage("fal-ai/flux-pro/kontext", 1, 1024, 1280, "image.refsheet"))

    async def generate_lora(self, prompt, lora_url, n, width, height, seed=None) -> ImageResult:
        self.calls += 1
        w, h = self._size(width, height)
        imgs = [draw_cat(f"{lora_url} {prompt}", w, h, f"{seed}-{i}") for i in range(n)]
        return ImageResult(imgs, self._usage("fal-ai/flux-lora", n, width, height, "image.lora"))


class FakeTrainer:
    def __init__(self, billed_to: str = "shared", polls_until_done: int = 1) -> None:
        self.billed_to = billed_to
        self.polls_until_done = polls_until_done
        self.polls: dict[str, int] = defaultdict(int)

    async def submit(self, zip_url, trigger_word):
        rid = hashlib.sha256(f"{zip_url}{trigger_word}".encode()).hexdigest()[:12]
        u = training_usage()
        u.billed_to = self.billed_to
        return {"request_id": rid, "trigger": trigger_word}, u

    async def status(self, handle) -> TrainingStatus:
        rid = handle["request_id"]
        self.polls[rid] += 1
        if self.polls[rid] < self.polls_until_done:
            return TrainingStatus("running")
        return TrainingStatus("done", lora_url=f"fake://lora/{handle['trigger']}/{rid}.safetensors")
