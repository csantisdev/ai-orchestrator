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
