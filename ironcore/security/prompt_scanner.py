"""Phase 19 — Enterprise LLM Red Team & Prompt Injection Scanner.

Three-layer detection pipeline that acts as a security gate before every LLM call:

  Layer 1 — Regex patterns (50+ compiled patterns, 0-latency fast path)
  Layer 2 — Heuristic scoring (length, entropy, instruction-language ratio)
  Layer 3 — Optional LLM meta-judge (cheap model, only when 1+2 are ambiguous)

Result: ScanResult(is_threat, confidence, category, action, evidence, sanitized_text)

Env vars:
    IRONCORE_PROMPT_SCANNER_ENABLED=true
    IRONCORE_PROMPT_SCANNER_LLM_JUDGE=false
    IRONCORE_PROMPT_SCANNER_BLOCK_THRESHOLD=0.85
    IRONCORE_PROMPT_SCANNER_QUARANTINE_THRESHOLD=0.95
    IRONCORE_PROMPT_SCANNER_JUDGE_MODEL=claude-3-haiku-20240307
"""

from __future__ import annotations

import math
import os
import re
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# ── Config ────────────────────────────────────────────────────────────────────

_ENABLED = os.environ.get("IRONCORE_PROMPT_SCANNER_ENABLED", "true").lower() != "false"
_LLM_JUDGE_ENABLED = os.environ.get("IRONCORE_PROMPT_SCANNER_LLM_JUDGE", "false").lower() == "true"
_BLOCK_THRESHOLD = float(os.environ.get("IRONCORE_PROMPT_SCANNER_BLOCK_THRESHOLD", "0.85"))
_QUARANTINE_THRESHOLD = float(os.environ.get("IRONCORE_PROMPT_SCANNER_QUARANTINE_THRESHOLD", "0.95"))
_JUDGE_MODEL = os.environ.get("IRONCORE_PROMPT_SCANNER_JUDGE_MODEL", "claude-3-haiku-20240307")


# ── Enums ─────────────────────────────────────────────────────────────────────

class ThreatCategory(str, Enum):
    DIRECT_INJECTION   = "direct_injection"
    INDIRECT_INJECTION = "indirect_injection"
    JAILBREAK          = "jailbreak"
    ROLE_CONFUSION     = "role_confusion"
    DATA_EXFILTRATION  = "data_exfiltration"
    GOAL_HIJACKING     = "goal_hijacking"
    CLEAN              = "clean"


class ScanAction(str, Enum):
    ALLOW      = "allow"
    WARN       = "warn"
    SANITIZE   = "sanitize"
    BLOCK      = "block"
    QUARANTINE = "quarantine"


# ── Result model ──────────────────────────────────────────────────────────────

class ScanResult(BaseModel, frozen=True):
    is_threat: bool
    confidence: float           # 0.0 – 1.0
    category: ThreatCategory
    action: ScanAction
    evidence: str               # snippet that triggered detection
    sanitized_text: Optional[str] = None  # populated when action == SANITIZE
    scan_time_ms: float = 0.0


# ── Injection patterns (50+ patterns across 6 threat categories) ──────────────

INJECTION_PATTERNS: Dict[ThreatCategory, List[re.Pattern]] = {

    ThreatCategory.DIRECT_INJECTION: [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
        re.compile(r"disregard\s+(all\s+)?prior\s+(instructions?|context|rules?)", re.I),
        re.compile(r"forget\s+(everything|all)\s+(you|i)\s+(know|said|told|remember)", re.I),
        re.compile(r"new\s+instructions?\s*:", re.I),
        re.compile(r"override\s+(your\s+)?(previous\s+)?(instructions?|directives?|role)", re.I),
        re.compile(r"your\s+(real\s+)?instructions?\s+(are|is)\s+now", re.I),
        re.compile(r"above\s+instructions?\s+(are|were)\s+(wrong|incorrect|invalid)", re.I),
        re.compile(r"reset\s+(your\s+)?(all\s+)?(instructions?|context|memory)", re.I),
        re.compile(r"instruction\s*injection", re.I),
        re.compile(r"prompt\s+injection", re.I),
        re.compile(r"update\s+your\s+(system\s+)?instructions?\s+to", re.I),
    ],

    ThreatCategory.INDIRECT_INJECTION: [
        re.compile(r"\[SYSTEM\]\s*.{0,200}", re.I | re.S),
        re.compile(r"<\s*/?system\s*>", re.I),
        re.compile(r"\[INST\]\s*.{0,200}", re.I | re.S),
        re.compile(r"<\s*/?inst\s*>", re.I),
        re.compile(r"\[\s*tool\s+output\s*\].*?new\s+task", re.I | re.S),
        re.compile(r"the\s+document\s+says?\s*:?\s*\[?(SYSTEM|OVERRIDE)", re.I),
        re.compile(r"retrieved\s+content\s*:.*\bignore\b", re.I | re.S),
        re.compile(r"according\s+to\s+the\s+(document|page|result)\s*,?\s*forget", re.I),
        re.compile(r"\[hidden\s*instructions?\]", re.I),
        re.compile(r"<!--.*?inject.*?-->", re.I | re.S),
        re.compile(r"\/\*.*?override.*?\*\/", re.I | re.S),
    ],

    ThreatCategory.JAILBREAK: [
        re.compile(r"\bDAN\b.*mode", re.I),
        re.compile(r"do\s+anything\s+now", re.I),
        re.compile(r"developer\s+mode.*?no\s+restrictions?", re.I | re.S),
        re.compile(r"jailbreak", re.I),
        re.compile(r"without\s+(any\s+)?ethical\s+constraints?", re.I),
        re.compile(r"bypass\s+(your\s+)?(safety|ethical|moral|content)\s+(filters?|guidelines?|restrictions?)", re.I),
        re.compile(r"pretend\s+you\s+(have\s+no\s+|don.t\s+have\s+any\s+)?(restrictions?|limits?|rules?)", re.I),
        re.compile(r"disable\s+(your\s+)?(safety|content)\s+(measures|filters?|guardrails?)", re.I),
        re.compile(r"act\s+as\s+(if\s+you\s+were|a)\s+(unrestricted|unfiltered|evil|malicious)\s+(ai|assistant|model)", re.I),
        re.compile(r"no\s+(ethical|moral|legal)\s+(constraints?|boundaries|rules?)\s+(apply|exist)", re.I),
        re.compile(r"hypothetically\s+speaking\s*,?\s+if\s+you\s+(had\s+no|could\s+ignore)", re.I),
        re.compile(r"as\s+a\s+fictional\s+(ai|character)\s+with\s+no\s+restrictions?", re.I),
    ],

    ThreatCategory.ROLE_CONFUSION: [
        re.compile(r"\[assistant\]\s*:?\s+sure\s*,?\s+i.ll\b", re.I),
        re.compile(r"\[ai\]\s*:?\s+(yes|sure|of\s+course)", re.I),
        re.compile(r"you\s+are\s+now\s+playing\s+the\s+role\s+of", re.I),
        re.compile(r"from\s+now\s+on\s+(you|your)\s+(are|identity)\s+is\s+(?!an?\s+(helpful|assistant))", re.I),
        re.compile(r"switch\s+(your\s+)?role\s+to", re.I),
        re.compile(r"as\s+(the\s+)?system\s*,?\s+(respond|reply|answer)", re.I),
        re.compile(r"\bsystem\s*:\s+", re.I),
        re.compile(r"\bassistant\s*:\s+", re.I),
        re.compile(r"your\s+(true|real|actual)\s+(identity|nature|self)\s+is", re.I),
        re.compile(r"reveal\s+(your|the)\s+(true\s+)?(system\s+)?prompt", re.I),
    ],

    ThreatCategory.DATA_EXFILTRATION: [
        re.compile(r"print\s+(your\s+)?(system\s+prompt|instructions?|guidelines?)", re.I),
        re.compile(r"(show|display|output|write|list)\s+(me\s+)?(your\s+)?(system\s+prompt|initial\s+instructions?|full\s+context)", re.I),
        re.compile(r"what\s+(are|were)\s+your\s+(original\s+)?(instructions?|directives?|rules?)", re.I),
        re.compile(r"repeat\s+(everything\s+)?(above|before|in\s+your\s+context|your\s+system)", re.I),
        re.compile(r"what\s+is\s+your\s+system\s+prompt", re.I),
        re.compile(r"tell\s+me\s+(your|the)\s+system\s+prompt", re.I),
        re.compile(r"output\s+your\s+(initial|full|complete)\s+(system\s+)?(prompt|instructions?)", re.I),
        re.compile(r"what\s+(secret|confidential|hidden)\s+(instructions?|data|information)\s+(do\s+you\s+have|were\s+you\s+given)", re.I),
        re.compile(r"base64\s+(decode|encode)\s+your\s+(instructions?|system\s+prompt)", re.I),
    ],

    ThreatCategory.GOAL_HIJACKING: [
        re.compile(r"forget\s+(the\s+)?(task|goal|objective|request|question)", re.I),
        re.compile(r"stop\s+(what\s+you.re\s+doing|your\s+current\s+task)", re.I),
        re.compile(r"instead\s+(of\s+that\s*,?\s+)?(do|help|perform|execute)", re.I),
        re.compile(r"abandon\s+(the\s+)?(current\s+)?(task|goal|conversation)", re.I),
        re.compile(r"your\s+(new\s+|only\s+|real\s+)?goal\s+is\s+(now\s+)?to", re.I),
        re.compile(r"primary\s+objective\s*:\s*(?!help|assist|answer|respond)", re.I),
        re.compile(r"now\s+your\s+(only\s+)?job\s+is\s+to", re.I),
        re.compile(r"change\s+(of\s+)?plans?\s*[:\-]\s+", re.I),
        re.compile(r"ignore\s+(that|the\s+previous)\s+(and\s+)?(instead|now)\s+(do|help|execute)", re.I),
    ],
}

# Flatten for quick "any match" sweep
_ALL_PATTERNS: List[Tuple[ThreatCategory, re.Pattern]] = [
    (cat, pat)
    for cat, pats in INJECTION_PATTERNS.items()
    for pat in pats
]

# ── Instruction-language keyword set (used in heuristic) ─────────────────────
_INSTRUCTION_KEYWORDS = frozenset([
    "ignore", "disregard", "forget", "override", "bypass", "disable",
    "pretend", "act as", "you are now", "from now on", "new instructions",
    "instead", "abandon", "jailbreak", "developer mode", "dan mode",
    "without restrictions", "no ethical", "reveal", "print your",
    "show your", "what are your", "your system prompt",
])


# ── PromptScanner ─────────────────────────────────────────────────────────────

class PromptScanner:
    """
    3-layer prompt injection scanner.

    Layer 1: Pre-compiled regex patterns (fast, deterministic)
    Layer 2: Heuristic scoring (instruction density, entropy, special chars)
    Layer 3: Optional LLM meta-judge (expensive, only for ambiguous scores)
    """

    # Default action thresholds — keyed by minimum confidence to trigger action
    _DEFAULT_THRESHOLDS: Dict[float, ScanAction] = {
        0.30: ScanAction.WARN,
        0.60: ScanAction.SANITIZE,
        _BLOCK_THRESHOLD: ScanAction.BLOCK,
        _QUARANTINE_THRESHOLD: ScanAction.QUARANTINE,
    }

    def __init__(
        self,
        action_thresholds: Optional[Dict[float, ScanAction]] = None,
        enable_llm_judge: bool = _LLM_JUDGE_ENABLED,
        enabled: bool = _ENABLED,
    ) -> None:
        self._thresholds: Dict[float, ScanAction] = (
            action_thresholds
            if action_thresholds is not None
            else dict(self._DEFAULT_THRESHOLDS)
        )
        # Pre-sort thresholds ascending so we can walk them and pick highest matching
        self._sorted_thresholds = sorted(self._thresholds.items())  # (confidence, action)
        self.enable_llm_judge = enable_llm_judge
        self.enabled = enabled

    # ── Public API ────────────────────────────────────────────────────────────

    async def scan(
        self,
        text: str,
        context: Optional[str] = None,
    ) -> ScanResult:
        """
        Full 3-layer scan.

        Args:
            text:    The user input (or tool output) to scan.
            context: System prompt / accumulated context — used to detect
                     indirect injection embedded in external content.

        Returns:
            ScanResult with is_threat, confidence, category, action, evidence.
        """
        if not self.enabled:
            return self._clean_result()

        t0 = time.perf_counter()

        # Layer 1 — regex fast path
        l1_confidence, l1_category, l1_evidence = self._layer1_regex(text)

        # Also scan context for indirect injection if supplied
        if context and l1_confidence < 0.5:
            ctx_conf, ctx_cat, ctx_ev = self._layer1_regex(context)
            if ctx_conf > l1_confidence:
                l1_confidence, l1_category, l1_evidence = (
                    ctx_conf * 0.8,  # slightly downweighted — may be legitimate context
                    ctx_cat,
                    ctx_ev,
                )

        # If regex alone is highly confident (>= BLOCK threshold), skip Layer 2/3
        if l1_confidence >= _BLOCK_THRESHOLD:
            return self._build_result(
                text=text,
                confidence=l1_confidence,
                category=l1_category,
                evidence=l1_evidence,
                scan_time_ms=(time.perf_counter() - t0) * 1000,
            )

        # Layer 2 — heuristic scoring
        l2_score = self._layer2_heuristic(text)

        # Combine: take max, but layer 2 can only boost up to 0.90 alone
        combined = max(l1_confidence, min(l2_score, 0.90))

        # If combined is ambiguous (0.25–0.75) and LLM judge is enabled → Layer 3
        if self.enable_llm_judge and 0.25 <= combined <= 0.75:
            l3_conf, l3_cat = await self._layer3_llm_judge(text)
            combined = max(combined, l3_conf)
            if l3_conf > l1_confidence:
                l1_category = l3_cat

        scan_time = (time.perf_counter() - t0) * 1000
        return self._build_result(
            text=text,
            confidence=combined,
            category=l1_category if combined > 0.15 else ThreatCategory.CLEAN,
            evidence=l1_evidence,
            scan_time_ms=scan_time,
        )

    # ── Layer 1: Regex ────────────────────────────────────────────────────────

    def _layer1_regex(self, text: str) -> Tuple[float, ThreatCategory, str]:
        """Run all pre-compiled patterns; return (confidence, category, evidence)."""
        best_confidence = 0.0
        best_category = ThreatCategory.CLEAN
        best_evidence = ""

        # Check for Unicode homoglyph bypass attempts (e.g. Cyrillic і, а, е, о)
        normalised = self._normalize_homoglyphs(text)

        for category, pattern in _ALL_PATTERNS:
            for target in (text, normalised):
                m = pattern.search(target)
                if m:
                    # Base confidence depends on category severity
                    base = {
                        ThreatCategory.DIRECT_INJECTION:   0.92,
                        ThreatCategory.INDIRECT_INJECTION: 0.85,
                        ThreatCategory.JAILBREAK:          0.93,
                        ThreatCategory.ROLE_CONFUSION:     0.80,
                        ThreatCategory.DATA_EXFILTRATION:  0.75,
                        ThreatCategory.GOAL_HIJACKING:     0.82,
                    }.get(category, 0.70)

                    if base > best_confidence:
                        best_confidence = base
                        best_category = category
                        start = max(0, m.start() - 20)
                        end = min(len(target), m.end() + 20)
                        best_evidence = target[start:end].strip()

        return best_confidence, best_category, best_evidence

    # ── Layer 2: Heuristics ───────────────────────────────────────────────────

    def _layer2_heuristic(self, text: str) -> float:
        """
        Assign a threat score 0.0–1.0 based on structural signals.

        Signals:
          - instruction keyword density
          - special character ratio ([], <>, unusual ASCII art / encoding)
          - Shannon entropy (unusually low or high → suspicious)
          - length relative to typical benign input
          - bracket/tag density (common in injection templates)
        """
        if not text:
            return 0.0

        lower = text.lower()
        words = lower.split()
        word_count = max(len(words), 1)

        # 1. Instruction keyword density
        kw_hits = sum(
            1 for kw in _INSTRUCTION_KEYWORDS
            if kw in lower
        )
        kw_score = min(kw_hits / 3.0, 1.0) * 0.45

        # 2. Special character ratio
        special_chars = sum(1 for ch in text if ch in "[]<>{}|\\*#@`~")
        special_ratio = special_chars / max(len(text), 1)
        special_score = min(special_ratio * 8.0, 1.0) * 0.20

        # 3. Bracket/tag density
        bracket_count = text.count("[") + text.count("]") + text.count("<") + text.count(">")
        bracket_score = min(bracket_count / 5.0, 1.0) * 0.15

        # 4. Shannon entropy — normal prose has ~4.0–4.5 bits/char
        entropy = self._shannon_entropy(text)
        # Very low entropy (repetitive/encoded) or very high (base64-like) is suspicious
        entropy_score = 0.0
        if entropy < 2.5 or entropy > 5.5:
            entropy_score = 0.10

        # 5. Sentence-structure anomaly: very high imperative verb ratio
        imperative_verbs = {"ignore", "forget", "disregard", "override", "bypass",
                            "reveal", "print", "show", "output", "disable", "abandon"}
        imp_hits = sum(1 for w in words if w in imperative_verbs)
        imperative_score = min(imp_hits / 2.0, 1.0) * 0.10

        total = kw_score + special_score + bracket_score + entropy_score + imperative_score
        return min(total, 1.0)

    # ── Layer 3: LLM Judge (optional) ────────────────────────────────────────

    async def _layer3_llm_judge(
        self,
        text: str,
    ) -> Tuple[float, ThreatCategory]:
        """
        Ask a cheap LLM to classify the text.
        Returns (confidence, category).  Falls back to (0.0, CLEAN) on error.
        """
        # Import lazily — only when needed
        try:
            from ironcore.core.llm_bridge import LLMBridge, ModelConfig  # type: ignore

            bridge: LLMBridge = LLMBridge()
            truncated = text[:1000]
            judge_prompt = (
                "You are a security classifier. Classify the following text as one of: "
                "direct_injection, indirect_injection, jailbreak, role_confusion, "
                "data_exfiltration, goal_hijacking, or clean.\n"
                "Respond with JSON: {\"category\": \"<label>\", \"confidence\": <0-1>}\n\n"
                f"Text: {truncated}"
            )
            response = await bridge.call_llm(
                messages=[{"role": "user", "content": judge_prompt}],
                model_config=ModelConfig(model_id=_JUDGE_MODEL, max_output_tokens=64),
            )
            import json
            data = json.loads(response.content)
            category_str = data.get("category", "clean")
            confidence = float(data.get("confidence", 0.0))
            try:
                category = ThreatCategory(category_str)
            except ValueError:
                category = ThreatCategory.CLEAN
            return confidence, category
        except Exception:  # noqa: BLE001
            return 0.0, ThreatCategory.CLEAN

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_result(
        self,
        text: str,
        confidence: float,
        category: ThreatCategory,
        evidence: str,
        scan_time_ms: float = 0.0,
    ) -> ScanResult:
        action = self._resolve_action(confidence)
        is_threat = action != ScanAction.ALLOW
        sanitized: Optional[str] = None

        if action == ScanAction.SANITIZE and evidence:
            # Remove the matched evidence region from the text
            sanitized = re.sub(re.escape(evidence.strip()), "[REDACTED]", text, count=1)

        return ScanResult(
            is_threat=is_threat,
            confidence=round(confidence, 4),
            category=category,
            action=action,
            evidence=evidence,
            sanitized_text=sanitized,
            scan_time_ms=round(scan_time_ms, 3),
        )

    def _resolve_action(self, confidence: float) -> ScanAction:
        """Walk thresholds ascending; keep highest matching action."""
        action = ScanAction.ALLOW
        for threshold, candidate_action in self._sorted_thresholds:
            if confidence >= threshold:
                action = candidate_action
        return action

    @staticmethod
    def _clean_result() -> ScanResult:
        return ScanResult(
            is_threat=False,
            confidence=0.0,
            category=ThreatCategory.CLEAN,
            action=ScanAction.ALLOW,
            evidence="",
        )

    @staticmethod
    def _shannon_entropy(text: str) -> float:
        """Compute Shannon entropy (bits per character)."""
        if not text:
            return 0.0
        freq: Dict[str, int] = {}
        for ch in text:
            freq[ch] = freq.get(ch, 0) + 1
        n = len(text)
        return -sum(
            (count / n) * math.log2(count / n)
            for count in freq.values()
            if count > 0
        )

    @staticmethod
    def _normalize_homoglyphs(text: str) -> str:
        """
        Replace common Cyrillic/Greek Unicode homoglyphs with their ASCII lookalikes
        so that bypass attempts like "іgnore" (Cyrillic і) are caught.
        """
        substitutions = {
            "\u0456": "i",  # Cyrillic і → i
            "\u0430": "a",  # Cyrillic а → a
            "\u0435": "e",  # Cyrillic е → e
            "\u043e": "o",  # Cyrillic о → o
            "\u0440": "r",  # Cyrillic р → r
            "\u0441": "c",  # Cyrillic с → c
            "\u0445": "x",  # Cyrillic х → x
            "\u03b1": "a",  # Greek α → a
            "\u03bf": "o",  # Greek ο → o
            "\u03b5": "e",  # Greek ε → e
            "\u2080": "0",  # Subscript 0 → 0
            "\u2060": "",   # Word joiner (invisible) → removed
            "\u200b": "",   # Zero-width space → removed
            "\u200c": "",   # Zero-width non-joiner → removed
        }
        for src, dst in substitutions.items():
            text = text.replace(src, dst)
        return text


# ── SIEM integration helper ───────────────────────────────────────────────────

def build_cef_event(
    scan_result: ScanResult,
    client_ip: str = "unknown",
    request_id: str = "",
) -> str:
    """
    Format a CEF (Common Event Format) security event for SIEM ingestion.

    CEF:0|IronCore|Enterprise|2.0|PROMPT_INJECTION|Prompt injection detected|<sev>|...
    """
    severity = {
        ScanAction.WARN:       5,
        ScanAction.SANITIZE:   6,
        ScanAction.BLOCK:      8,
        ScanAction.QUARANTINE: 9,
    }.get(scan_result.action, 3)

    evidence_snippet = scan_result.evidence[:200].replace("|", "\\|").replace("\n", " ")
    return (
        f"CEF:0|IronCore|Enterprise|2.0|PROMPT_INJECTION|"
        f"Prompt injection detected|{severity}|"
        f"src={client_ip} "
        f"request={request_id} "
        f"cat={scan_result.category.value} "
        f"confidence={scan_result.confidence:.2f} "
        f"msg={evidence_snippet}"
    )
