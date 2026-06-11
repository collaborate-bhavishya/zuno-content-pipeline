"""
Per-run metrics collector with dynamic pricing.

Uses thread-local storage so each pipeline run gets its own isolated collector.
Graph nodes call `record_llm_call()` after each LLM invocation; `main.py`
calls `record_node_timing()` as each node completes.

Pricing is looked up by prefix match against CONFIG.pricing at compute time,
so admin panel model swaps are reflected immediately.
"""
import time
import threading
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

# Thread-local storage for the current run's collector
_local = threading.local()

# ───────────────────────────────────────────────────────────────
# Default pricing per 1M tokens (input / output) and per image
# Keys are prefix-matched: "gemini-2.5-flash" matches
# "gemini-2.5-flash-preview-0514" etc.
# ───────────────────────────────────────────────────────────────

DEFAULT_PRICING = {
    # Google Gemini (Vertex AI)
    "gemini-2.5-flash": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gemini-2.5-pro":   {"input_per_1m": 1.25, "output_per_1m": 10.00},
    "gemini-2.0-flash": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gemini-1.5-flash": {"input_per_1m": 0.075, "output_per_1m": 0.30},
    "gemini-1.5-pro":   {"input_per_1m": 1.25, "output_per_1m": 5.00},
    # Anthropic
    "claude-sonnet":    {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "claude-opus":      {"input_per_1m": 15.00, "output_per_1m": 75.00},
    "claude-haiku":     {"input_per_1m": 0.25, "output_per_1m": 1.25},
    # OpenAI
    "gpt-4o":           {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-4o-mini":      {"input_per_1m": 0.15, "output_per_1m": 0.60},
    # Image
    "imagen-3.0":       {"per_image": 0.03},
    "imagen-2.0":       {"per_image": 0.02},
    # Fallback for unknown models
    "_fallback":        {"input_per_1m": 0.50, "output_per_1m": 2.00},
}


@dataclass
class LLMCall:
    """Record of a single LLM invocation."""
    node: str               # which graph node made the call
    role: str               # "generator", "judge", "vision_judge", "eval_judge"
    model: str              # actual model name used
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0     # wall-clock milliseconds
    cost: float = 0.0       # estimated USD


@dataclass
class NodeTiming:
    """Timing for a single graph node execution."""
    node: str
    latency_ms: int = 0
    started_at: float = 0.0


@dataclass
class RunMetrics:
    """Aggregated metrics for a complete pipeline run."""
    total_latency_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    total_llm_calls: int = 0
    total_image_calls: int = 0
    retries: Dict[str, int] = field(default_factory=dict)
    llm_calls: List[dict] = field(default_factory=list)
    node_timings: List[dict] = field(default_factory=list)
    per_node_summary: Dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class MetricsCollector:
    """Collects metrics during a single pipeline run."""

    def __init__(self):
        self._llm_calls: List[LLMCall] = []
        self._node_timings: List[NodeTiming] = []
        self._image_calls: int = 0
        self._run_start: float = time.time()
        self._pricing: dict = {}  # loaded lazily from CONFIG

    def _get_pricing(self) -> dict:
        """Load pricing from CONFIG (if available) or use defaults."""
        if not self._pricing:
            try:
                from app.core.config import CONFIG
                self._pricing = getattr(CONFIG, 'pricing', None) or DEFAULT_PRICING
            except Exception:
                self._pricing = DEFAULT_PRICING
        return self._pricing

    def _lookup_price(self, model: str) -> dict:
        """Prefix-match model name against pricing table."""
        pricing = self._get_pricing()
        model_lower = model.lower()
        # Try exact match first
        if model_lower in pricing:
            return pricing[model_lower]
        # Prefix match (longest prefix wins)
        best_match = None
        best_len = 0
        for key in pricing:
            if key == "_fallback":
                continue
            if model_lower.startswith(key) and len(key) > best_len:
                best_match = key
                best_len = len(key)
        if best_match:
            return pricing[best_match]
        return pricing.get("_fallback", {"input_per_1m": 0.50, "output_per_1m": 2.00})

    def _compute_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Compute cost in USD for a single LLM call."""
        rates = self._lookup_price(model)
        input_cost = (input_tokens / 1_000_000) * rates.get("input_per_1m", 0)
        output_cost = (output_tokens / 1_000_000) * rates.get("output_per_1m", 0)
        return round(input_cost + output_cost, 6)

    def record_llm_call(
        self,
        node: str,
        role: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
    ):
        """Record a single LLM call with its metrics."""
        cost = self._compute_cost(model, input_tokens, output_tokens)
        call = LLMCall(
            node=node, role=role, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=latency_ms, cost=cost,
        )
        self._llm_calls.append(call)

    def record_image_call(self):
        """Record an image generation API call."""
        self._image_calls += 1

    def record_node_start(self, node: str) -> NodeTiming:
        """Mark the start of a node execution."""
        t = NodeTiming(node=node, started_at=time.time())
        self._node_timings.append(t)
        return t

    def record_node_end(self, timing: NodeTiming):
        """Mark the end of a node execution."""
        timing.latency_ms = int((time.time() - timing.started_at) * 1000)

    def get_node_metrics(self, node: str) -> dict:
        """Get metrics summary for a specific node (for SSE detail)."""
        calls = [c for c in self._llm_calls if c.node == node]
        if not calls:
            return {}
        total_in = sum(c.input_tokens for c in calls)
        total_out = sum(c.output_tokens for c in calls)
        total_cost = sum(c.cost for c in calls)
        total_lat = sum(c.latency_ms for c in calls)
        model = calls[-1].model  # most recent model used
        return {
            "tokens_in": total_in,
            "tokens_out": total_out,
            "cost_usd": round(total_cost, 6),
            "latency_ms": total_lat,
            "model": model,
        }

    def finalize(self, retries: dict) -> RunMetrics:
        """Compute final aggregated metrics for the run."""
        total_latency = int((time.time() - self._run_start) * 1000)
        total_in = sum(c.input_tokens for c in self._llm_calls)
        total_out = sum(c.output_tokens for c in self._llm_calls)
        total_cost = sum(c.cost for c in self._llm_calls)
        # Add image costs
        img_rates = self._lookup_price("imagen-3.0")
        img_cost = self._image_calls * img_rates.get("per_image", 0.03)
        total_cost += img_cost

        # Per-node summary
        per_node: Dict[str, dict] = {}
        for c in self._llm_calls:
            if c.node not in per_node:
                per_node[c.node] = {
                    "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "latency_ms": 0, "cost": 0.0, "model": c.model,
                }
            s = per_node[c.node]
            s["calls"] += 1
            s["input_tokens"] += c.input_tokens
            s["output_tokens"] += c.output_tokens
            s["latency_ms"] += c.latency_ms
            s["cost"] = round(s["cost"] + c.cost, 6)
            s["model"] = c.model

        return RunMetrics(
            total_latency_ms=total_latency,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cost=round(total_cost, 6),
            total_llm_calls=len(self._llm_calls),
            total_image_calls=self._image_calls,
            retries=retries,
            llm_calls=[asdict(c) for c in self._llm_calls],
            node_timings=[{"node": t.node, "latency_ms": t.latency_ms}
                          for t in self._node_timings if t.latency_ms > 0],
            per_node_summary=per_node,
        )


# ───────────────────────────────────────────────────────────────
# Thread-local access (one collector per run)
# ───────────────────────────────────────────────────────────────

def init_collector() -> MetricsCollector:
    """Initialize a fresh collector for this run."""
    c = MetricsCollector()
    _local.collector = c
    return c


def get_collector() -> Optional[MetricsCollector]:
    """Get the current run's collector (or None if not initialized)."""
    return getattr(_local, 'collector', None)


def clear_collector():
    """Clean up the thread-local collector."""
    _local.collector = None
