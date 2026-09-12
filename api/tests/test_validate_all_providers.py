"""Quick validation test for all 3 new TTS providers."""
from types import SimpleNamespace
from unittest.mock import patch

from api.services.configuration.registry import (
    ServiceProviders,
    RumikTTSConfiguration,
    SonioxTTSConfiguration,
    FishAudioTTSConfiguration,
    RUMIK_TTS_MODELS,
    FISHAUDIO_TTS_MODELS,
)
from api.services.pipecat.service_factory import create_tts_service


def test_rumik_config_defaults():
    r = RumikTTSConfiguration(api_key="test", base_url="wss://gateway.rumik.ai")
    assert r.provider == ServiceProviders.RUMIK
    assert r.model == "muga"
    assert r.voice is None
    assert r.base_url == "wss://gateway.rumik.ai"
    assert RUMIK_TTS_MODELS == ["muga", "mulberry"]


def test_soniox_config_defaults():
    s = SonioxTTSConfiguration(api_key="test")
    assert s.provider == ServiceProviders.SONIOX
    assert s.model == "tts-rt-v2"
    assert s.voice == "Bryce"
    assert s.language == "en"
    assert s.speed is None


def test_fishaudio_config_defaults():
    f = FishAudioTTSConfiguration(api_key="test")
    assert f.provider == ServiceProviders.FISHAUDIO
    assert f.model == "s2.1-pro"
    assert f.voice is None
    assert f.language is None
    assert f.latency == "balanced"
    assert FISHAUDIO_TTS_MODELS == ["s2.1-pro", "s2-pro", "s1"]


def test_fishaudio_factory():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.FISHAUDIO.value,
            api_key="test-key",
            model="s2.1-pro",
            voice="test-voice",
            language="es",
            latency="normal",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )
    with patch("api.services.pipecat.service_factory.FishAudioTTSService") as mock:
        create_tts_service(user_config, audio_config)
        kwargs = mock.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["settings"].model == "s2.1-pro"
        assert kwargs["settings"].voice == "test-voice"
        assert kwargs["settings"].language == "es"
        assert kwargs["settings"].latency == "normal"


def test_soniox_factory():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.SONIOX.value,
            api_key="test-key",
            model="tts-rt-v2",
            voice="Adrian",
            language="fr",
            speed=1.2,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=16000,
        transport_in_sample_rate=16000,
    )
    with patch("api.services.pipecat.service_factory.SonioxTTSService") as mock:
        create_tts_service(user_config, audio_config)
        kwargs = mock.call_args.kwargs
        assert kwargs["api_key"] == "test-key"
        assert kwargs["settings"].model == "tts-rt-v2"
        assert kwargs["settings"].voice == "Adrian"
        assert kwargs["settings"].speed == 1.2


def test_rumik_guard_when_package_missing():
    """When pipecat-rumik is not installed, RumikTTSService is None -> informative error."""
    import api.services.pipecat.service_factory as sf

    original = sf.RumikTTSService
    try:
        sf.RumikTTSService = None
        user_config = SimpleNamespace(
            tts=SimpleNamespace(
                provider=ServiceProviders.RUMIK.value,
                api_key="test-key",
                voice="test",
                model="muga",
                language=None,
                base_url="wss://gateway.rumik.ai",
            )
        )
        audio_config = SimpleNamespace(
            transport_out_sample_rate=16000,
            transport_in_sample_rate=16000,
        )
        try:
            create_tts_service(user_config, audio_config)
            assert False, "Should have raised HTTPException"
        except Exception as e:
            assert "pipecat-rumik package" in str(e)
    finally:
        sf.RumikTTSService = original
