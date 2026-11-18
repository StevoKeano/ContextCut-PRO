"""Tests for the sibling diffusion worker, client, proxy routes, and tools."""

from __future__ import annotations

import email.message
import io
import json
import time
import urllib.parse
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _request_url(request):
    return request if isinstance(request, str) else getattr(request, "full_url", str(request))


class TestModelRegistry:
    def test_default_is_z_image_turbo(self):
        from diffusion.worker import MODEL_REGISTRY, resolve_model

        assert resolve_model() == "z-image-turbo"
        spec = MODEL_REGISTRY["z-image-turbo"]
        assert spec.model_id == "Tongyi-MAI/Z-Image-Turbo"
        assert spec.steps == 8
        assert spec.guidance_scale == 0.0
        assert set(spec.pipelines) == {"text", "img2img", "inpaint"}

    def test_explicit_flux2_klein(self):
        from diffusion.worker import MODEL_REGISTRY, resolve_model

        assert resolve_model("flux2-klein") == "flux2-klein"
        spec = MODEL_REGISTRY["flux2-klein"]
        assert spec.model_id == "black-forest-labs/FLUX.2-klein-4B"
        assert spec.pipelines["text"] == "Flux2KleinPipeline"
        assert spec.steps == 4
        assert spec.guidance_scale == 1.0

    def test_explicit_stage1_models(self):
        from diffusion.worker import MODEL_REGISTRY

        dev = MODEL_REGISTRY["flux1-dev"]
        assert dev.model_id == "black-forest-labs/FLUX.1-dev"
        assert dev.pipelines["text"] == "FluxPipeline"

        kontext = MODEL_REGISTRY["flux1-kontext"]
        assert kontext.model_id == "black-forest-labs/FLUX.1-Kontext-dev"
        assert set(kontext.pipelines) == {"img2img"}

    def test_model_aliases(self):
        from diffusion.worker import resolve_model

        assert resolve_model("FLUX.2-klein") == "flux2-klein"
        assert resolve_model("FLUX.1-dev") == "flux1-dev"
        assert resolve_model("FLUX.1-Kontext-dev") == "flux1-kontext"

    def test_flux1_dev_is_hidden_but_explicitly_resolvable(self):
        from diffusion.worker import MODEL_REGISTRY, PUBLIC_MODEL_IDS, resolve_model

        assert "flux1-dev" not in PUBLIC_MODEL_IDS
        assert set(PUBLIC_MODEL_IDS) == {
            "z-image-turbo",
            "flux2-klein",
            "flux1-kontext",
            "auto",
        }
        assert MODEL_REGISTRY["flux1-dev"].offload_mode == "sequential"
        assert resolve_model("flux1-dev") == "flux1-dev"

    def test_flux1_dev_uses_sequential_cpu_offload(self, monkeypatch):
        import sys

        from diffusion.worker import PipelineManager

        calls = []
        pipe = SimpleNamespace(
            enable_sequential_cpu_offload=lambda: calls.append("sequential"),
            enable_model_cpu_offload=lambda: calls.append("model"),
            to=lambda device: calls.append(device),
        )
        pipeline_class = SimpleNamespace(
            from_pretrained=lambda source, **kwargs: pipe
        )
        monkeypatch.setitem(
            sys.modules, "torch", SimpleNamespace(bfloat16="bfloat16")
        )
        monkeypatch.setitem(
            sys.modules, "diffusers", SimpleNamespace(FluxPipeline=pipeline_class)
        )

        manager = PipelineManager(idle_timeout=1)
        assert manager._load_pipeline("flux1-dev", "text") is pipe
        assert calls == ["sequential"]

    def test_auto_policy_env(self, monkeypatch):
        from diffusion.worker import resolve_model

        monkeypatch.setenv("DIFFUSION_AUTO_TEXT_MODEL", "flux1-dev")
        monkeypatch.setenv("DIFFUSION_AUTO_EDIT_MODEL", "flux1-kontext")
        monkeypatch.setenv("DIFFUSION_AUTO_INPAINT_MODEL", "z-image-turbo")
        monkeypatch.setenv("DIFFUSION_AUTO_MULTIREF_MODEL", "flux1-kontext")

        assert resolve_model("auto") == "flux1-dev"
        assert resolve_model("auto", reference_images=1) == "flux1-kontext"
        assert resolve_model("auto", reference_images=3) == "flux1-kontext"
        assert resolve_model("auto", mask=True, reference_images=1) == "z-image-turbo"

        monkeypatch.setenv("DIFFUSION_AUTO_TEXT_MODEL", "not-a-model")
        assert resolve_model("auto") == "z-image-turbo"

    def test_task_capability_validation(self):
        from diffusion.worker import resolve_task

        assert resolve_task("flux2-klein", reference_images=3) == "img2img"
        with pytest.raises(ValueError):
            resolve_task("flux1-kontext")
        with pytest.raises(ValueError):
            resolve_task("flux1-dev", mask=True)
        with pytest.raises(ValueError):
            resolve_task("z-image-turbo", reference_images=2)

    def test_local_model_root_with_fallback(self, monkeypatch, tmp_path):
        import diffusion.worker as worker

        local = tmp_path / "FLUX.1-dev"
        local.mkdir()
        monkeypatch.setattr(worker, "MODEL_ROOT", tmp_path)

        dev = worker.MODEL_REGISTRY["flux1-dev"]
        assert worker._model_source(dev) == str(local)

        klein = worker.MODEL_REGISTRY["flux2-klein"]
        assert worker._model_source(klein) == klein.model_id

    def test_auto_switches_to_flux_with_reference_images(self):
        from diffusion.worker import resolve_model, resolve_task

        assert resolve_model("auto", reference_images=1) == "flux2-klein"
        assert resolve_model("auto", reference_images=3) == "flux2-klein"
        assert resolve_task("flux2-klein", reference_images=2) == "img2img"

    def test_auto_uses_z_image_for_text_and_masked_inpainting(self):
        from diffusion.worker import resolve_model, resolve_task

        assert resolve_model("auto") == "z-image-turbo"
        assert resolve_model("auto", reference_images=1, mask=True) == "z-image-turbo"
        assert resolve_task("z-image-turbo", mask=True, reference_images=1) == "inpaint"

    def test_unknown_model_rejected(self):
        from diffusion.worker import resolve_model

        with pytest.raises(ValueError):
            resolve_model("not-a-model")


class TestVramEviction:
    def test_evicts_every_loaded_ollama_model(self):
        from diffusion import client

        calls = []

        def fake_urlopen(request, timeout=None):
            url = _request_url(request)
            if url.endswith("/api/ps"):
                return _FakeResponse({"models": [{"name": "llama"}, {"name": "qwen"}]})
            if url.endswith("/api/generate"):
                calls.append(json.loads(request.data))
                return _FakeResponse({})
            raise AssertionError(url)

        with patch("diffusion.client.urllib.request.urlopen", side_effect=fake_urlopen):
            evicted = client.evict_ollama("http://192.168.137.1:11434")

        assert evicted == ["llama", "qwen"]
        assert [call["model"] for call in calls] == ["llama", "qwen"]
        assert all(call["keep_alive"] == 0 for call in calls)

    def test_unload_only_when_diffusion_active(self):
        from diffusion import client

        with patch.object(client, "_post_json") as post:
            client.set_active(False)
            assert client.unload_if_active() is False
            post.assert_not_called()

            client.set_active(True)
            assert client.unload_if_active() is True
            post.assert_called_once_with(
                client.WORKER_URL + "/internal/unload", {}, client.OLLAMA_EVICT_TIMEOUT
            )
            assert client.is_active() is False

            assert client.unload_if_active() is False
            assert post.call_count == 1
        client.set_active(False)

    def test_worker_call_evicts_then_uses_long_read_timeout(self):
        from diffusion import client

        def fake_urlopen(request, timeout=None):
            url = _request_url(request)
            if url.endswith("/api/ps"):
                return _FakeResponse({"models": []})
            if url.endswith("/v1/images/generations"):
                assert timeout >= 600
                return _FakeResponse(
                    {"data": [{"url": "http://127.0.0.1:8189/outputs/images/a.png"}]}
                )
            raise AssertionError(url)

        with patch("diffusion.client.urllib.request.urlopen", side_effect=fake_urlopen):
            result = client.call_worker(
                "/v1/images/generations",
                {"prompt": "a cat"},
                ollama_url="http://127.0.0.1:11434",
            )

        assert result["data"][0]["url"] == "/outputs/images/a.png"
        assert client.is_active() is True
        client.set_active(False)

    def test_remote_worker_uses_absolute_image_urls(self, monkeypatch):
        from diffusion import client

        monkeypatch.setattr(client, "WORKER_URL", "http://192.168.137.1:8189")
        monkeypatch.setattr(client, "IMAGE_BASE_URL", "")
        payload = {
            "data": [{"url": "http://127.0.0.1:8189/outputs/images/remote.png"}]
        }

        client.rewrite_image_urls(payload)

        assert (
            payload["data"][0]["url"]
            == "http://192.168.137.1:8189/outputs/images/remote.png"
        )

    def test_explicit_image_base_url_override(self, monkeypatch):
        from diffusion import client

        monkeypatch.setattr(client, "WORKER_URL", "http://192.168.137.1:8189")
        monkeypatch.setattr(client, "IMAGE_BASE_URL", "http://images.example.com/i")
        payload = {"data": [{"url": "http://127.0.0.1:8189/outputs/images/x.png"}]}

        client.rewrite_image_urls(payload)

        assert payload["data"][0]["url"] == "http://images.example.com/i/x.png"

    def test_chat_hook_unloads_diffusion(self):
        from diffusion import client

        request = MagicMock()
        request.url.path = "/v1/chat/completions"
        with patch.object(client, "unload_if_active") as unload:
            client._sync_unload_hook(request)
            unload.assert_called_once_with()
            request.url.path = "/health"
            client._sync_unload_hook(request)
            assert unload.call_count == 1

    def test_model_ids_discovers_worker_models(self, monkeypatch):
        from diffusion import client

        monkeypatch.setattr(client, "_model_cache", [])
        monkeypatch.setattr(client, "_model_cache_ts", 0.0)
        monkeypatch.setattr(client, "WORKER_URL", "http://worker:8189")
        monkeypatch.setattr(
            client,
            "_get_json",
            lambda url, timeout: {
                "data": [{"id": "z-image-turbo"}, {"id": "flux1-dev"}]
            },
        )

        assert client.model_ids() == ("z-image-turbo", "flux1-dev")

    def test_model_ids_fallback_when_worker_offline(self, monkeypatch):
        from diffusion import client

        def offline(*args, **kwargs):
            raise OSError("offline")

        monkeypatch.setattr(client, "_model_cache", [])
        monkeypatch.setattr(client, "_model_cache_ts", 0.0)
        monkeypatch.setattr(client, "_get_json", offline)

        models = client.model_ids()
        assert "flux1-kontext" in models
        assert "auto" in models


class TestProxyRoutes:
    @pytest.fixture(autouse=True)
    def _enable_diffusion(self, monkeypatch):
        import qdrant_proxy_final as proxy

        monkeypatch.setattr(proxy, "DIFFUSION_ENABLED", True)
        monkeypatch.setattr(proxy, "_provider_name", "Ollama")
        monkeypatch.setattr(proxy, "UPSTREAM", "http://127.0.0.1:11434")
        from diffusion import client

        client.set_active(False)

    def _parsed(self, raw):
        return json.loads(raw.split(b"\r\n\r\n", 1)[-1])

    def test_generation_route_forwards_and_rewrites_urls(self, make_handler):
        from qdrant_proxy_final import ProxyHandler

        payload = {
            "created": 1,
            "data": [
                {
                    "url": "http://127.0.0.1:8189/outputs/images/gen.png",
                    "b64_json": None,
                }
            ],
        }

        def fake_urlopen(request, timeout=None):
            url = _request_url(request)
            if url.endswith("/api/ps"):
                return _FakeResponse({"models": []})
            if url.endswith("/v1/images/generations"):
                assert json.loads(request.data)["prompt"] == "a dog"
                return _FakeResponse(payload)
            raise AssertionError(url)

        with patch("diffusion.client.urllib.request.urlopen", side_effect=fake_urlopen):
            status, raw = make_handler(
                "/v1/images/generations",
                "POST",
                body=json.dumps({"prompt": "a dog", "size": "512x512"}).encode(),
                handler_cls=ProxyHandler,
            )

        assert status == 200
        assert self._parsed(raw)["data"][0]["url"] == "/outputs/images/gen.png"

    def test_generation_route_with_remote_worker_uses_absolute_urls(
        self, make_handler, monkeypatch
    ):
        from diffusion import client
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr(client, "WORKER_URL", "http://192.168.137.1:8189")
        monkeypatch.setattr(client, "IMAGE_BASE_URL", "")
        payload = {
            "created": 3,
            "data": [
                {
                    "url": "http://127.0.0.1:8189/outputs/images/remote.png",
                    "b64_json": None,
                }
            ],
        }

        def fake_urlopen(request, timeout=None):
            url = _request_url(request)
            if url.endswith("/api/ps"):
                return _FakeResponse({"models": []})
            if url.startswith("http://192.168.137.1:8189/v1/images/generations"):
                return _FakeResponse(payload)
            raise AssertionError(url)

        with patch("diffusion.client.urllib.request.urlopen", side_effect=fake_urlopen):
            status, raw = make_handler(
                "/v1/images/generations",
                "POST",
                body=json.dumps({"prompt": "a dog"}).encode(),
                handler_cls=ProxyHandler,
            )

        assert status == 200
        assert (
            self._parsed(raw)["data"][0]["url"]
            == "http://192.168.137.1:8189/outputs/images/remote.png"
        )

    def test_edits_route_forwards_and_rewrites_urls(self, make_handler):
        from qdrant_proxy_final import ProxyHandler

        payload = {
            "created": 2,
            "data": [{"url": "http://127.0.0.1:8189/outputs/images/edit.png"}],
        }

        def fake_urlopen(request, timeout=None):
            url = _request_url(request)
            if url.endswith("/api/ps"):
                return _FakeResponse({"models": []})
            if url.endswith("/v1/images/edits"):
                return _FakeResponse(payload)
            raise AssertionError(url)

        with patch("diffusion.client.urllib.request.urlopen", side_effect=fake_urlopen):
            status, raw = make_handler(
                "/v1/images/edits",
                "POST",
                body=json.dumps(
                    {"prompt": "make it blue", "image": ["base64data"]}
                ).encode(),
                handler_cls=ProxyHandler,
            )

        assert status == 200
        assert self._parsed(raw)["data"][0]["url"] == "/outputs/images/edit.png"

    def test_static_image_serving_blocks_traversal(self, make_handler, monkeypatch, tmp_path):
        import qdrant_proxy_final as proxy
        from qdrant_proxy_final import ProxyHandler

        images = tmp_path / "images"
        images.mkdir()
        (images / "ok.png").write_bytes(b"\x89PNG\r\n\x1a\nvalid")
        (tmp_path / "secret.png").write_bytes(b"secret")
        monkeypatch.setattr(proxy, "OUTPUTS_DIR", images)

        status, raw = make_handler(
            "/outputs/images/ok.png", "GET", handler_cls=ProxyHandler
        )
        assert status == 200
        assert b"Content-Type: image/png" in raw
        assert raw.endswith(b"\x89PNG\r\n\x1a\nvalid")

        status, raw = make_handler(
            "/outputs/images/..%2Fsecret.png", "GET", handler_cls=ProxyHandler
        )
        assert status == 404
        assert b"secret" not in raw

    def test_models_endpoint_appends_diffusion_models(self, make_handler):
        from qdrant_proxy_final import ProxyHandler

        def fake_urlopen(request, timeout=None):
            assert _request_url(request).endswith("/v1/models")
            return _FakeResponse({"object": "list", "data": [{"id": "llama"}]})

        models = ["z-image-turbo", "flux2-klein", "flux1-kontext", "auto"]
        with patch("qdrant_proxy_final.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("qdrant_proxy_final.diffusion_model_names", return_value=models):
                status, raw = make_handler("/v1/models", "GET", handler_cls=ProxyHandler)

        assert status == 200
        ids = [item["id"] for item in self._parsed(raw)["data"]]
        assert ids == ["llama"] + models

    def test_forward_unloads_diffusion_before_llm_request(self):
        import qdrant_proxy_final as proxy

        handler = proxy.ProxyHandler.__new__(proxy.ProxyHandler)
        handler.requestline = "POST /v1/chat/completions HTTP/1.1"
        handler.path = "/v1/chat/completions"
        handler.headers = email.message.Message()
        handler.wfile = io.BytesIO()
        handler.request_version = "HTTP/1.1"

        with patch.object(proxy.diffusion_client, "unload_if_active") as unload:
            with patch(
                "qdrant_proxy_final.urllib.request.urlopen",
                side_effect=RuntimeError("stop"),
            ):
                handler._forward("POST", b"{}")

        unload.assert_called_once_with()

    def test_disabled_diffusion_returns_503(self, make_handler, monkeypatch):
        import qdrant_proxy_final as proxy
        from qdrant_proxy_final import ProxyHandler

        monkeypatch.setattr(proxy, "DIFFUSION_ENABLED", False)
        status, raw = make_handler(
            "/v1/images/generations",
            "POST",
            body=b'{"prompt":"x"}',
            handler_cls=ProxyHandler,
        )
        assert status == 503
        assert "disabled" in raw.decode("utf-8", errors="replace")


class TestDashboardDiffusionTest:
    def test_endpoint_probes_url_from_query(self, make_handler, monkeypatch):
        import qdrant_proxy_final as proxy

        monkeypatch.setattr(proxy, "DIFFUSION_ENABLED", True)
        monkeypatch.setattr(proxy, "DIFFUSION_WORKER_URL", "http://127.0.0.1:8189")

        def fake_urlopen(request, timeout=None):
            assert _request_url(request) == "http://192.168.137.1:8189/health"
            assert timeout <= 5
            return _FakeResponse(
                {
                    "status": "ok",
                    "models": ["z-image-turbo", "auto"],
                    "active_model": None,
                    "vram_allocated_bytes": 0,
                }
            )

        url = urllib.parse.quote("http://192.168.137.1:8189", safe="")
        with patch("qdrant_proxy_final.urllib.request.urlopen", side_effect=fake_urlopen):
            status, raw = make_handler(
                f"/api/diffusion/test?url={url}", "GET"
            )

        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data["ok"] is True
        assert data["url"] == "http://192.168.137.1:8189"
        assert data["models"] == ["z-image-turbo", "auto"]
        assert data["latency_ms"] >= 0

    def test_endpoint_reports_connection_error(self, make_handler, monkeypatch):
        import qdrant_proxy_final as proxy

        monkeypatch.setattr(proxy, "DIFFUSION_ENABLED", False)

        with patch(
            "qdrant_proxy_final.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ):
            status, raw = make_handler("/api/diffusion/test", "GET")

        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data["ok"] is False
        assert data["enabled"] is False
        assert "connection refused" in data["error"]

    def test_status_endpoint_returns_gpu_fields(self, make_handler, monkeypatch):
        import qdrant_proxy_final as proxy

        monkeypatch.setattr(proxy, "DIFFUSION_ENABLED", True)
        monkeypatch.setattr(proxy, "DIFFUSION_WORKER_URL", "http://192.168.137.1:8189")
        payload = {
            "status": "ok",
            "models": ["z-image-turbo", "flux2-klein", "auto"],
            "active_model": "z-image-turbo",
            "vram_allocated_bytes": 20754693120,
            "gpu_utilization_percent": 97,
            "gpu_memory_used_bytes": 23068672000,
            "gpu_memory_total_bytes": 25768876000,
            "gpu_temperature_c": 68,
            "gpu_power_watts": 320.15,
        }
        with patch(
            "qdrant_proxy_final.diffusion_client._get_json", return_value=payload
        ):
            status, raw = make_handler("/api/diffusion/status", "GET")

        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data["ok"] is True
        assert data["gpu_utilization_percent"] == 97
        assert data["gpu_memory_total_bytes"] == 25768876000
        assert data["active_model"] == "z-image-turbo"

    def test_status_endpoint_reports_worker_error(self, make_handler, monkeypatch, capsys):
        import qdrant_proxy_final as proxy

        monkeypatch.setattr(proxy, "DIFFUSION_ENABLED", True)
        monkeypatch.setattr(proxy, "DIFFUSION_WORKER_URL", "http://worker:8189")
        with patch(
            "qdrant_proxy_final.diffusion_client._get_json",
            side_effect=OSError("worker timeout"),
        ):
            status, raw = make_handler("/api/diffusion/status", "GET")

        assert status == 200
        data = json.loads(raw.split(b"\r\n\r\n", 1)[-1])
        assert data["ok"] is False
        assert data["enabled"] is True
        assert data["error"] == "worker timeout"
        assert "[diffusion] status error: worker timeout" in capsys.readouterr().out


class TestDashboardGenerationProgress:
    def test_progress_ui_is_present(self):
        import qdrant_proxy_final as proxy

        html = proxy.make_dashboard()
        assert "gen-progress" in html
        assert "startGenerationProgress" in html
        assert "markGenerationProgressDone" in html
        assert "finishGenerationProgress" in html
        assert "refreshGenerationStats" in html
        assert "setInterval(refreshGenerationStats, 5000)" in html
        assert "'/api/diffusion/status'" in html


class TestGpuStats:
    def test_parses_nvidia_smi_output(self, monkeypatch):
        import diffusion.worker as worker

        monkeypatch.setattr(worker, "_gpu_sample", {"ts": 0.0, "data": None})

        def fake_run(cmd, **kwargs):
            assert cmd[0] == "nvidia-smi"
            return SimpleNamespace(
                stdout=(
                    "NVIDIA GeForce RTX 4090, 97, 22000, 24564, 68, 320.15\n"
                ),
                stderr="",
            )

        monkeypatch.setattr(worker.subprocess, "run", fake_run)
        data = worker._gpu_stats()
        assert data["gpu_name"] == "NVIDIA GeForce RTX 4090"
        assert data["gpu_utilization_percent"] == 97
        assert data["gpu_memory_used_bytes"] == 22000 * 1048576
        assert data["gpu_memory_total_bytes"] == 24564 * 1048576
        assert data["gpu_temperature_c"] == 68
        assert data["gpu_power_watts"] == 320.15
        assert data["gpu_error"] is None

    def test_failure_returns_nulls(self, monkeypatch):
        import diffusion.worker as worker

        monkeypatch.setattr(worker, "_gpu_sample", {"ts": 0.0, "data": None})

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("nvidia-smi not found")

        monkeypatch.setattr(worker.subprocess, "run", fake_run)
        data = worker._gpu_stats()
        assert data["gpu_utilization_percent"] is None
        assert data["gpu_memory_used_bytes"] is None
        assert data["gpu_temperature_c"] is None
        assert data["gpu_error"]


class TestIdleWatchdog:
    def test_unloads_after_idle_timeout(self):
        from diffusion.worker import PipelineManager

        manager = PipelineManager(idle_timeout=0.05)
        manager.pipe = object()
        manager.active_model_key = "z-image-turbo"
        with patch.object(manager, "_unload_locked") as unload:
            manager.start_watchdog()
            try:
                time.sleep(0.4)
                assert unload.call_count >= 1
            finally:
                manager.stop_watchdog()

    def test_touch_resets_idle_timer(self):
        from diffusion.worker import PipelineManager

        manager = PipelineManager(idle_timeout=0.15)
        manager.pipe = object()
        with patch.object(manager, "_unload_locked") as unload:
            manager.start_watchdog()
            try:
                for _ in range(3):
                    time.sleep(0.05)
                    manager.touch()
                assert unload.call_count == 0
                time.sleep(0.3)
                assert unload.call_count >= 1
            finally:
                manager.stop_watchdog()

    def test_waits_for_generation_lock_before_unloading(self):
        from diffusion.worker import PipelineManager

        manager = PipelineManager(idle_timeout=0.05)
        manager.pipe = object()
        with patch.object(manager, "_unload_locked") as unload:
            manager.generation_lock.acquire()
            manager.start_watchdog()
            try:
                time.sleep(0.3)
                assert unload.call_count == 0
                manager.generation_lock.release()
                time.sleep(0.4)
                assert unload.call_count >= 1
            finally:
                if manager.generation_lock.locked():
                    manager.generation_lock.release()
                manager.stop_watchdog()


class TestAgentTools:
    def test_tools_expose_generate_and_edit(self):
        from diffusion.tools import make_image_tools

        tools = make_image_tools(ollama_url="http://127.0.0.1:11434")
        assert [tool.name for tool in tools] == ["generate_image", "edit_image"]

        with patch("diffusion.tools.client.call_worker") as call:
            call.return_value = {"data": [{"url": "/outputs/images/x.png"}]}
            result = tools[0].invoke({"prompt": "a cat", "size": "512x512"})

        assert "/outputs/images/x.png" in result
        payload = call.call_args[0][1]
        assert payload["prompt"] == "a cat"
        assert call.call_args[1]["ollama_url"] == "http://127.0.0.1:11434"

    def test_tools_skip_eviction_for_cloud_provider(self):
        from diffusion.tools import make_image_tools

        tools = make_image_tools(ollama_url="https://api.openai.com", provider="OpenAI")
        with patch("diffusion.tools.client.call_worker") as call:
            call.return_value = {"data": [{"url": "/outputs/images/y.png"}]}
            tools[0].invoke({"prompt": "a cat"})
        assert call.call_args[1]["evict"] is False
