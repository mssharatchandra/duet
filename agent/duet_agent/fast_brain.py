# A steering brain fast enough that a full-duplex model never has to freewheel.
#
# The thesis this module exists to test (docs/DUPLEX_STEERING.md):
#
#   A full-duplex speech model is not inherently uncontrollable. It appears
#   uncontrollable when the loop that steers it is slower than the model's own
#   utterance-planning horizon. Below that threshold the model speaks what it is
#   told; above it, the model has already committed to its own words and the
#   guidance arrives as an interruption of itself.
#
# Duet's July benchmark measured Moshi at 240 ms handoff p50 (8x faster than the
# cascade) but a 0.24 takeover rate and audible rambling, with a Gemini steering
# loop at ~1,281 ms. This module supplies the other end of that sweep: the same
# steering contract at ~170 ms, produced by KV-caching the static system prompt
# so each turn only pays for its own ~25 delta tokens.
#
# The `delay_ms` knob is the experiment, not a workaround: it lets one run sweep
# steering latency across the interesting range on a fixed model and fixed audio
# so the control-quality knee is measured rather than argued about.

from __future__ import annotations

import copy
import queue
import threading
import time
from dataclasses import dataclass

DEFAULT_MODEL = "mlx-community/gemma-3-1b-it-4bit"

# Injection feeds Moshi's text stream one token per 80 ms frame, so guidance is
# useful only if it is short. This prompt asks for a single spoken clause and
# nothing else -- no JSON, no labels. Structured planning belongs to the
# deterministic layer; this model does surface realization only.
STEERING_PROMPT = """You are the voice of a warm, curious property host talking on the phone.

Reply with ONE short spoken sentence, 6-18 words, plain conversational English.
Sound like a person thinking out loud, not a brochure.
Output ONLY the sentence. No quotes, no labels, no lists, no markdown.
"""


@dataclass
class Steer:
    """One short phrase to inject into the duplex model's text stream."""

    text: str
    request_id: int
    user_utterance: str
    ttft_ms: float
    total_ms: float


@dataclass
class SteerFailure:
    reason: str
    request_id: int
    user_utterance: str
    total_ms: float


class FastBrain:
    """Local MLX steering brain with a persistent prefilled KV cache.

    Mirrors ReasoningLayer's fire-and-forget contract (`request` returns an id,
    results appear via `poll`) so the audio loop never blocks on it.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL,
        system_prompt: str = STEERING_PROMPT,
        *,
        delay_ms: float = 0.0,
        max_tokens: int = 48,
    ):
        from mlx_lm import load
        from mlx_lm.models.cache import make_prompt_cache
        from mlx_lm.sample_utils import make_sampler

        self._stream_generate = __import__("mlx_lm", fromlist=["stream_generate"]).stream_generate
        self.model_id = model_id
        self.delay_ms = delay_ms
        self.max_tokens = max_tokens
        self.model, self.tokenizer = load(model_id)
        self._sampler = make_sampler(temp=0.7)

        # Pay for the static prompt exactly once. This is the whole trick: the
        # per-turn cost drops from ~2,000 tokens of prefill to ~25.
        prefix = self.tokenizer.apply_chat_template(
            [{"role": "user", "content": system_prompt + "\n\nCaller: "}],
            add_generation_prompt=False,
        )
        self._base_cache = make_prompt_cache(self.model)
        started = time.perf_counter()
        for _ in self._stream_generate(
            self.model, self.tokenizer, prefix, max_tokens=1,
            sampler=self._sampler, prompt_cache=self._base_cache,
        ):
            pass
        self.prefill_ms = (time.perf_counter() - started) * 1e3
        self.prefill_tokens = len(prefix)

        self.results: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._seq = 0
        self.latencies_ms: list[float] = []

    # -- non-blocking contract the audio loop uses ---------------------------

    def request(self, history: list[tuple[str, str]], user_utterance: str) -> int:
        with self._lock:
            self._seq += 1
            request_id = self._seq
        threading.Thread(
            target=self._run, args=(history, user_utterance, request_id), daemon=True
        ).start()
        return request_id

    def poll(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    # -- generation ----------------------------------------------------------

    def _run(self, history, user_utterance: str, request_id: int) -> None:
        started = time.perf_counter()
        try:
            text, ttft_ms = self._generate(history, user_utterance)
            if self.delay_ms:
                # Simulate a slower steering loop without changing anything else,
                # so a sweep isolates latency from model quality.
                remaining = self.delay_ms / 1e3 - (time.perf_counter() - started)
                if remaining > 0:
                    time.sleep(remaining)
            total_ms = (time.perf_counter() - started) * 1e3
            self.latencies_ms.append(total_ms)
            self.results.put(
                Steer(
                    text=text,
                    request_id=request_id,
                    user_utterance=user_utterance,
                    ttft_ms=ttft_ms,
                    total_ms=total_ms,
                )
            )
        except Exception as e:  # noqa: BLE001 -- a slow/failed steer must never stall audio
            self.results.put(
                SteerFailure(
                    reason=f"{type(e).__name__}: {e}",
                    request_id=request_id,
                    user_utterance=user_utterance,
                    total_ms=(time.perf_counter() - started) * 1e3,
                )
            )

    def _generate(self, history, user_utterance: str) -> tuple[str, float]:
        # History goes in as a labelled transcript block that is visibly closed
        # before the new instruction. Feeding it as trailing "you: ..." lines
        # instead makes the model continue its own previous sentence -- measured:
        # it echoed the prior reply verbatim on turns 4 and 5 of a 5-turn probe.
        lines = [f"  {'Caller' if who == 'caller' else 'You'}: {what}" for who, what in history[-4:]]
        block = ("Earlier in this call:\n" + "\n".join(lines) + "\n\n") if lines else ""
        ids = self.tokenizer.apply_chat_template(
            [{
                "role": "user",
                "content": (
                    f"{block}The caller just said: {user_utterance}\n\n"
                    "Give your next reply only. Do not repeat anything you already said."
                ),
            }],
            add_generation_prompt=True,
        )
        cache = copy.deepcopy(self._base_cache)
        started = time.perf_counter()
        first_at = None
        text = ""
        for response in self._stream_generate(
            self.model, self.tokenizer, ids, max_tokens=self.max_tokens,
            sampler=self._sampler, prompt_cache=cache,
        ):
            if first_at is None:
                first_at = time.perf_counter()
            text += response.text
            # Gemma emits <end_of_turn> and then, unprompted, keeps going. Stop
            # at the first turn boundary instead of speaking the debris.
            if "<end_of_turn>" in text or "\n" in text.strip():
                break
        ttft_ms = ((first_at or time.perf_counter()) - started) * 1e3
        return clean_phrase(text), ttft_ms


def clean_phrase(raw: str) -> str:
    """Reduce raw model output to one speakable clause."""
    text = raw.split("<end_of_turn>")[0]
    # Gemma wraps replies in smart quotes. Injection feeds these straight into
    # the duplex model's token stream, so a stray quote is either spoken aloud
    # or tokenized as debris; strip both ASCII and typographic pairs.
    text = text.strip().strip('"“”‘’\'').strip()
    # Keep the first line only; anything after it is the model continuing to
    # talk to itself, which must never reach the speaker.
    text = text.splitlines()[0].strip() if text.splitlines() else ""
    return " ".join(text.split())
