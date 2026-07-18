import threading
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from orchestrator import background, egress
from orchestrator.context import ContextNotFoundError, ProjectContext
from orchestrator.egress import EgressPolicy, current_policy, set_policy
from orchestrator.providers.base import BaseProvider, CompletionResult


def _config(clearance: str = "internal") -> dict:
    return {
        "defaults": {"default_provider": "claude"},
        "providers": {
            "claude": {
                "api_key": "test",
                "model": "test-model",
                "clearance": clearance,
            }
        },
    }


class RecordingProvider(BaseProvider):
    name = "claude"

    def __init__(self, observed_policies: list):
        super().__init__(api_key="test", model="test-model")
        self.observed_policies = observed_policies

    def _complete(self, prompt: str, system: str = "") -> CompletionResult:
        self.observed_policies.append(current_policy())
        return CompletionResult(
            text="ok",
            provider=self.name,
            model=self.model,
        )


@contextmanager
def _worker_runtime(provider: BaseProvider, loaded_ctx=None, load_error=None):
    done = threading.Event()
    failed = threading.Event()
    with ExitStack() as stack:
        update_run = stack.enter_context(patch("orchestrator.background.update_run"))
        fail_run = stack.enter_context(patch("orchestrator.background.fail_run"))
        fail_run.side_effect = lambda *args, **kwargs: failed.set()
        stack.enter_context(patch("orchestrator.background.insert_run", return_value=101))
        bus = stack.enter_context(patch("orchestrator.background.BUS"))
        bus.publish.side_effect = (
            lambda event, payload: done.set() if event == "run_done" else None
        )
        index_path = stack.enter_context(
            patch("orchestrator.index.get_project_path", return_value=Path("."))
        )
        load_context = stack.enter_context(
            patch("orchestrator.context.load_context", return_value=loaded_ctx)
        )
        if load_error is not None:
            load_context.side_effect = load_error
        stack.enter_context(
            patch("orchestrator.router._fetch_active_context", return_value=None)
        )
        stack.enter_context(
            patch("orchestrator.providers.factory.build_provider", return_value=provider)
        )
        # router.py importa build_provider a nivel de módulo (binding propio,
        # independiente del de providers.factory) y decide_provider() llama a
        # _fetch_similar_runs(), que golpea el backend real de ChromaDB si no
        # se mockea -- sin esto, el único test que no fuerza `model=` dispara
        # una llamada de red real y una descarga de modelo ONNX en runners
        # sin cache, superando el join(timeout=3) del test.
        stack.enter_context(
            patch("orchestrator.router.build_provider", return_value=provider)
        )
        stack.enter_context(
            patch("orchestrator.router._fetch_similar_runs", return_value=[])
        )
        stack.enter_context(
            patch("orchestrator.tracer.span", side_effect=lambda *a, **k: nullcontext())
        )
        stack.enter_context(patch("orchestrator.rag.retrieve_docs", return_value=[]))
        stack.enter_context(patch("orchestrator.rag.retrieve_responses", return_value=[]))
        stack.enter_context(patch("orchestrator.rag.build_context_block", return_value=""))
        stack.enter_context(patch("orchestrator.rag.index_response"))
        stack.enter_context(
            patch("orchestrator.config.get_pricing_table", return_value={})
        )
        stack.enter_context(patch("orchestrator.costs.calculate_cost", return_value=0.0))
        stack.enter_context(
            patch("orchestrator.costs.check_budget", return_value={"warning": False})
        )
        yield SimpleNamespace(
            done=done,
            failed=failed,
            update_run=update_run,
            fail_run=fail_run,
            bus=bus,
            index_path=index_path,
            load_context=load_context,
        )


def test_background_worker_sets_policy_inside_thread():
    observed = []
    provider = RecordingProvider(observed)
    ctx = ProjectContext(name="worker-project", sensitivity="internal")
    parent_token = set_policy(EgressPolicy(
        project="parent-project",
        blocked_providers=["claude"],
    ))
    try:
        created_threads = []
        real_thread_class = threading.Thread

        def create_thread(*args, **kwargs):
            thread = real_thread_class(*args, **kwargs)
            created_threads.append(thread)
            return thread

        with _worker_runtime(provider, loaded_ctx=ctx) as runtime:
            with patch(
                "orchestrator.background.threading.Thread",
                side_effect=create_thread,
            ):
                run_id = background.submit_run(
                    project="worker-project",
                    task="tarea",
                    config=_config(),
                )
            created_threads[0].join(timeout=3)

        assert run_id == 101
        assert not created_threads[0].is_alive()
        assert runtime.done.is_set()
        assert not runtime.failed.is_set()
        assert observed[0].project == "worker-project"
    finally:
        egress._POLICY.reset(parent_token)


def test_parent_thread_policy_does_not_silently_leak_to_worker():
    observed = []
    provider = RecordingProvider(observed)
    ctx = ProjectContext(name="isolated-worker", sensitivity="public")
    parent_policy = EgressPolicy(project="parent-only", sensitivity="secret")
    parent_token = set_policy(parent_policy)
    try:
        with _worker_runtime(provider, loaded_ctx=ctx) as runtime:
            thread = threading.Thread(
                target=background._worker,
                args=(102, "isolated-worker", "tarea", _config(), "claude", None),
            )
            thread.start()
            thread.join(timeout=3)

        assert not thread.is_alive()
        assert runtime.done.is_set()
        assert observed[0].project == "isolated-worker"
        assert observed[0] is not parent_policy
        assert current_policy() is parent_policy
    finally:
        egress._POLICY.reset(parent_token)


def test_missing_context_yaml_uses_internal_default_and_does_not_block():
    observed = []
    provider = RecordingProvider(observed)
    missing = ContextNotFoundError("missing context.yaml")

    with _worker_runtime(provider, load_error=missing) as runtime:
        background._worker(103, "new-project", "tarea", _config(), "claude", None)

    assert runtime.done.is_set()
    assert not runtime.failed.is_set()
    assert observed[0].project == "new-project"
    assert observed[0].sensitivity == "internal"


def test_worker_resets_policy_between_runs():
    observed = []
    provider = RecordingProvider(observed)
    original_policy = current_policy()
    restricted_ctx = ProjectContext(name="first", sensitivity="restricted")
    public_ctx = ProjectContext(name="second", sensitivity="public")

    with _worker_runtime(provider) as runtime:
        background._worker(
            104, "first", "tarea", _config("secret"), "claude", restricted_ctx
        )
        assert current_policy() is original_policy
        background._worker(
            105, "second", "tarea", _config("secret"), "claude", public_ctx
        )

    assert runtime.update_run.call_count == 2
    assert [policy.project for policy in observed] == ["first", "second"]
    assert [policy.sensitivity for policy in observed] == ["restricted", "public"]
    assert current_policy() is original_policy


def test_worker_uses_provided_ctx_without_reloading():
    observed = []
    provider = RecordingProvider(observed)
    ctx = ProjectContext(name="provided", sensitivity="restricted")

    with _worker_runtime(provider) as runtime:
        background._worker(
            106, "provided", "tarea", _config("restricted"), "claude", ctx
        )

    runtime.index_path.assert_not_called()
    runtime.load_context.assert_not_called()
    assert runtime.done.is_set()
    assert observed[0].sensitivity == "restricted"


def test_corrupt_context_fails_closed_instead_of_using_default():
    observed = []
    provider = RecordingProvider(observed)

    with _worker_runtime(provider, load_error=ValueError("invalid yaml")) as runtime:
        background._worker(107, "broken", "tarea", _config(), "claude", None)

    assert runtime.failed.is_set()
    assert not runtime.done.is_set()
    assert observed == []
    assert "invalid yaml" in runtime.fail_run.call_args.args[1]
