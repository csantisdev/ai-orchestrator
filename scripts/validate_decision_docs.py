"""Validate naming, metadata, and local links in docs/decisions."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml


DECISIONS_ROOT = Path(__file__).resolve().parents[1] / "docs" / "decisions"
DOCUMENT_CATEGORIES = {
    "rfcs": ("RFC", "rfc"),
    "adrs": ("ADR", "adr"),
    "analyses": ("ANL", "analysis"),
}
STATUS_VALUES = {
    "rfc": {"draft", "in-review", "accepted", "rejected", "withdrawn", "superseded"},
    "adr": {"proposed", "accepted", "rejected", "superseded", "deprecated"},
    "analysis": {"active", "superseded", "archived"},
}
IMPLEMENTATION_STATUS_VALUES = {
    "not-started", "in-progress", "implemented", "verified", "abandoned",
}
ID_PATTERN = re.compile(r"^(RFC|ADR|ANL)-\d{3}$")
FILENAME_PATTERN = re.compile(r"^(RFC|ADR|ANL)-\d{3}-.+\.md$")
ARCHIVE_FILENAME_PATTERN = re.compile(r"^(RFC|ADR|ANL)-\d{3}-.+\.md$")
MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")


def _error(path: Path, message: str) -> str:
    return f"{path}: {message}"


def _canonical_id(path: Path) -> str | None:
    match = re.match(r"^(RFC|ADR|ANL)-\d{3}(?:-|$)", path.name)
    return match.group(0).rstrip("-") if match else None


def _validate_filename(path: Path, root: Path, errors: list[str]) -> tuple[str, str] | None:
    relative = path.relative_to(root)
    category = relative.parts[0]
    canonical_id = _canonical_id(path)

    if category in DOCUMENT_CATEGORIES:
        expected_prefix, expected_type = DOCUMENT_CATEGORIES[category]
        if path.name == "README.md":
            return None
        if not FILENAME_PATTERN.fullmatch(path.name):
            errors.append(_error(path, f"filename must be {expected_prefix}-NNN-descriptive-name.md"))
            return None
        if not path.name.startswith(f"{expected_prefix}-"):
            errors.append(_error(path, f"filename must use the {expected_prefix}-NNN prefix in {category}/"))
            return None
        return canonical_id, expected_type

    if category == "archive" and ARCHIVE_FILENAME_PATTERN.fullmatch(path.name):
        return canonical_id, None

    return None


def _parse_front_matter(path: Path, text: str, errors: list[str]) -> dict | None:
    lines = text.splitlines()
    if lines and lines[0] == "---":
        try:
            end = lines.index("---", 1)
        except ValueError:
            errors.append(_error(path, "front matter starts at line 1 but has no closing --- delimiter"))
            return None
        try:
            metadata = yaml.safe_load("\n".join(lines[1:end]))
        except yaml.YAMLError as exc:
            errors.append(_error(path, f"invalid YAML front matter: {exc}"))
            return None
        if not isinstance(metadata, dict):
            errors.append(_error(path, "front matter must be a YAML mapping"))
            return None
        return metadata

    for index, line in enumerate(lines):
        if line != "---":
            continue
        following = next((item for item in lines[index + 1:] if item.strip()), "")
        if re.match(r"(id|type|title|status|implementation_status):", following):
            errors.append(_error(path, "front matter must start at line 1, before the H1"))
        break
    return None


def _is_date(value: object) -> bool:
    return isinstance(value, (date, datetime)) or (
        isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
    )


def _validate_metadata(
    path: Path, metadata: dict, canonical_id: str | None, expected_type: str | None, errors: list[str]
) -> None:
    for field in ("id", "type", "title", "status", "created", "updated"):
        if field not in metadata:
            errors.append(_error(path, f"front matter is missing required field {field!r}"))

    doc_id = metadata.get("id")
    doc_type = metadata.get("type")
    if not isinstance(doc_id, str) or not ID_PATTERN.fullmatch(doc_id):
        errors.append(_error(path, "front matter id must be RFC-NNN, ADR-NNN, or ANL-NNN"))
    elif canonical_id and doc_id != canonical_id:
        errors.append(_error(path, f"front matter id {doc_id!r} does not match filename ID {canonical_id!r}"))

    if doc_type not in STATUS_VALUES:
        errors.append(_error(path, f"front matter type must be one of {', '.join(STATUS_VALUES)}"))
    elif expected_type and doc_type != expected_type:
        errors.append(_error(path, f"front matter type {doc_type!r} does not match its directory"))
    elif isinstance(doc_id, str) and ID_PATTERN.fullmatch(doc_id):
        id_type = {"RFC": "rfc", "ADR": "adr", "ANL": "analysis"}[doc_id[:3]]
        if doc_type != id_type:
            errors.append(_error(path, f"front matter type {doc_type!r} does not match ID {doc_id!r}"))

    if not isinstance(metadata.get("title"), str) or not metadata.get("title", "").strip():
        errors.append(_error(path, "front matter title must be a non-empty string"))
    if doc_type in STATUS_VALUES and metadata.get("status") not in STATUS_VALUES[doc_type]:
        errors.append(_error(path, f"invalid {doc_type} status {metadata.get('status')!r}"))
    for field in ("created", "updated"):
        if field in metadata and not _is_date(metadata[field]):
            errors.append(_error(path, f"front matter {field} must be an ISO date"))

    if doc_type == "adr":
        implementation_status = metadata.get("implementation_status")
        if implementation_status not in IMPLEMENTATION_STATUS_VALUES:
            errors.append(_error(path, "ADR implementation_status must be one of "
                          f"{', '.join(sorted(IMPLEMENTATION_STATUS_VALUES))}"))

    for field in ("supersedes", "related", "support", "evidence"):
        if field in metadata and (
            not isinstance(metadata[field], list)
            or not all(isinstance(value, str) for value in metadata[field])
        ):
            errors.append(_error(path, f"front matter {field} must be a list of strings"))
    if "superseded_by" in metadata and metadata["superseded_by"] is not None and not isinstance(
        metadata["superseded_by"], str
    ):
        errors.append(_error(path, "front matter superseded_by must be a string or null"))


def _validate_local_links(path: Path, text: str, errors: list[str]) -> None:
    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        target = match.group(1).strip("<>")
        parsed = urlparse(target)
        if not target or target.startswith("#") or parsed.scheme or target.startswith("//"):
            continue
        target_path = target.split("#", 1)[0].split("?", 1)[0]
        if target_path and not (path.parent / unquote(target_path)).resolve().exists():
            errors.append(_error(path, f"local link does not resolve: {target}"))


def validate_documents(root: Path = DECISIONS_ROOT) -> list[str]:
    """Return all validation errors for Markdown documents below *root*."""
    errors: list[str] = []
    canonical_ids: dict[str, Path] = {}
    for path in sorted(root.rglob("*.md")):
        filename_info = _validate_filename(path, root, errors)
        text = path.read_text(encoding="utf-8")
        if filename_info:
            metadata = _parse_front_matter(path, text, errors)
            canonical_id, expected_type = filename_info
            if expected_type:
                previous = canonical_ids.get(canonical_id)
                if previous:
                    errors.append(_error(path, f"duplicate canonical ID {canonical_id!r}; already used by {previous}"))
                else:
                    canonical_ids[canonical_id] = path
            if metadata is not None:
                _validate_metadata(path, metadata, canonical_id, expected_type, errors)
        _validate_local_links(path, text, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DECISIONS_ROOT)
    args = parser.parse_args()
    errors = validate_documents(args.root)
    if errors:
        print("Decision-document validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Decision-document validation passed: {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
