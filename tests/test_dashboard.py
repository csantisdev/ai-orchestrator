import unittest

from orchestrator.dashboard import _fmt_ms, _fmt_tokens, _purpose_bucket, build_html


class DashboardTest(unittest.TestCase):
    def test_formats_numeric_strings_and_invalid_values(self):
        self.assertEqual("1.5s", _fmt_ms("1500"))
        self.assertEqual("—", _fmt_ms("invalid"))
        self.assertEqual("2K", _fmt_tokens("1200", "800"))

    def test_classifies_purpose(self):
        self.assertEqual("Manual · deepseek", _purpose_bucket("Elegido manualmente", "deepseek"))
        self.assertEqual("Research", _purpose_bucket("Research mode", "claude"))
        self.assertEqual("Sin razón", _purpose_bucket(None, "openai"))
        self.assertEqual("Router", _purpose_bucket("Elegido por señales", "claude"))

    def test_escapes_run_fields(self):
        payload = '<img src=x onerror="alert(1)">'
        output = build_html([
            {
                "ts": "2026-06-20T00:00:00+00:00",
                "project": payload,
                "provider": payload,
                "model": payload,
                "task_preview": payload,
                "routing_reason": payload,
                "duration_ms": "100",
                "input_tokens": "10",
                "output_tokens": None,
            }
        ])

        self.assertNotIn(payload, output)
        self.assertIn("&lt;img", output)
        self.assertIn("&quot;alert(1)&quot;", output)

    def test_renders_empty_and_malformed_runs(self):
        self.assertIn("Sin datos", build_html([]))
        output = build_html([
            {
                "project": 123,
                "provider": None,
                "model": None,
                "duration_ms": "bad",
                "input_tokens": {},
            }
        ])
        self.assertIn("123", output)
        self.assertIn("—", output)


if __name__ == "__main__":
    unittest.main()


_SCRIPT_BREAKOUT = "x</script><script>window.__xss=1</script><!-- "


def _run_with(task):
    return {"id": 1, "ts": "2026-01-01T00:00:00+00:00", "project": "demo", "provider": "git",
            "model": "", "status": "done", "task": task, "task_preview": task, "duration_ms": 0,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "cache_read_tokens": 0,
            "routing_reason": ""}


class ScriptInjectionTest(unittest.TestCase):
    """A run's text or the selected project must never close a <script> block."""

    def test_run_text_cannot_close_the_runs_script_block(self):
        import json

        output = build_html([_run_with(_SCRIPT_BREAKOUT)])

        self.assertNotIn("</script><script>window.__xss", output)
        start = output.index("window.__runsData = ") + len("window.__runsData = ")
        end = output.index(";\n</script>", start)
        runs = json.loads(output[start:end])
        self.assertEqual(_SCRIPT_BREAKOUT, runs[0]["task_preview"])

    def test_selected_project_cannot_close_the_filter_script(self):
        output = build_html([], selected_project=_SCRIPT_BREAKOUT)

        self.assertNotIn("</script><script>window.__xss", output)
        self.assertIn('_runsFilterProject = "x' + chr(92) + 'u003c/script' + chr(92) + 'u003e', output)

    def test_context_title_is_not_placed_inside_an_inline_handler(self):
        from orchestrator.dashboard import _build_contexts_section

        title = "x');window.__xss=1;//"
        output = _build_contexts_section([{"id": 7, "title": title, "project": "demo",
                                           "status": "active", "steps": []}])

        self.assertNotIn("deleteContext(7,", output)
        self.assertIn('onclick="deleteContextFromButton(this)"', output)
        self.assertIn('data-ctx-title="x&#x27;);window.__xss=1;//"', output)


class JsonForScriptTest(unittest.TestCase):
    def test_escapes_every_sequence_that_can_end_or_alter_a_script_block(self):
        import json

        from orchestrator.dashboard import _json_for_script

        value = {"t": "</script><script>a</SCRIPT><!-- b --> & c \u2028 d \u2029"}
        encoded = _json_for_script(value)

        for raw in ("<", ">", "&", "\u2028", "\u2029"):
            self.assertNotIn(raw, encoded)
        self.assertEqual(value, json.loads(encoded))

    def test_selected_project_round_trips(self):
        import json

        output = build_html([], selected_project=_SCRIPT_BREAKOUT)
        marker = "<script>\n_runsFilterProject = "
        start = output.index(marker) + len(marker)
        end = output.index(";", start)

        self.assertEqual(_SCRIPT_BREAKOUT, json.loads(output[start:end]))


class InlineHandlerSinkTest(unittest.TestCase):
    """Free text (aliases, titles) never goes inside an inline JS handler."""

    def test_project_aliases_are_read_from_data_attributes(self):
        from orchestrator.dashboard_js import _build_js

        js = _build_js()

        self.assertNotIn("RenameProject(\\'", js)
        self.assertIn("data-reg-action=\"start\" data-alias=\"' + ae + '\"", js)
        self.assertIn("ev.target.closest(\"[data-reg-action]\")", js)
