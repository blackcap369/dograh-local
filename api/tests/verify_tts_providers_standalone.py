"""Standalone verification for Rumik AI, Soniox, and Fish Audio TTS providers.

This bypasses the broken pipecat.utils.run_context import chain to verify
our specific code changes are correct.

Run: python api/tests/verify_tts_providers_standalone.py
"""
import sys
import os
import ast

# Set minimal env vars so constants.py doesn't crash
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "testtest")
os.environ.setdefault("MPS_API_URL", "http://localhost:8080")

passed = 0
failed = 0
errors = []


def check(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  OK  {name}")
    except Exception as e:
        failed += 1
        errors.append((name, e))
        print(f"  FAIL {name}: {e}")


print("=" * 60)
print("TTS Provider Standalone Verification")
print("=" * 60)

# ── 1. Syntax validation ──────────────────────────────────────────
print("\n[1] Syntax validation of modified files")

for filepath in [
    "api/services/configuration/registry.py",
    "api/services/pipecat/service_factory.py",
]:
    def _syntax(path=filepath):
        with open(path, "r", encoding="utf-8") as f:
            ast.parse(f.read(), filename=path)

    check(f"ast.parse({os.path.basename(filepath)})", _syntax)

# ── 2. Registry imports ────────────────────────────────────────────
print("\n[2] Registry imports and config validation")

def _test_imports():
    from api.services.configuration.registry import (
        ServiceProviders,
        RumikTTSConfiguration,
        SonioxTTSConfiguration,
        FishAudioTTSConfiguration,
        RUMIK_TTS_MODELS,
        FISHAUDIO_TTS_MODELS,
    )
    # Verify enum values
    assert ServiceProviders.RUMIK.value == "rumik"
    assert ServiceProviders.SONIOX.value == "soniox"
    assert ServiceProviders.FISHAUDIO.value == "fishaudio"
    # Verify model lists
    assert "muga" in RUMIK_TTS_MODELS
    assert "mulberry" in RUMIK_TTS_MODELS
    assert "s2.1-pro" in FISHAUDIO_TTS_MODELS

check("import enum values + model lists", _test_imports)

def _test_rumik_defaults():
    from api.services.configuration.registry import (
        ServiceProviders, RumikTTSConfiguration, RUMIK_TTS_MODELS,
    )
    r = RumikTTSConfiguration(api_key="test", base_url="wss://gateway.rumik.ai")
    assert r.provider == ServiceProviders.RUMIK
    assert r.model == "muga"
    assert r.voice is None
    assert r.base_url == "wss://gateway.rumik.ai"
    assert r.language is None

check("RumikTTSConfiguration defaults", _test_rumik_defaults)

def _test_rumik_custom():
    from api.services.configuration.registry import RumikTTSConfiguration
    r = RumikTTSConfiguration(
        api_key="sk-123",
        base_url="wss://custom.rumik.ai",
        model="mulberry",
        voice="speaker_5",
        language="es",
    )
    assert r.model == "mulberry"
    assert r.voice == "speaker_5"
    assert r.language == "es"

check("RumikTTSConfiguration custom fields", _test_rumik_custom)

def _test_soniox_defaults():
    from api.services.configuration.registry import (
        ServiceProviders, SonioxTTSConfiguration,
    )
    s = SonioxTTSConfiguration(api_key="test")
    assert s.provider == ServiceProviders.SONIOX
    assert s.model == "tts-rt-v2"
    assert s.voice == "Bryce"
    assert s.language == "en"
    assert s.speed is None

check("SonioxTTSConfiguration defaults", _test_soniox_defaults)

def _test_soniox_custom():
    from api.services.configuration.registry import SonioxTTSConfiguration
    s = SonioxTTSConfiguration(
        api_key="sk-456",
        voice="Adrian",
        language="fr",
        speed=1.2,
    )
    assert s.voice == "Adrian"
    assert s.language == "fr"
    assert s.speed == 1.2

check("SonioxTTSConfiguration custom fields", _test_soniox_custom)

def _test_soniox_speed_validation():
    from api.services.configuration.registry import SonioxTTSConfiguration
    from pydantic import ValidationError
    try:
        SonioxTTSConfiguration(api_key="test", speed=2.0)
        raise AssertionError("Should have rejected speed=2.0")
    except ValidationError:
        pass  # expected

check("SonioxTTSConfiguration speed validation (reject >1.3)", _test_soniox_speed_validation)

def _test_fishaudio_defaults():
    from api.services.configuration.registry import (
        ServiceProviders, FishAudioTTSConfiguration, FISHAUDIO_TTS_MODELS,
    )
    f = FishAudioTTSConfiguration(api_key="test")
    assert f.provider == ServiceProviders.FISHAUDIO
    assert f.model == "s2.1-pro"
    assert f.voice is None
    assert f.language is None
    assert f.latency == "balanced"
    assert FISHAUDIO_TTS_MODELS == ["s2.1-pro", "s2-pro", "s1"]

check("FishAudioTTSConfiguration defaults", _test_fishaudio_defaults)

def _test_fishaudio_custom():
    from api.services.configuration.registry import FishAudioTTSConfiguration
    f = FishAudioTTSConfiguration(
        api_key="sk-789",
        model="s2-pro",
        voice="voice-abc",
        language="de",
        latency="normal",
    )
    assert f.model == "s2-pro"
    assert f.voice == "voice-abc"
    assert f.language == "de"
    assert f.latency == "normal"

check("FishAudioTTSConfiguration custom fields", _test_fishaudio_custom)

# ── 3. Provider registration ───────────────────────────────────────
print("\n[3] Provider registration in registry")

def _test_registry_has_providers():
    from api.services.configuration.registry import REGISTRY, ServiceProviders
    tts = REGISTRY[ServiceProviders.TTS if hasattr(ServiceProviders, 'TTS') else None]
    # Access ServiceType through the registry dict keys
    from api.services.configuration.registry import ServiceType
    tts_registry = REGISTRY[ServiceType.TTS]
    assert ServiceProviders.RUMIK.value in tts_registry
    assert ServiceProviders.SONIOX.value in tts_registry
    assert ServiceProviders.FISHAUDIO.value in tts_registry

check("All 3 providers registered in TTS registry", _test_registry_has_providers)

# ── 4. service_factory syntax + structure ──────────────────────────
print("\n[4] service_factory.py structure verification")

def _test_factory_has_elif_branches():
    with open("api/services/pipecat/service_factory.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert 'ServiceProviders.RUMIK.value' in content, "Missing RUMIK elif branch"
    assert 'ServiceProviders.SONIOX.value' in content, "Missing SONIOX elif branch"
    assert 'ServiceProviders.FISHAUDIO.value' in content, "Missing FISHAUDIO elif branch"

check("service_factory.py has RUMIK/SONIOX/FISHAUDIO branches", _test_factory_has_elif_branches)

def _test_factory_has_imports():
    with open("api/services/pipecat/service_factory.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "FishAudioTTSService" in content, "Missing FishAudioTTSService import"
    assert "SonioxTTSService" in content, "Missing SonioxTTSService import"
    assert "RumikTTSService" in content, "Missing RumikTTSService import"

check("service_factory.py has required imports", _test_factory_has_imports)

def _test_factory_rumik_guard():
    with open("api/services/pipecat/service_factory.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "pipecat-rumik" in content, "Missing pipecat-rumik error message"
    assert "RumikTTSService is None" in content, "Missing None guard for Rumik"

check("service_factory.py has Rumik import guard", _test_factory_rumik_guard)

# ── 5. requirements.txt ────────────────────────────────────────────
print("\n[5] Requirements file")

def _test_requirements():
    with open("api/requirements.txt", "r") as f:
        content = f.read()
    assert "pipecat-rumik" in content, "Missing pipecat-rumik in requirements.txt"

check("pipecat-rumik in requirements.txt", _test_requirements)

# ── 6. Documentation ──────────────────────────────────────────────
print("\n[6] Documentation updates")

def _test_voice_docs():
    with open("docs/configurations/voice.mdx", "r", encoding="utf-8") as f:
        content = f.read()
    assert "Rumik AI" in content
    assert "Soniox" in content
    assert "Fish Audio" in content

check("voice.mdx lists all 3 providers", _test_voice_docs)

# ── Summary ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"Results: {passed} passed, {failed} failed")
if errors:
    print("\nFailed tests:")
    for name, err in errors:
        print(f"  - {name}: {err}")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
