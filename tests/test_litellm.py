import io

from litellm_codex_models import __version__
from litellm_codex_models.config import LiteLLMConfig
import litellm_codex_models.litellm as litellm_module


def test_fetch_payload_user_agent_uses_package_version(monkeypatch):
    captured = {}

    class FakeResponse(io.StringIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse('{"data": []}')

    monkeypatch.setenv("TEST_LITELLM_API_KEY", "test-key")
    monkeypatch.setattr(litellm_module, "urlopen", fake_urlopen)

    config = LiteLLMConfig(
        url="https://litellm.example.com",
        api_key_env="TEST_LITELLM_API_KEY",
        timeout_seconds=7.0,
    )

    assert litellm_module.fetch_payload(config) == []
    assert captured["request"].get_header("User-agent") == f"litellm-codex-models/{__version__}"
    assert captured["timeout"] == 7.0
