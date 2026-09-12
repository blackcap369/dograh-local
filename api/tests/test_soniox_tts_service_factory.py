from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pipecat.transcriptions.language import Language

from api.services.configuration.registry import (
    ServiceProviders,
    SonioxTTSConfiguration,
)
from api.services.pipecat.service_factory import create_tts_service


def test_soniox_tts_configuration_defaults():
    config = SonioxTTSConfiguration(api_key="test-key")

    assert config.provider == ServiceProviders.SONIOX
    assert config.model == "tts-rt-v2"
    assert config.voice == "Bryce"
    assert config.language == "en"
    assert config.speed is None


def test_create_soniox_tts_service_uses_websocket_streaming():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.SONIOX.value,
            api_key="test-key",
            model="tts-rt-v2",
            voice="Adrian",
            language="en",
            speed=None,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.SonioxTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    assert mock_service.call_count == 1
    kwargs = mock_service.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["settings"].model == "tts-rt-v2"
    assert kwargs["settings"].voice == "Adrian"
    assert kwargs["settings"].language == Language.EN


def test_create_soniox_tts_service_converts_language():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.SONIOX.value,
            api_key="test-key",
            model="tts-rt-v2",
            voice="Bryce",
            language="fr",
            speed=None,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.SonioxTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].language == Language.FR


def test_create_soniox_tts_service_falls_back_to_english_for_unknown_language():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.SONIOX.value,
            api_key="test-key",
            model="tts-rt-v2",
            voice="Bryce",
            language="not-a-language",
            speed=None,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.SonioxTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].language == Language.EN


def test_create_soniox_tts_service_with_speed():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.SONIOX.value,
            api_key="test-key",
            model="tts-rt-v2",
            voice="Bryce",
            language="en",
            speed=1.2,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.SonioxTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    kwargs = mock_service.call_args.kwargs
    assert kwargs["settings"].speed == 1.2
