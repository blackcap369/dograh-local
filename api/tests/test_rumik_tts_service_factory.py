from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pipecat.transcriptions.language import Language

from api.services.configuration.registry import (
    RUMIK_TTS_MODELS,
    ServiceProviders,
    RumikTTSConfiguration,
)
from api.services.pipecat.service_factory import create_tts_service


def test_rumik_tts_configuration_defaults():
    config = RumikTTSConfiguration(api_key="test-key", base_url="wss://gateway.rumik.ai/v1/tts/stream")

    assert config.provider == ServiceProviders.RUMIK
    assert config.model == "muga"
    assert config.voice is None
    assert config.language is None
    assert RUMIK_TTS_MODELS == ["muga", "mulberry"]


def test_create_rumik_tts_service_uses_websocket_streaming():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.RUMIK.value,
            api_key="test-key",
            model="muga",
            voice="speaker_1",
            language="en",
            base_url="wss://gateway.rumik.ai/v1/tts/stream",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=24000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.RumikTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    assert mock_service.call_count == 1
    kwargs = mock_service.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["gateway_url"] == "wss://gateway.rumik.ai/v1/tts/stream"
    assert kwargs["settings"].model == "muga"
    assert kwargs["settings"].voice == "speaker_1"


def test_create_rumik_tts_service_requires_gateway_url():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.RUMIK.value,
            api_key="test-key",
            model="muga",
            voice=None,
            language=None,
            base_url=None,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=24000,
        transport_in_sample_rate=16000,
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        create_tts_service(user_config, audio_config)
    assert exc_info.value.status_code == 400
    assert "base_url" in exc_info.value.detail.lower() or "gateway" in exc_info.value.detail.lower()


def test_create_rumik_tts_service_with_mulberry_model():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.RUMIK.value,
            api_key="test-key",
            model="mulberry",
            voice="speaker_2",
            language="en",
            base_url="wss://gateway.rumik.ai/v1/tts/stream",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=24000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.RumikTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].model == "mulberry"
    assert kwargs["settings"].voice == "speaker_2"
