"""Estáticos con hash por directorio (§19.4 O3, §23.7) y registro de api_v1 (§24.3.2)."""

from __future__ import annotations

import http.client
import json
import re
import threading

import pytest

from orchestrator.static_assets import CACHE_CONTROL, URL_PREFIX, build_bundle


def _tree(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


class TestStaticBundle:
    def test_inventories_servable_files_and_hashes_paths_and_contents(self, tmp_path):
        root = _tree(tmp_path / "a", {
            "core/router.js": b"export const x = 1;", "tokens.css": b":root{}", "package.json": b"{}",
            ".hidden.js": b"x", "notes.txt": b"x", "core/.cache/y.js": b"x",
        })

        bundle = build_bundle(root)

        assert bundle.files == {"core/router.js", "tokens.css"}
        assert re.fullmatch(r"[0-9a-f]{12}", bundle.version)

    @pytest.mark.parametrize("change", [
        lambda root: (root / "tokens.css").write_bytes(b":root{--x:1}"),
        lambda root: (root / "core/router.js").rename(root / "core/router2.js"),
        lambda root: (root / "views").mkdir() or (root / "views/home.js").write_bytes(b""),
    ])
    def test_any_change_changes_the_version(self, tmp_path, change):
        root = _tree(tmp_path / "a", {"core/router.js": b"x", "tokens.css": b"y"})
        before = build_bundle(root).version

        change(root)

        assert build_bundle(root).version != before

    def test_package_json_does_not_affect_the_version(self, tmp_path):
        root = _tree(tmp_path / "a", {"core/router.js": b"x", "package.json": b"{}"})
        before = build_bundle(root).version

        (root / "package.json").write_bytes(b'{"type": "module"}')

        assert build_bundle(root).version == before

    def test_resolve_serves_only_inventoried_files_of_the_current_version(self, tmp_path):
        root = _tree(tmp_path / "a", {"core/router.js": b"x", "tokens.css": b"y", "package.json": b"{}"})
        bundle = build_bundle(root)
        prefix = f"{URL_PREFIX}{bundle.version}/"

        assert bundle.resolve(prefix + "core/router.js") == (root / "core/router.js", "text/javascript; charset=utf-8")
        assert bundle.resolve(prefix + "tokens.css")[1] == "text/css; charset=utf-8"
        for bad in ("package.json", "../a/tokens.css", "core/../tokens.css", "core%2Frouter.js", "CORE/router.js",
                    "core/router.js/", "", "core\\router.js"):
            assert bundle.resolve(prefix + bad) is None, bad
        assert bundle.resolve(f"{URL_PREFIX}000000000000/core/router.js") is None
        assert bundle.url("core/router.js") == prefix + "core/router.js"
        with pytest.raises(KeyError):
            bundle.url("package.json")

    def test_the_real_directory_is_servable(self):
        bundle = build_bundle()

        assert {"core/store.js", "core/router.js"} <= bundle.files
        assert "package.json" not in bundle.files


class TestApiRegistry:
    def test_discover_finds_every_vertical_module(self):
        from orchestrator import api_v1

        routes = api_v1.discover()

        assert ("GET", "/api/v1/meta/projects") in {(r.method, r.pattern) for r in routes}

    def test_dispatch_matches_params_methods_and_errors(self):
        from orchestrator.api_v1 import Registry, Request

        registry = Registry()

        @registry.route("GET", "/api/v1/demo/{item_id}")
        def get_item(request):
            if request.params["item_id"] == "bad":
                raise ValueError("id inválido")
            return {"id": request.params["item_id"], "q": request.arg("q")}

        @registry.route("POST", "/api/v1/demo/{item_id}")
        def post_item(request):
            return 201, {"body": request.body}

        @registry.route("POST", "/api/v1/solo-post")
        def only_post(request):
            return {}

        assert registry.dispatch(Request("GET", "/api/v1/demo/a%20b", query={"q": ["1"]})) == (200, {"id": "a b", "q": "1"})
        assert registry.dispatch(Request("POST", "/api/v1/demo/x", body={"k": 1})) == (201, {"body": {"k": 1}})
        assert registry.dispatch(Request("GET", "/api/v1/demo/bad")) == (400, {"error": "id inválido"})
        assert registry.dispatch(Request("GET", "/api/v1/demo/a/b"))[0] == 404
        assert registry.dispatch(Request("GET", "/api/v1/otra"))[0] == 404
        assert registry.dispatch(Request("GET", "/api/v1/solo-post"))[0] == 405

    @pytest.mark.parametrize("method, pattern", [("PUT", "/api/v1/x"), ("GET", "/otra/x")])
    def test_route_rejects_bad_declarations(self, method, pattern):
        from orchestrator.api_v1 import Registry

        with pytest.raises(ValueError):
            Registry().route(method, pattern)(lambda request: {})

    def test_duplicate_routes_are_rejected(self):
        from orchestrator.api_v1 import Registry

        registry = Registry()
        registry.route("GET", "/api/v1/x")(lambda request: {})
        with pytest.raises(ValueError):
            registry.route("GET", "/api/v1/x")(lambda request: {})


@pytest.fixture
def server(tmp_path, monkeypatch):
    import orchestrator.db as db
    import orchestrator.paths as paths
    from orchestrator.server import serve

    monkeypatch.setattr(paths, "HOME_DIR", tmp_path)
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "runs.db")
    monkeypatch.setattr(db, "_local", threading.local())
    db.init_db()
    servers, ready = [], threading.Event()

    def on_ready(srv):
        servers.append(srv)
        ready.set()

    thread = threading.Thread(target=serve, args=(0, None, False, {}),
                              kwargs={"on_server_ready": on_ready, "start_background": False}, daemon=True)
    thread.start()
    assert ready.wait(5)
    port = servers[0].server_address[1]

    def request(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body, {"Host": f"localhost:{port}", **(headers or {})})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response, data

    _, page = request("GET", "/")
    token = re.search(rb'orchestrator-session" content="([^"]+)', page).group(1).decode()
    yield request, token
    servers[0].shutdown()
    thread.join(timeout=3)


def test_server_serves_dashboard_statics_with_immutable_cache(server):
    request, _ = server
    bundle = build_bundle()

    response, body = request("GET", bundle.url("core/router.js"))

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/javascript; charset=utf-8"
    assert response.getheader("Cache-Control") == CACHE_CONTROL
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert b"export function parseLocation" in body
    for bad in (f"{URL_PREFIX}{bundle.version}/package.json", f"{URL_PREFIX}000000000000/core/router.js",
                f"{URL_PREFIX}{bundle.version}/../../server.py"):
        assert request("GET", bad)[0].status == 404


def test_server_dispatches_api_v1_routes(server, monkeypatch):
    import orchestrator.index as index_module

    monkeypatch.setattr(index_module, "list_projects", lambda: {"mi-proyecto": "/x"})
    request, token = server

    response, body = request("GET", "/api/v1/meta/projects")

    assert response.status == 200
    assert response.getheader("Cache-Control") == "no-store"
    assert json.loads(body) == {"projects": [{"alias": "mi-proyecto", "registered": True, "has_runs": False}]}
    assert request("GET", "/api/v1/no-existe")[0].status == 404


def test_api_v1_posts_go_through_the_session_checks(server):
    request, token = server
    json_headers = {"Content-Type": "application/json"}

    assert request("POST", "/api/v1/meta/projects", b"{}", json_headers)[0].status == 403
    session = {**json_headers, "X-Orchestrator-Session": token}
    assert request("POST", "/api/v1/meta/projects", b"{}", session)[0].status == 405
    assert request("POST", "/api/v1/meta/projects", b"[1]", session)[0].status == 400
    assert request("POST", "/api/v1/meta/projects", b"no json", session)[0].status == 400
