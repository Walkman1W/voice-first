"""Tests for AgentResponse: text cleaning, segmentation, and TTS pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from agent_response import AgentResponse, AudioSegment, PlaybackCommand, clean_for_tts


class TestCleanForTTS:
    def test_removes_bold_markdown(self):
        assert clean_for_tts("这是**加粗**文本") == "这是加粗文本"

    def test_removes_double_asterisks(self):
        assert clean_for_tts("**标题内容**") == "标题内容"

    def test_removes_heading_markers(self):
        assert clean_for_tts("## 二级标题") == "二级标题"
        assert clean_for_tts("### 三级标题") == "三级标题"

    def test_removes_emoji(self):
        assert clean_for_tts("你好😊世界🌍") == "你好世界"
        assert clean_for_tts("🎉 恭喜完成") == "恭喜完成"

    def test_removes_code_backticks(self):
        assert clean_for_tts("使用`print()`函数") == "使用print()函数"

    def test_removes_bullet_markers(self):
        assert clean_for_tts("- 第一项") == "第一项"
        assert clean_for_tts("* 第二项") == "第二项"

    def test_removes_numbered_list(self):
        # Numbered lists should be PRESERVED for TTS to read as sequence
        assert clean_for_tts("1. 第一步") == "1. 第一步"
        assert clean_for_tts("3、第三步") == "3、第三步"

    def test_extracts_link_text(self):
        assert clean_for_tts("点击[这里](http://example.com)查看") == "点击这里查看"

    def test_empty_after_cleaning(self):
        assert clean_for_tts("**") == ""
        assert clean_for_tts("🎉🎊🎈") == ""
        assert clean_for_tts("  ") == ""

    def test_preserves_normal_text(self):
        assert clean_for_tts("今天天气真好") == "今天天气真好"

    def test_mixed_content(self):
        text = "## 总结\n\n**重点**是：要保持😊积极的态度！"
        result = clean_for_tts(text)
        assert "##" not in result
        assert "**" not in result
        assert "😊" not in result
        assert "重点" in result
        assert "积极的态度" in result

    def test_strikethrough(self):
        assert clean_for_tts("~~删除线~~文本") == "删除线文本"


class TestAgentResponseStreaming:
    def test_start_streaming_sets_metadata(self):
        ar = AgentResponse()
        ar.start_streaming(agent_name="test-agent")
        assert ar.agent_name == "test-agent"
        assert ar.is_streaming is True
        assert ar.is_complete is False
        assert ar.created_at > 0

    def test_feed_token_produces_segments(self):
        ar = AgentResponse()
        ar.start_streaming()
        segments = ar.feed_token("你好世界。这是一个测试。")
        assert len(segments) == 2
        assert segments[0].cleaned_text == "你好世界。"
        assert segments[1].cleaned_text == "这是一个测试。"

    def test_feed_token_cleans_markdown(self):
        ar = AgentResponse()
        ar.start_streaming()
        segments = ar.feed_token("**你好**世界。")
        assert len(segments) == 1
        assert segments[0].cleaned_text == "你好世界。"
        assert "**" not in segments[0].cleaned_text

    def test_feed_token_cleans_emoji(self):
        ar = AgentResponse()
        ar.start_streaming()
        segments = ar.feed_token("恭喜🎉完成！")
        assert len(segments) == 1
        assert "🎉" not in segments[0].cleaned_text

    def test_feed_token_skips_empty_segments(self):
        ar = AgentResponse()
        ar.start_streaming()
        segments = ar.feed_token("🎉🎊。正常文本。")
        cleaned_texts = [s.cleaned_text for s in segments]
        assert all("🎉" not in t for t in cleaned_texts)
        assert any("正常文本" in t for t in cleaned_texts)

    def test_finish_streaming_flushes_buffer(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("这段文字没有标点")
        last = ar.finish_streaming()
        assert last is not None
        assert last.cleaned_text == "这段文字没有标点"
        assert ar.is_streaming is False
        assert ar.is_complete is True

    def test_finish_streaming_returns_none_if_empty(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("已结束。")
        last = ar.finish_streaming()
        assert last is None

    def test_full_streaming_flow(self):
        ar = AgentResponse()
        ar.start_streaming(agent_name="openclaw")

        tokens = ["你好", "！我是", "小龙虾", "。很高兴", "认识你", "。"]
        all_segments = []
        for token in tokens:
            segs = ar.feed_token(token)
            all_segments.extend(segs)

        last = ar.finish_streaming()
        if last:
            all_segments.append(last)

        assert len(all_segments) >= 2
        assert ar.full_text == "你好！我是小龙虾。很高兴认识你。"
        assert ar.is_complete is True

    def test_incremental_token_streaming(self):
        """Simulate realistic LLM token-by-token output."""
        ar = AgentResponse()
        ar.start_streaming()

        tokens = ["好", "的", "，", "我", "来", "帮", "你", "查", "一", "下", "。",
                  "结", "果", "如", "下", "："]
        all_segs = []
        for t in tokens:
            segs = ar.feed_token(t)
            all_segs.extend(segs)

        last = ar.finish_streaming()
        if last:
            all_segs.append(last)

        full = "".join(s.cleaned_text for s in all_segs)
        assert "好" in full
        assert "查一下" in full


class TestAgentResponsePlayback:
    def test_mark_segment_ready(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("第一句。第二句。")
        ar.mark_segment_ready(0, "base64data", "mp3")
        assert ar.segments[0].is_ready is True
        assert ar.segments[0].audio_b64 == "base64data"

    def test_playback_commands(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("一。二。三。")
        ar.finish_streaming()

        ar.is_playing = True
        result = ar.execute_command(PlaybackCommand.NEXT)
        assert result == {"action": "play_segment", "index": 1}
        assert ar.current_index == 1

        result = ar.execute_command(PlaybackCommand.PREV)
        assert result == {"action": "play_segment", "index": 0}
        assert ar.current_index == 0

        result = ar.execute_command(PlaybackCommand.PAUSE)
        assert result == {"action": "pause"}
        assert ar.is_paused is True

    def test_to_status(self):
        ar = AgentResponse()
        ar.start_streaming(agent_name="my-agent")
        ar.feed_token("你好世界。")
        status = ar.to_status()
        assert status["agent_name"] == "my-agent"
        assert status["is_streaming"] is True
        assert status["total_segments"] == 1

    def test_reset(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("内容。")
        ar.reset()
        assert ar.full_text == ""
        assert ar.segments == []
        assert ar.is_streaming is False


class TestCleanForTTSEdgeCases:
    def test_heading_at_line_start_only(self):
        assert clean_for_tts("# 标题") == "标题"
        assert clean_for_tts("这不是#标签") == "这不是#标签"

    def test_multiple_markdown_in_one_segment(self):
        text = "**加粗**和*斜体*混合"
        result = clean_for_tts(text)
        assert "**" not in result
        assert "*" not in result
        assert "加粗" in result
        assert "斜体" in result

    def test_triple_backtick(self):
        assert clean_for_tts("```代码块```内容") == "代码块内容"

    def test_multiline_with_headings_and_bullets(self):
        text = "## 步骤\n- 第一步\n- 第二步"
        result = clean_for_tts(text)
        assert "##" not in result
        assert "-" not in result or "第一步" in result
        assert "第一步" in result
        assert "第二步" in result


class TestSegmentSeqOrder:
    """Test that segments have correct seq numbers for ordered playback."""

    def test_segments_have_sequential_seq(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("第一句。第二句。第三句。")
        last = ar.finish_streaming()
        if last:
            pass
        for i, seg in enumerate(ar.segments):
            assert seg.seq == i, f"Segment {i} has seq={seg.seq}"

    def test_seq_preserved_after_empty_cleaned_skip(self):
        """If a segment is skipped (empty after cleaning), seq stays sequential."""
        ar = AgentResponse()
        ar.start_streaming()
        # First produces real content, second is emoji-only (skipped), third is real
        segs = ar.feed_token("正常内容。🎉🎊🎈。又一段正常内容。")
        last = ar.finish_streaming()
        if last:
            segs.append(last)

        # Verify all produced segments have contiguous seq numbers
        for i, seg in enumerate(ar.segments):
            assert seg.seq == i

    def test_numbered_list_preserved_in_tts(self):
        ar = AgentResponse()
        ar.start_streaming()
        segs = ar.feed_token("1. 打开设置。2. 找到选项。3. 点击确认。")
        last = ar.finish_streaming()
        if last:
            segs.append(last)

        texts = [s.cleaned_text for s in ar.segments]
        assert any("1." in t for t in texts)
        assert any("2." in t for t in texts)
        assert any("3." in t for t in texts)


@pytest.mark.asyncio
class TestOrderedPlayback:
    """Test that wait_for_next_ready delivers segments in seq order."""

    async def test_out_of_order_ready_still_delivers_in_order(self):
        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("第一。第二。第三。")
        ar.finish_streaming()
        ar.notify_streaming_done()

        # Mark segments ready out of order: 2, 0, 1
        ar.mark_segment_ready(2, "audio_2", "mp3")
        ar.mark_segment_ready(0, "audio_0", "mp3")
        ar.mark_segment_ready(1, "audio_1", "mp3")

        received = []
        while True:
            seg = await ar.wait_for_next_ready()
            if seg is None:
                break
            received.append(seg.seq)

        assert received == [0, 1, 2]

    async def test_delayed_ready_blocks_until_available(self):
        import asyncio

        ar = AgentResponse()
        ar.start_streaming()
        ar.feed_token("第一。第二。")
        ar.finish_streaming()
        ar.notify_streaming_done()

        received = []

        async def sender():
            while True:
                seg = await ar.wait_for_next_ready()
                if seg is None:
                    break
                received.append(seg.seq)

        sender_task = asyncio.create_task(sender())

        # Seg 1 ready first (out of order)
        ar.mark_segment_ready(1, "audio_1", "mp3")
        await asyncio.sleep(0.01)
        # Sender should NOT have sent anything yet (waiting for seq 0)
        assert received == []

        # Now mark seg 0 ready
        ar.mark_segment_ready(0, "audio_0", "mp3")
        await asyncio.sleep(0.01)
        # Both should be delivered in order
        assert received == [0, 1]

        await sender_task
