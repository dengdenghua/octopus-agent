"""Unit tests for the multimodal user-message path in react_loop.

Validates that an image attachment with a data URL is folded into the
user message as an OpenAI-style `content` array, while non-image
attachments and bare text fall back to plain string content.
"""

from __future__ import annotations

from runtime.core.cerebrum.react_loop import (
    _build_user_message_content,
    _image_blocks_from_attachments,
    _looks_like_image_attachment,
)

# ── _looks_like_image_attachment ──────────────────────────


def test_looks_like_image_via_media_type() -> None:
    assert _looks_like_image_attachment({"mediaType": "image/png"})
    assert _looks_like_image_attachment({"mime_type": "image/jpeg"})
    assert _looks_like_image_attachment({"media_type": "IMAGE/WEBP"})
    assert not _looks_like_image_attachment({"mediaType": "application/pdf"})


def test_looks_like_image_via_extension() -> None:
    assert _looks_like_image_attachment({"filename": "cat.png"})
    assert _looks_like_image_attachment({"filename": "photo.JPG"})
    assert _looks_like_image_attachment({"name": "diagram.gif"})
    assert not _looks_like_image_attachment({"filename": "doc.pdf"})
    assert not _looks_like_image_attachment({"filename": "noext"})


def test_looks_like_image_falsy_input() -> None:
    assert not _looks_like_image_attachment({})
    assert not _looks_like_image_attachment({"filename": "", "mediaType": ""})


# ── _image_blocks_from_attachments ────────────────────────


def test_image_blocks_data_url_takes_priority() -> None:
    blocks, consumed = _image_blocks_from_attachments([{"data_url": "data:image/png;base64,AAA="}])
    assert consumed == {0}
    assert len(blocks) == 1
    assert blocks[0]["type"] == "image_url"
    assert blocks[0]["image_url"]["url"].startswith("data:image/")


def test_image_blocks_hosted_url_with_media_type() -> None:
    blocks, _ = _image_blocks_from_attachments(
        [{"url": "https://example.com/cat.png", "mediaType": "image/png"}]
    )
    assert len(blocks) == 1
    assert blocks[0]["image_url"]["url"] == "https://example.com/cat.png"


def test_image_blocks_filters_non_image() -> None:
    blocks, consumed = _image_blocks_from_attachments(
        [
            {"url": "https://example.com/doc.pdf", "mediaType": "application/pdf"},
            {"data_url": "data:image/png;base64,AAA="},
        ]
    )
    assert consumed == {1}
    assert len(blocks) == 1


def test_image_blocks_handles_invalid_input() -> None:
    assert _image_blocks_from_attachments(None) == ([], set())
    assert _image_blocks_from_attachments([]) == ([], set())
    assert _image_blocks_from_attachments("not a list") == ([], set())
    assert _image_blocks_from_attachments([None, "string", 42]) == ([], set())


def test_image_blocks_skips_attachment_without_url() -> None:
    blocks, consumed = _image_blocks_from_attachments(
        [
            {"filename": "cat.png", "mediaType": "image/png"}  # no url
        ]
    )
    assert blocks == []
    assert consumed == set()


# ── _build_user_message_content ───────────────────────────


def test_build_content_plain_text_when_no_attachments() -> None:
    assert _build_user_message_content("hello world", []) == "hello world"
    assert _build_user_message_content("hi", None) == "hi"


def test_build_content_strips_text() -> None:
    assert _build_user_message_content("  hi  ", []) == "hi"


def test_build_content_returns_array_with_image() -> None:
    result = _build_user_message_content(
        "describe this",
        [{"data_url": "data:image/png;base64,AAA="}],
    )
    assert isinstance(result, list)
    assert result[0] == {"type": "text", "text": "describe this"}
    assert result[1]["type"] == "image_url"


def test_build_content_image_only_no_text() -> None:
    """Empty text + image → content array with just the image block."""
    result = _build_user_message_content(
        "",
        [{"data_url": "data:image/png;base64,AAA="}],
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "image_url"


def test_build_content_non_image_includes_readable_file_manifest() -> None:
    """Non-image attachments stay text-shaped but expose their real path."""
    result = _build_user_message_content(
        "hello",
        [
            {
                "filename": "doc.pdf",
                "path": "/tmp/thread/upload/doc.pdf",
                "artifact_url": "/api/threads/t/artifacts/doc.pdf",
                "mediaType": "application/pdf",
            }
        ],
    )
    assert isinstance(result, str)
    assert result.startswith("hello\n\n<attached_files")
    assert '"filename": "doc.pdf"' in result
    assert '"path": "/tmp/thread/upload/doc.pdf"' in result
    assert "Use the path field with read_file" in result


def test_build_content_document_preview_is_bounded_and_marked_untrusted() -> None:
    result = _build_user_message_content(
        "summarize",
        [
            {
                "filename": "deck.pptx",
                "path": "/tmp/deck.pptx",
                "extracted_text": "x" * 10_000,
            }
        ],
    )
    assert isinstance(result, str)
    assert 'trust="untrusted"' in result
    assert '"preview_truncated": true' in result
    assert len(result) < 5_000


def test_build_content_filename_only_attachment_is_still_visible() -> None:
    result = _build_user_message_content(
        "inspect",
        [{"filename": "legacy.docx", "mediaType": "application/octet-stream"}],
    )
    assert isinstance(result, str)
    assert '"filename": "legacy.docx"' in result


def test_build_content_multiple_images() -> None:
    result = _build_user_message_content(
        "compare",
        [
            {"data_url": "data:image/png;base64,AAA="},
            {"data_url": "data:image/jpeg;base64,BBB="},
        ],
    )
    assert isinstance(result, list)
    image_blocks = [b for b in result if b.get("type") == "image_url"]
    assert len(image_blocks) == 2


# ── router delivery · the picture must survive translation ─
#
# The whole upload chain worked and the model still said "I don't see any
# image": ``_messages_to_openai`` matched no branch for an ``image_url``
# block and dropped it, and the Gemini translator did the same. Assembly
# building the block correctly is not enough — assert the provider payload.


def test_openai_translation_keeps_uploaded_image() -> None:
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.openai_router import _messages_to_openai

    out = _messages_to_openai(
        [
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "describe this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAA="},
                    },
                ],
            )
        ]
    )
    assert len(out) == 1
    blocks = out[0]["content"]
    assert isinstance(blocks, list), "collapsing to a string loses the image"
    assert [b["type"] for b in blocks] == ["text", "image_url"]
    assert blocks[1]["image_url"]["url"] == "data:image/png;base64,AAA="


def test_openai_translation_accepts_anthropic_shaped_image() -> None:
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.openai_router import _messages_to_openai

    out = _messages_to_openai(
        [
            Message(
                role="user",
                content=[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": "BBB",
                        },
                    }
                ],
            )
        ]
    )
    assert out[0]["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,BBB"


def test_openai_translation_still_splits_tool_results() -> None:
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.openai_router import _messages_to_openai

    out = _messages_to_openai(
        [
            Message(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                    {"type": "text", "text": "next"},
                ],
            )
        ]
    )
    assert out == [
        {"role": "tool", "tool_call_id": "t1", "content": "ok"},
        {"role": "user", "content": "next"},
    ]


def test_openai_screenshot_appends_to_upload_bearing_message() -> None:
    """A computer-use screenshot must not stringify away a user's upload."""
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.openai_router import (
        _attach_images_to_last_user_openai,
        _messages_to_openai,
    )

    msgs = _messages_to_openai(
        [
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "look"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,UPLOAD"},
                    },
                ],
            )
        ]
    )
    _attach_images_to_last_user_openai(msgs, ["SHOT"])
    urls = [b["image_url"]["url"] for b in msgs[-1]["content"] if b["type"] == "image_url"]
    assert urls == ["data:image/png;base64,UPLOAD", "data:image/png;base64,SHOT"]


def test_gemini_translation_keeps_uploaded_image() -> None:
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.gemini_router import _split_system_and_contents

    _, contents = _split_system_and_contents(
        [
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "describe this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAA="},
                    },
                ],
            )
        ]
    )
    parts = contents[0]["parts"]
    assert parts[0] == {"text": "describe this"}
    assert parts[1]["inlineData"] == {"mimeType": "image/png", "data": "AAA="}


def test_gemini_translation_uses_file_data_for_remote_url() -> None:
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.gemini_router import _split_system_and_contents

    _, contents = _split_system_and_contents(
        [
            Message(
                role="user",
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/cat.png"},
                    }
                ],
            )
        ]
    )
    assert contents[0]["parts"][0]["fileData"]["fileUri"] == "https://example.com/cat.png"


# ── hosted-only uploads must not vanish from both channels ─


def test_relative_artifact_url_is_not_sent_as_image_url() -> None:
    """A server-relative artifact path is unfetchable by any provider."""
    blocks, consumed = _image_blocks_from_attachments(
        [
            {
                "filename": "shot.png",
                "mediaType": "image/png",
                "artifact_url": "/api/threads/T1/artifacts/shot.png",
            }
        ]
    )
    assert blocks == []
    assert consumed == set()


def test_hosted_only_image_falls_back_to_readable_manifest() -> None:
    """No inline image → the model still learns the file exists on disk."""
    result = _build_user_message_content(
        "what is in this picture",
        [
            {
                "filename": "shot.png",
                "mediaType": "image/png",
                "path": "/data/workspaces/T1/upload/shot.png",
                "artifact_url": "/api/threads/T1/artifacts/shot.png",
            }
        ],
    )
    assert isinstance(result, str), "no usable image URL → stays text-shaped"
    assert "shot.png" in result
    assert "/data/workspaces/T1/upload/shot.png" in result


def test_inline_image_is_not_duplicated_into_the_manifest() -> None:
    """An attachment delivered as a picture must not also be listed as a file."""
    result = _build_user_message_content(
        "describe",
        [
            {
                "filename": "shot.png",
                "mediaType": "image/png",
                "data_url": "data:image/png;base64,AAA=",
                "path": "/data/workspaces/T1/upload/shot.png",
            }
        ],
    )
    assert isinstance(result, list)
    assert [b["type"] for b in result] == ["text", "image_url"]
    assert result[0]["text"] == "describe"
