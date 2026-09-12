from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pipecat.transcriptions.language import Language

from api.services.configuration.registry import (
    FISHAUDIO_TTS_MODELS,
    ServiceProviders,
    FishAudioTTSConfiguration,
)
from api.services.pipecat.service_factory import create_tts_service


def test_fishaudio_tts_configuration_defaults():
    config = FishAudioTTSConfiguration(api_key="test-key")

    assert config.provider == ServiceProviders.FISHAUDIO
    assert config.model == "s2.1-pro"
    assert config.voice is None
    assert config.language is None
    assert config.latency == "balanced"
    assert FISHAUDIO_TTS_MODELS == ["s2.1-pro", "s2-pro", "s1"]


def test_create_fishaudio_tts_service_uses_websocket_streaming():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.FISHAUDIO.value,
            api_key="test-key",
            model="s2.1-pro",
            voice="voice-id-123",
            language="en",
            latency="balanced",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.FishAudioTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    assert mock_service.call_count == 1
    kwargs = mock_service.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["output_format"] == "pcm"
    assert kwargs["settings"].model == "s2.1-pro"
    assert kwargs["settings"].voice == "voice-id-123"
    assert kwargs["settings"].latency == "balanced"


def test_create_fishaudio_tts_service_with_normal_latency():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.FISHAUDIO.value,
            api_key="test-key",
            model="s2-pro",
            voice=None,
            language=None,
            latency="normal",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.FishAudioTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].model == "s2-pro"
    assert kwargs["settings"].latency == "normal"
    assert kwargs["settings"].voice is None


def test_create_fishaudio_tts_service_defaults_to_balanced_latency():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.FISHAUDIO.value,
            api_key="test-key",
            model="s2.1-pro",
            voice=None,
            language=None,
            latency=None,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.FishAudioTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].latency == "balanced"


def test_create_fishaudio_tts_service_with_language():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.FISHAUDIO.value,
            api_key="test-key",
            model="s2.1-pro",
            voice="voice-id-123",
            language="es",
            latency="balanced",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.FishAudioTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].language == "es"
