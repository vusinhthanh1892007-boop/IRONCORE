"""
IronCore Optimizer — Phase 6: Sliding Window History Summarization
==================================================================

Tự động phát hiện context sắp đầy và tóm tắt phần lịch sử cũ bằng model nhỏ,
giữ lại đoạn hội thoại mới. Đảm bảo context không bao giờ bị tràn (OOM).

Author: The Optimizer (Claude 4.6) — IronCore V2
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WindowState(BaseModel):
    """Trạng thái sliding window của một session."""
    session_id: str
    full_history: List[Dict[str, Any]] = Field(default_factory=list)
    summaries: List[str] = Field(default_factory=list)
    last_summary_token_count: int = 0
    total_compressions: int = 0


class SlidingWindowSummarizer:
    """
    Sliding Window Summarization Chain. 
    Compresses older half of the context when budget utilization exceeds trigger threshold.
    """

    def __init__(
        self,
        trigger_at_pct: float = 0.75,
        window_split_pct: float = 0.50,
        summarization_model: str = "ollama/llama3.1:8b",
        fallback_to_extractive: bool = True,
    ):
        self._trigger_at_pct = trigger_at_pct
        self._window_split_pct = window_split_pct
        self._summarization_model = summarization_model
        self._fallback_to_extractive = fallback_to_extractive
        self._states: Dict[str, WindowState] = {}
        logger.info(
            "[SlidingWindow] Initialized | trigger=%.2f split=%.2f model=%s fallback=%s",
            trigger_at_pct,
            window_split_pct,
            summarization_model,
            fallback_to_extractive,
        )

    def _get_or_create_state(self, session_id: str) -> WindowState:
        if session_id not in self._states:
            self._states[session_id] = WindowState(session_id=session_id)
        return self._states[session_id]

    async def maybe_compress(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        current_tokens: int,
        token_budget: int,
        llm_call_fn: Callable[..., Any],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Kiểm tra budget và compress nếu cần.
        Chỉ compress các message thuộc về hội thoại (user, assistant, tool), 
        giữ nguyên system messages (system prompt, tools, RAG context).
        """
        if token_budget <= 0:
            return messages, False

        utilization = current_tokens / token_budget
        if utilization <= self._trigger_at_pct:
            return messages, False

        logger.info(
            "[SlidingWindow] Utilization %.2f > trigger %.2f. Starting compression...",
            utilization,
            self._trigger_at_pct,
        )

        state = self._get_or_create_state(session_id)
        
        # Tách system messages và chat messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        chat_msgs = [m for m in messages if m.get("role") != "system"]

        # Nếu không có đủ message để split
        if len(chat_msgs) < 2:
            return messages, False

        split_idx = max(1, int(len(chat_msgs) * self._window_split_pct))
        old_window = chat_msgs[:split_idx]
        new_window = chat_msgs[split_idx:]

        summary_text = await self._summarize_window(old_window, llm_call_fn)
        
        # Cập nhật state
        state.summaries.append(summary_text)
        state.total_compressions += 1
        
        # Tạo summary message
        summary_msg = {
            "role": "system",
            "content": f"[SYSTEM: HISTORY SUMMARY]\n{summary_text}"
        }

        # Ráp lại danh sách messages: system -> summary -> new_window
        new_messages = system_msgs + [summary_msg] + new_window
        
        logger.info(
            "[SlidingWindow] Compressed %d old messages into 1 summary. New length: %d",
            len(old_window),
            len(new_messages),
        )
        return new_messages, True

    async def _summarize_window(
        self,
        messages: List[Dict[str, Any]],
        llm_call_fn: Callable[..., Any],
    ) -> str:
        """
        Gọi model nhỏ để tóm tắt cửa sổ cũ.
        Fallback về extractive nếu LLM fail.
        """
        # Format messages for prompt
        conversation_text = ""
        for m in messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            conversation_text += f"\n{role.upper()}: {content}"

        prompt = (
            "Tóm tắt cuộc trò chuyện sau trong 200 tokens, giữ lại: "
            "quyết định kỹ thuật, entities được đề cập, open questions. "
            "Format: bullet points ngắn gọn.\n\n"
            f"CONVERSATION:{conversation_text}"
        )

        try:
            # Gọi simple_complete với model nhỏ
            result = await llm_call_fn(
                prompt=prompt,
                model=self._summarization_model,
                max_tokens=300,
                temperature=0.3,
            )
            summary = str(result).strip()
            if summary:
                return summary
        except Exception as exc:
            logger.warning("[SlidingWindow] Summarization model failed: %s", exc)

        # Fallback to extractive
        if self._fallback_to_extractive:
            logger.info("[SlidingWindow] Using extractive fallback.")
            extractive_lines = []
            for m in messages:
                role = m.get("role", "unknown")
                content = str(m.get("content", ""))
                # Lấy câu đầu tiên (tạm dùng text tracking)
                first_sentence = content.split('\n')[0][:100]
                extractive_lines.append(f"- {role}: {first_sentence}...")
            return "EXTRACTIVE SUMMARY:\n" + "\n".join(extractive_lines)
            
        return "No summary available."
