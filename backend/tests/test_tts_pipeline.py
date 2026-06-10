"""Integration test: streaming LLM tokens -> segmentation -> cleaning -> TTS queue."""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from agent_response import AgentResponse, clean_for_tts


class TestTTSPipeline:
    """Simulates the full pipeline from LLM tokens to TTS-ready segments."""

    def test_streaming_to_tts_segments(self):
        """Verify that streaming tokens produce cleaned segments for TTS."""
        ar = AgentResponse()
        ar.start_streaming()

        # Simulate LLM streaming with markdown
        llm_output = "## 总结\n\n**首先**，我来帮你分析一下。其次，这个问题很简单！最后，请参考[文档](http://example.com)。"
        tokens = [llm_output[i:i+3] for i in range(0, len(llm_output), 3)]

        all_segments = []
        for token in tokens:
            segs = ar.feed_token(token)
            all_segments.extend(segs)

        last = ar.finish_streaming()
        if last:
            all_segments.append(last)

        assert len(all_segments) >= 2
        for seg in all_segments:
            assert "**" not in seg.cleaned_text
            assert "##" not in seg.cleaned_text
            assert "[" not in seg.cleaned_text
            assert "](http" not in seg.cleaned_text

    def test_first_segment_available_quickly(self):
        """First segment should be available as soon as first sentence boundary arrives."""
        ar = AgentResponse()
        ar.start_streaming()

        segments = ar.feed_token("你好！")
        assert len(segments) == 1
        assert segments[0].cleaned_text == "你好！"

    def test_emoji_heavy_content(self):
        ar = AgentResponse()
        ar.start_streaming()

        text = "🎉 恭喜你完成了！🎊 继续加油。💪 你做得很好！"
        segs = ar.feed_token(text)
        last = ar.finish_streaming()
        if last:
            segs.append(last)

        for seg in segs:
            assert "🎉" not in seg.cleaned_text
            assert "🎊" not in seg.cleaned_text
            assert "💪" not in seg.cleaned_text

    def test_code_blocks_cleaned(self):
        ar = AgentResponse()
        ar.start_streaming()

        text = "使用```python```语言编写。代码如下："
        segs = ar.feed_token(text)
        last = ar.finish_streaming()
        if last:
            segs.append(last)

        for seg in segs:
            assert "```" not in seg.cleaned_text

    def test_tts_text_truncated_at_500(self):
        """TTS engine truncates at 500 chars; verify segments don't exceed that."""
        ar = AgentResponse()
        ar.start_streaming()

        long_text = "这是一个很长的句子" * 20 + "。"
        segs = ar.feed_token(long_text)
        last = ar.finish_streaming()
        if last:
            segs.append(last)

        for seg in segs:
            assert len(seg.cleaned_text) <= 500


@pytest.mark.asyncio
class TestTTSEngineIntegration:
    """Test that EdgeTTSEngine works with cleaned text."""

    async def test_tts_with_cleaned_text(self):
        """Edge TTS should not crash on cleaned text."""
        try:
            from engines.tts_edge import EdgeTTSEngine
        except ImportError:
            pytest.skip("edge_tts not installed")

        engine = EdgeTTSEngine()
        cleaned = clean_for_tts("**你好**世界！这是一个测试。")
        assert cleaned == "你好世界！这是一个测试。"

        audio = await engine.synthesize(cleaned)
        assert isinstance(audio, bytes)
        assert len(audio) > 0

    async def test_tts_skips_empty_cleaned(self):
        try:
            from engines.tts_edge import EdgeTTSEngine
        except ImportError:
            pytest.skip("edge_tts not installed")

        engine = EdgeTTSEngine()
        audio = await engine.synthesize("🎉🎊🎈")
        assert audio == b""
