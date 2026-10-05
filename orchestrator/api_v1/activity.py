"""Endpoint Activity del proyecto (spec §10.4)."""

from __future__ import annotations

import re

from orchestrator.api_v1 import Request, route
from orchestrator.api_v1.work import _connection, _require_project
from orchestrator.projections_activity import project_activity


@route("GET", "/api/v1/projects/{project}/activity")
def activity(request: Request):
    """Devuelve hitos sanitizados, paginados y limitados al proyecto."""
    value = request.arg("limit")
    if value is None:
        limit = 50
    elif re.fullmatch(r"[1-9][0-9]{0,2}", value) and int(value) <= 200:
        limit = int(value)
    else:
        raise ValueError("limit must be an integer between 1 and 200")
    conn = _connection()
    missing = _require_project(conn, request.params["project"])
    if missing:
        return missing
    return project_activity(conn, request.params["project"], limit=limit, cursor=request.arg("cursor"))
