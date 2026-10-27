import pytest
from pydantic import ValidationError

from comfy_hub_worker.config import Settings


@pytest.fixture
def config(tmp_path):
    return dict(
        _env_file=None,
        cloud_api_base_url="https://example.invalid",
        worker_id="00000000-0000-4000-8000-000000000001",
        worker_api_token="x" * 32,
        workflow_directory=tmp_path,
    )


def test_valid_config_masks_secret(config):
    settings = Settings(**config)
    assert settings.max_concurrent_jobs == 1
    assert "x" * 32 not in repr(settings)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cloud_api_base_url", "http://example.invalid"),
        ("cloud_api_base_url", "https://user:pass@example.invalid"),
        ("worker_api_token", ""),
        ("max_concurrent_jobs", 0),
        ("poll_interval_seconds", 0),
        ("workflow_directory", "/does-not-exist-comfy-hub"),
        ("worker_id", "invalid"),
    ],
)
def test_invalid_config(config, field, value):
    config[field] = value
    with pytest.raises(ValidationError):
        Settings(**config)


def test_local_development_allows_http(config):
    config["cloud_api_base_url"] = "http://127.0.0.1:3000"
    assert Settings(**config).cloud_api_base_url.scheme == "http"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8189",
        "http://localhost:8189",
        "http://[::1]:8189",
        "https://desktop-g58ban7.example-tailnet.ts.net",
    ],
)
def test_h3_runs_on_same_host_or_private_tailnet(config, url):
    config["h3_comfyui_base_url"] = url
    assert Settings(**config).h3_comfyui_base_url is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://desktop-g58ban7.example-tailnet.ts.net",
        "https://example.invalid",
        "http://192.168.2.80:8189",
        "http://127.0.0.1.evil.invalid:8189",
        "https://user:pass@127.0.0.1:8189",
    ],
)
def test_h3_rejects_nonlocal_insecure_or_unapproved_hosts(config, url):
    config["h3_comfyui_base_url"] = url
    with pytest.raises(ValidationError):
        Settings(**config)
