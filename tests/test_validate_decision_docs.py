import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.validate_decision_docs as validator


def _document(root: Path, relative_path: str, body: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _rfc(metadata: str = "") -> str:
    return f"""---
id: RFC-001
type: rfc
title: Test RFC
status: draft
created: 2026-01-01
updated: 2026-01-01
{metadata}---
# Test RFC
"""


def test_valid_documents_and_legacy_documents_pass(tmp_path):
    _document(tmp_path, "rfcs/RFC-001-test.md", _rfc())
    _document(tmp_path, "adrs/ADR-001-legacy.md", "# Legacy ADR\n")
    _document(tmp_path, "analyses/ANL-001-test.md", """---
id: ANL-001
type: analysis
title: Test analysis
status: active
created: 2026-01-01
updated: 2026-01-01
---
# Test analysis
""")

    assert validator.validate_documents(tmp_path) == []


def test_duplicate_canonical_ids_fail(tmp_path):
    _document(tmp_path, "rfcs/RFC-001-one.md", _rfc())
    _document(tmp_path, "rfcs/RFC-001-two.md", _rfc())

    errors = validator.validate_documents(tmp_path)

    assert any("duplicate canonical ID" in error for error in errors)


def test_front_matter_must_be_at_start_and_valid(tmp_path):
    _document(tmp_path, "rfcs/RFC-001-test.md", """# Test RFC
---
id: RFC-001
type: rfc
status: not-a-status
---
""")

    errors = validator.validate_documents(tmp_path)

    assert any("must start at line 1" in error for error in errors)


def test_invalid_adr_implementation_status_fails(tmp_path):
    _document(tmp_path, "adrs/ADR-001-test.md", """---
id: ADR-001
type: adr
title: Test ADR
status: accepted
implementation_status: complete
created: 2026-01-01
updated: 2026-01-01
---
# Test ADR
""")

    errors = validator.validate_documents(tmp_path)

    assert any("implementation_status" in error for error in errors)


def test_invalid_front_matter_yaml_fails(tmp_path):
    _document(tmp_path, "rfcs/RFC-001-test.md", """---
id: RFC-001
type: rfc
title: [unclosed
---
# Test RFC
""")

    errors = validator.validate_documents(tmp_path)

    assert any("invalid YAML front matter" in error for error in errors)


def test_broken_local_markdown_link_fails(tmp_path):
    _document(tmp_path, "rfcs/RFC-001-test.md", _rfc() + "\n[missing](missing.md)\n")

    errors = validator.validate_documents(tmp_path)

    assert any("local link does not resolve" in error for error in errors)
