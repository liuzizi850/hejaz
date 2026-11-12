# -*- coding: utf-8 -*-
"""AI 评测师改接 RAGFlow 的测试。"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.assistant.models import AssistantSession, ChatMessage, DifyConfig
from apps.assistant.ragflow_client import (
    RagflowError,
    chat_completion,
    fetch_chunk_image,
    is_session_error,
    normalize_base_url,
    normalize_reference,
)

User = get_user_model()


class NormalizeBaseUrlTests(TestCase):
    def test_appends_api_v1(self):
        self.assertEqual(
            normalize_base_url("http://127.0.0.1:9380/"),
            "http://127.0.0.1:9380/api/v1",
        )

    def test_keeps_existing_api_v1(self):
        self.assertEqual(
            normalize_base_url("http://127.0.0.1:9380/api/v1"),
            "http://127.0.0.1:9380/api/v1",
        )


class ChatCompletionClientTests(TestCase):
    @patch("apps.assistant.ragflow_client.requests.post")
    def test_sends_non_streaming_payload(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "code": 0,
            "data": {
                "answer": "hello",
                "session_id": "sess-1",
                "id": "msg-1",
            },
        }

        data = chat_completion(
            "http://127.0.0.1:9380",
            "ragflow-key",
            "你好",
            chat_id="chat-1",
            session_id="sess-1",
        )

        self.assertEqual(data["answer"], "hello")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:9380/api/v1/chat/completions")
        self.assertEqual(kwargs["json"]["stream"], False)
        self.assertEqual(kwargs["json"]["question"], "你好")
        self.assertEqual(kwargs["json"]["chat_id"], "chat-1")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ragflow-key")

    @patch("apps.assistant.ragflow_client.requests.post")
    def test_raises_on_ragflow_error_code(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "code": 102,
            "message": "Session does not exist",
        }
        with self.assertRaises(RagflowError) as ctx:
            chat_completion("http://127.0.0.1:9380", "key", "hi", session_id="old")
        self.assertTrue(is_session_error(ctx.exception))


class NormalizeReferenceTests(TestCase):
    def test_keeps_cited_chunk_fields(self):
        chunks = normalize_reference({
            "chunks": [{
                "content": "标准政策要求自雇人士经营至少 2 年",
                "document_name": "v1.5 Hejaz.pdf",
                "document_id": "doc-1",
                "dataset_id": "kb-1",
                "image_id": "kb-1-chunk-1",
                "positions": [[3, 10, 200, 20, 80]],
                "similarity": 0.91,
            }]
        })
        self.assertEqual(chunks, [{
            "index": 0,
            "content": "标准政策要求自雇人士经营至少 2 年",
            "document_id": "doc-1",
            "document_name": "v1.5 Hejaz.pdf",
            "dataset_id": "kb-1",
            "image_id": "kb-1-chunk-1",
            "page": 3,
        }])

    def test_drops_unsafe_image_id_and_empty_chunk(self):
        chunks = normalize_reference({
            "chunks": [
                {"content": "", "image_id": "../secret"},
                {"content": "原文段落", "img_id": "kb_1-ck_2", "positions": [0]},
            ]
        })
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["image_id"], "kb_1-ck_2")
        self.assertEqual(chunks[0]["page"], 1)
        self.assertEqual(chunks[0]["index"], 1)


class FetchChunkImageTests(TestCase):
    def test_rejects_path_outside_image_id(self):
        with self.assertRaises(RagflowError):
            fetch_chunk_image("http://127.0.0.1:9380", "key", "../secret")

    @patch("apps.assistant.ragflow_client.requests.get")
    def test_uses_legacy_image_path_when_new_path_is_not_an_image(self, mock_get):
        missing = mock_get.return_value
        missing.status_code = 404
        missing.headers = {"Content-Type": "application/json"}
        missing.content = b'{"code":102}'
        missing.url = "http://127.0.0.1:9380/api/v1/documents/images/kb1-ck1"
        legacy = type(missing)()
        legacy.status_code = 200
        legacy.headers = {"Content-Type": "application/octet-stream"}
        legacy.content = b"\xff\xd8\xff\xd9"
        legacy.url = "http://127.0.0.1:9380/v1/document/image/kb1-ck1"
        mock_get.side_effect = [missing, legacy]

        content, media_type = fetch_chunk_image("http://127.0.0.1:9380", "key", "kb1-ck1")

        self.assertEqual(content, b"\xff\xd8\xff\xd9")
        self.assertEqual(media_type, "image/jpeg")
        self.assertEqual(
            mock_get.call_args_list[1].args[0],
            "http://127.0.0.1:9380/v1/document/image/kb1-ck1",
        )


class AssistantRagflowApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reviewer", password="pass12345")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.config = DifyConfig.objects.create(
            api_url="http://127.0.0.1:9380",
            api_key="ragflow-api-key-123",
            chat_id="chat-assistant-1",
            is_active=True,
        )
        self.session = AssistantSession.objects.create(
            user=self.user,
            session_id="local-session-1",
            title="测试会话",
        )

    @patch("apps.assistant.views.chat_completion")
    def test_send_message_uses_ragflow(self, mock_complete):
        mock_complete.return_value = {
            "answer": "这是评测建议",
            "session_id": "rf-session-9",
            "id": "rf-msg-9",
        }

        response = self.client.post(
            "/api/assistant/chat/send_message/",
            {"session_id": "local-session-1", "message": "如何做接口测试？"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["assistant_message"]["content"], "这是评测建议")
        self.session.refresh_from_db()
        self.assertEqual(self.session.conversation_id, "rf-session-9")
        mock_complete.assert_called_once()
        kwargs = mock_complete.call_args.kwargs
        self.assertEqual(kwargs["question"], "如何做接口测试？")
        self.assertEqual(kwargs["chat_id"], "chat-assistant-1")
        self.assertEqual(response.data["assistant_message"]["references"], [])

    @patch("apps.assistant.views.chat_completion")
    def test_send_message_stores_knowledge_references(self, mock_complete):
        mock_complete.return_value = {
            "answer": "原则上不接受，除非满足两年经营 ##0$$",
            "session_id": "rf-session-9",
            "id": "rf-msg-9",
            "reference": {
                "chunks": [{
                    "content": "标准政策要求自雇人士在当前业务中经营至少 2 年。",
                    "document_name": "v1.5 Hejaz Auto Finance Credit Policy.pdf",
                    "document_id": "doc-1",
                    "dataset_id": "kb-1",
                    "image_id": "kb-1-chunk-1",
                    "positions": [[2, 12, 480, 40, 160]],
                }]
            },
        }

        response = self.client.post(
            "/api/assistant/chat/send_message/",
            {"session_id": "local-session-1", "message": "自雇不满两年可以申请吗？"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        stored = ChatMessage.objects.get(role="assistant")
        reference = stored.references[0]
        self.assertEqual(reference["document_name"], "v1.5 Hejaz Auto Finance Credit Policy.pdf")
        self.assertEqual(reference["content"][:8], "标准政策要求自雇")
        self.assertEqual(reference["image_id"], "kb-1-chunk-1")
        self.assertEqual(reference["page"], 2)
        self.assertEqual(response.data["assistant_message"]["references"][0]["index"], 0)

    @patch("apps.assistant.views.fetch_chunk_image", return_value=(b"\xff\xd8\xff", "image/jpeg"))
    def test_reference_image_proxies_snapshot(self, mock_fetch):
        response = self.client.get(
            "/api/assistant/chat/reference_image/",
            {"image_id": "kb-1-chunk-1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, b"\xff\xd8\xff")
        mock_fetch.assert_called_once()

    def test_reference_image_hides_invalid_id(self):
        response = self.client.get(
            "/api/assistant/chat/reference_image/",
            {"image_id": "../secret"},
        )
        self.assertEqual(response.status_code, 404)

    @patch("apps.assistant.views.chat_completion")
    def test_retries_when_old_session_is_invalid(self, mock_complete):
        self.session.conversation_id = "dify-old-id"
        self.session.save(update_fields=["conversation_id"])
        mock_complete.side_effect = [
            RagflowError("Session does not exist", detail="session missing"),
            {"answer": "新会话回复", "session_id": "rf-new", "id": "m2"},
        ]

        response = self.client.post(
            "/api/assistant/chat/send_message/",
            {"session_id": "local-session-1", "message": "hello"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["assistant_message"]["content"], "新会话回复")
        self.assertEqual(mock_complete.call_count, 2)
        self.assertIsNone(mock_complete.call_args_list[1].kwargs["session_id"])

    def test_create_session_returns_id_and_can_be_deleted(self):
        response = self.client.post(
            "/api/assistant/sessions/",
            {"session_id": "local-new", "title": "新会话"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["session_id"], "local-new")
        self.assertEqual(response.data["title"], "新会话")
        session_pk = response.data["id"]
        self.assertIsNotNone(session_pk)

        delete_response = self.client.delete(f"/api/assistant/sessions/{session_pk}/")
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(AssistantSession.objects.filter(pk=session_pk).exists())

    def test_send_message_requires_chat_id(self):
        self.config.chat_id = ""
        self.config.save(update_fields=["chat_id"])
        response = self.client.post(
            "/api/assistant/chat/send_message/",
            {"session_id": "local-session-1", "message": "hello"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Chat ID", response.data["error"])

    @patch("apps.assistant.views_config.list_chats")
    def test_connection_lists_chats(self, mock_list):
        mock_list.return_value = [{"id": "chat-assistant-1", "name": "AI评测师"}]
        response = self.client.post(
            "/api/assistant/config/dify/test_connection/",
            {
                "api_url": "http://127.0.0.1:9380",
                "api_key": "ragflow-api-key-123",
                "chat_id": "chat-assistant-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["chats"][0]["id"], "chat-assistant-1")
