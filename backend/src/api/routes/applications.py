"""
Applications CRUD router.

Provides endpoints for managing job applications: listing, creating,
updating, deleting, and dashboard statistics.
"""

from __future__ import annotations

import logging
from uuid import UUID

from asyncpg import Connection
from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from src.api.dependencies import get_db
from src.core.state_machine import ApplicationStatus, can_transition, transition
from src.db.models import ApplicationCreate, ApplicationResponse, ApplicationUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["Applications"])


# ---------------------------------------------------------------------------
# GET /stats/summary — dashboard metrics
# Must be defined BEFORE /{app_id} to avoid route shadowing.
# ---------------------------------------------------------------------------

@router.get("/stats/summary")
async def get_stats_summary(conn: Connection = Depends(get_db)):
    """Return application counts grouped by status for the dashboard."""
    rows = await conn.fetch(
        """
        SELECT status, COUNT(*)::int AS count
        FROM applications
        WHERE deleted_at IS NULL
        GROUP BY status
        ORDER BY status
        """
    )
    # Build a dict that always includes every valid status (zero-filled).
    summary: dict[str, int] = {s.value: 0 for s in ApplicationStatus}
    for row in rows:
        summary[row["status"]] = row["count"]

    total = sum(summary.values())
    applied = summary.get(ApplicationStatus.APPLIED.value, 0) + summary.get(ApplicationStatus.OA_RECEIVED.value, 0)
    interviews = (
        summary.get(ApplicationStatus.INTERVIEW_SCHEDULED.value, 0)
        + summary.get(ApplicationStatus.INTERVIEWED.value, 0)
    )
    offers = summary.get(ApplicationStatus.OFFERED.value, 0) + summary.get(ApplicationStatus.ACCEPTED.value, 0)
    rejected = summary.get(ApplicationStatus.REJECTED.value, 0)

    return {
        "total": total,
        "applied": applied,
        "interviews": interviews,
        "offers": offers,
        "rejected": rejected,
        "by_status": summary,
    }


# ---------------------------------------------------------------------------
# GET / — list all applications
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ApplicationResponse])
async def list_applications(
    response: Response,
    status_filter: list[str] | None = Query(
        None,
        alias="status",
        description=(
            "Filter by application status. Repeat the parameter to match any "
            "of several, e.g. ?status=APPLIED&status=OFFERED."
        ),
    ),
    search: str | None = Query(
        None,
        description="Case-insensitive search across company name and role.",
    ),
    sort_by: str = Query(
        "updated_at",
        description="Column to sort by (created_at, updated_at, company, role, status).",
    ),
    order: str = Query(
        "desc",
        description="Sort order: 'asc' or 'desc'.",
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size."),
    offset: int = Query(0, ge=0, description="Number of rows to skip."),
    conn: Connection = Depends(get_db),
):
    """List applications with optional filtering, searching, sorting, and pagination."""
    # -- Validate sort parameters -------------------------------------------
    allowed_sort_columns = {"created_at", "updated_at", "company", "role", "status"}
    if sort_by not in allowed_sort_columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sort_by must be one of {allowed_sort_columns}",
        )
    if order.lower() not in ("asc", "desc"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order must be 'asc' or 'desc'",
        )

    # -- Build query dynamically --------------------------------------------
    conditions: list[str] = ["deleted_at IS NULL"]
    params: list[object] = []
    idx = 1  # asyncpg uses $1, $2, … placeholders

    if status_filter:
        # Validate every requested status before building the query.
        for value in status_filter:
            try:
                ApplicationStatus(value)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status '{value}'. Valid values: "
                           f"{[s.value for s in ApplicationStatus]}",
                ) from exc
        # Cast explicitly: asyncpg cannot infer the element type of an empty
        # or text array being compared against an enum column.
        conditions.append(f"status = ANY(${idx}::application_status[])")
        params.append(status_filter)
        idx += 1

    if search:
        conditions.append(
            f"(company ILIKE ${idx} OR role ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1

    where_clause = " AND ".join(conditions)

    # Total matching rows, before paging. Returned as a header so the body
    # stays a plain list; the UI needs it to page through the backlog, which
    # runs to tens of thousands of scraped listings.
    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM applications WHERE {where_clause}", *params
    )
    response.headers["X-Total-Count"] = str(total)

    # sort_by is validated above so safe for interpolation.
    query = f"""
        SELECT *
        FROM applications
        WHERE {where_clause}
        ORDER BY {sort_by} {order.upper()}
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit, offset])

    rows = await conn.fetch(query, *params)
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# GET /{app_id} — get single application
# ---------------------------------------------------------------------------

@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: UUID,
    conn: Connection = Depends(get_db),
):
    """Retrieve a single application by its UUID."""
    row = await conn.fetchrow(
        "SELECT * FROM applications WHERE id = $1 AND deleted_at IS NULL",
        app_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found.",
        )
    return dict(row)


# ---------------------------------------------------------------------------
# POST / — create new application
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    payload: ApplicationCreate,
    conn: Connection = Depends(get_db),
):
    """Create a new job application record."""
    # ApplicationCreate.status is already constrained to the enum by Pydantic,
    # so an invalid value is rejected as a 422 before reaching this point.
    initial_status = payload.status.value

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO applications
                (company, role, location, url, date_posted, source, status, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7::application_status, $8)
            RETURNING *
            """,
            payload.company,
            payload.role,
            payload.location,
            payload.url,
            payload.date_posted,
            payload.source,
            initial_status,
            payload.notes,
        )
    except UniqueViolationError as exc:
        # The schema dedupes on listing URL, falling back to
        # company + role + location. Both are surfaced as a conflict rather
        # than a 500 so the caller can tell a duplicate from a real failure.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"An application for '{payload.role}' at '{payload.company}' "
                "already exists."
            ),
        ) from exc
    logger.info("Created application %s for %s at %s", row["id"], payload.role, payload.company)
    return dict(row)


# ---------------------------------------------------------------------------
# PATCH /{app_id} — update application
# ---------------------------------------------------------------------------

@router.patch("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: UUID,
    payload: ApplicationUpdate,
    conn: Connection = Depends(get_db),
):
    """
    Update an existing application.

    If a status change is requested the state-machine validates whether
    the transition is allowed. Invalid transitions are rejected with 409.
    """
    # Fetch current record.
    existing = await conn.fetchrow(
        "SELECT * FROM applications WHERE id = $1 AND deleted_at IS NULL",
        app_id,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found.",
        )

    # Determine fields to update.
    update_data = payload.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update.",
        )

    # Validate status transition if the caller is changing status.
    if "status" in update_data and update_data["status"] is not None:
        current_status = ApplicationStatus(existing["status"])
        new_status = ApplicationStatus(update_data["status"])

        if not can_transition(current_status, new_status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot transition from '{current_status.value}' "
                    f"to '{new_status.value}'."
                ),
            )
        # Apply the validated transition (may carry side-effects / logging).
        transition(current_status, new_status)

    # Build dynamic SET clause.
    set_parts: list[str] = []
    params: list[object] = []
    idx = 1
    for column, value in update_data.items():
        set_parts.append(f"{column} = ${idx}")
        params.append(value)
        idx += 1

    # Always bump updated_at.
    set_parts.append("updated_at = NOW()")

    set_clause = ", ".join(set_parts)
    params.append(app_id)

    row = await conn.fetchrow(
        f"UPDATE applications SET {set_clause} WHERE id = ${idx} AND deleted_at IS NULL RETURNING *",
        *params,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found after update.",
        )

    logger.info("Updated application %s", app_id)
    return dict(row)


# ---------------------------------------------------------------------------
# DELETE /{app_id} — soft-delete application
# ---------------------------------------------------------------------------

@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: UUID,
    hard: bool = Query(False, description="Permanently delete the record."),
    conn: Connection = Depends(get_db),
):
    """
    Delete an application.

    By default a *soft* delete is performed (sets ``deleted_at``).
    Pass ``hard=true`` to permanently remove the row.
    """
    if hard:
        result = await conn.execute(
            "DELETE FROM applications WHERE id = $1", app_id
        )
    else:
        result = await conn.execute(
            "UPDATE applications SET deleted_at = NOW() WHERE id = $1 AND deleted_at IS NULL",
            app_id,
        )

    # asyncpg returns e.g. "DELETE 1" or "UPDATE 1"
    affected = int(result.split()[-1])
    if affected == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application {app_id} not found.",
        )

    logger.info("Deleted application %s (hard=%s)", app_id, hard)
    return None
