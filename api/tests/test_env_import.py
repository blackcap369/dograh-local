#!/usr/bin/env python
"""Test that our modified files can be imported with fake env vars."""
import os
import sys

# Add the project root to sys.path so we can import api.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set fake env vars so constants.py doesn't crash
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["MINIO_ENDPOINT"] = "localhost:9000"
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"
os.environ["BACKEND_API_ENDPOINT"] = "http://localhost:8000"
os.environ["UI_APP_URL"] = "http://localhost:3000"
os.environ["DOGRAH_DEVOPS_SECRET"] = "test-secret"

print("Testing imports with fake env...")

try:
    # This will trigger constants.py loading
    from api import constants
    print("  OK: api.constants loaded")
    print(f"    DATABASE_URL = {constants.DATABASE_URL}")
    print(f"    REDIS_URL = {constants.REDIS_URL}")
except Exception as e:
    print(f"  FAIL: api.constants import failed: {e}")
    sys.exit(1)

try:
    from api.services.configuration.registry import (
        ServiceProviders,
        RumikTTSConfiguration,
        SonioxTTSConfiguration,
        FishAudioTTSConfiguration,
    )
    print("  OK: TTS provider configs imported")

    # Quick sanity check
    r = RumikTTSConfiguration(api_key="test", base_url="wss://test")
    assert r.provider == ServiceProviders.RUMIK
    print("  OK: RumikTTSConfiguration instantiation works")

    s = SonioxTTSConfiguration(api_key="test")
    assert s.provider == ServiceProviders.SONIOX
    assert s.voice == "Bryce"
    print("  OK: SonioxTTSConfiguration defaults work")

    f = FishAudioTTSConfiguration(api_key="test")
    assert f.provider == ServiceProviders.FISHAUDIO
    assert f.model == "s2.1-pro"
    print("  OK: FishAudioTTSConfiguration defaults work")

except Exception as e:
    print(f"  FAIL: TTS provider imports failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    from api.services.pipecat import service_factory
    print("  OK: service_factory imported")
    # Just verify the create_tts_service function exists
    assert hasattr(service_factory, 'create_tts_service')
    print("  OK: create_tts_service function present")
except Exception as e:
    print(f"  FAIL: service_factory import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✅ All core imports successful!")
print("The TTS provider code is syntactically correct and can be imported.")
print("\nTo test the full server:")
print("1. Install Docker Desktop")
print("2. Run: docker-compose -f docker-compose-local.yaml up -d")
print("3. Copy api/.env.example to api/.env (or use the one I created)")
print("4. Run: python -m uvicorn api.app:app --reload --port 8000")