"""Offline regression tests for Copilot model discovery compatibility."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx
from copilot import CopilotClient, ModelBilling, ModelInfo
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    SessionIdleData,
)

from server.handlers import handle_chat_completion, handle_chat_completion_stream, handle_models
from server.main import app
from server.models import ChatCompletionRequest


class FakeModelsClient:
    async def list_models(self):
        return [SimpleNamespace(id="copilot-confirmed-model")]


class FakeModelListTransport:
    def __init__(self, models):
        self.models = models

    async def request(self, method, params):
        if method != "models.list":
            raise AssertionError(f"Unexpected SDK request: {method}")
        return {"models": self.models}


class FakeSession:
    def on(self, callback):
        self.callback = callback
        return lambda: None

    async def send(self, prompt, **kwargs):
        self.callback(
            SimpleNamespace(
                data=AssistantMessageData(
                    content="Hello",
                    message_id="message-1",
                ),
            )
        )
        self.callback(
            SimpleNamespace(data=SessionIdleData())
        )

    async def disconnect(self):
        return None


class CompletionClientWithoutModels:
    async def list_models(self):
        raise AssertionError("Chat completions must not list models")

    async def create_session(self, **kwargs):
        return FakeSession()


class StreamingSession(FakeSession):
    async def send(self, prompt, **kwargs):
        self.callback(
            SimpleNamespace(
                data=AssistantMessageDeltaData(
                    delta_content="Hello",
                    message_id="message-1",
                ),
            )
        )
        self.callback(SimpleNamespace(data=SessionIdleData()))


class StreamingCompletionClient(CompletionClientWithoutModels):
    async def create_session(self, **kwargs):
        return StreamingSession()


class ModelCompatibilityTests(IsolatedAsyncioTestCase):
    def test_missing_multiplier_is_optional_billing(self):
        raw_model = {
            "id": "copilot-confirmed-model",
            "name": "Copilot Confirmed Model",
            "capabilities": {
                "supports": {"vision": False},
                "limits": {},
            },
            "billing": {"tokenPrices": {"input": 1}},
        }

        model = ModelInfo.from_dict(raw_model)

        self.assertIsNotNone(model.billing)
        self.assertIsNone(model.billing.multiplier)

    def test_normal_multiplier_still_uses_sdk_parser(self):
        billing = ModelBilling.from_dict({"multiplier": 1.5})

        self.assertIsNotNone(billing)
        self.assertEqual(billing.multiplier, 1.5)

    async def test_sdk_lists_models_without_multiplier(self):
        raw_model = {
            "id": "copilot-confirmed-model",
            "name": "Copilot Confirmed Model",
            "capabilities": {
                "supports": {"vision": False},
                "limits": {},
            },
            "billing": {"tokenPrices": {"input": 1}},
        }
        client = CopilotClient()
        client._client = FakeModelListTransport([raw_model])

        models = await client.list_models()

        self.assertEqual([model.id for model in models], ["copilot-confirmed-model"])
        self.assertIsNotNone(models[0].billing)
        self.assertIsNone(models[0].billing.multiplier)

    async def test_models_handler_returns_openai_model_ids(self):
        response = await handle_models(FakeModelsClient())

        self.assertEqual(response.object, "list")
        self.assertEqual(response.data[0].id, "copilot-confirmed-model")
        self.assertEqual(response.data[0].owned_by, "github-copilot")

    async def test_models_endpoint_returns_openai_response(self):
        with patch("server.main.get_client", AsyncMock(return_value=FakeModelsClient())):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.get(
                    "/v1/models",
                    headers={"Authorization": "Bearer test-token"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "object": "list",
                "data": [
                    {
                        "id": "copilot-confirmed-model",
                        "object": "model",
                        "created": response.json()["data"][0]["created"],
                        "owned_by": "github-copilot",
                    }
                ],
            },
        )

    async def test_chat_completion_does_not_depend_on_model_listing(self):
        response = await handle_chat_completion(
            CompletionClientWithoutModels(),
            ChatCompletionRequest(
                model="copilot-confirmed-model",
                messages=[{"role": "user", "content": "Say hello"}],
            ),
        )

        self.assertEqual(response.choices[0].message.content, "Hello")
        self.assertEqual(response.model, "copilot-confirmed-model")

    async def test_streaming_completion_handles_typed_sdk_events(self):
        chunks = [
            chunk
            async for chunk in handle_chat_completion_stream(
                StreamingCompletionClient(),
                ChatCompletionRequest(
                    model="copilot-confirmed-model",
                    messages=[{"role": "user", "content": "Say hello"}],
                ),
            )
        ]

        self.assertTrue(any('"content":"Hello"' in chunk for chunk in chunks))
        self.assertEqual(chunks[-1], "data: [DONE]\n\n")