"""
Shared job board.

Listings are scraped once and visible to everyone. The queue a user sees is
the listings they have not yet turned into an application of their own.
"""

from __future__ import annotations

import logging
from uuid import UUID

from asyncpg import Connection
from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from src.api.dependencies import CurrentUser, get_current_user, get_db
from src.db.models import ApplicationResponse, ListingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/listings", tags=["Listings"])

_SORT_COLUMNS = {"created_at", "date_posted", "company", "role"}


@router.get("/", response_model=list[ListingResponse])
async def list_listings(
    response: Response,
    search: str | None = Query(None, description="Matches company or role."),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """Listings the user has no live application for. Total in X-Total-Count."""
    if sort_by not in _SORT_COLUMNS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"sort_by must be one of {sorted(_SORT_COLUMNS)}"
        )
    if order.lower() not in ("asc", "desc"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "order must be 'asc' or 'desc'")

    conditions = [
        """NOT EXISTS (
            SELECT 1 FROM applications a
            WHERE a.listing_id = l.id AND a.user_id = $1 AND a.deleted_at IS NULL
        )"""
    ]
    params: list[object] = [user.id]
    if search:
        params.append(f"%{search}%")
        conditions.append(f"(l.company ILIKE ${len(params)} OR l.role ILIKE ${len(params)})")
    where = " AND ".join(conditions)

    total = await conn.fetchval(f"SELECT COUNT(*) FROM listings l WHERE {where}", *params)
    response.headers["X-Total-Count"] = str(total)

    params.extend([limit, offset])
    # sort_by and order are validated above, so safe to interpolate.
    rows = await conn.fetch(
        f"""
        SELECT l.* FROM listings l
        WHERE {where}
        ORDER BY l.{sort_by} {order.upper()} NULLS LAST, l.id
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    return [dict(r) for r in rows]


@router.post(
    "/{listing_id}/apply",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def apply_to_listing(
    listing_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """Record that the user applied to a listing."""
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO applications
                (user_id, listing_id, company, role, location, url, date_posted,
                 source, status)
            SELECT $1, id, company, role, location, url, date_posted, source, 'APPLIED'
            FROM listings WHERE id = $2
            RETURNING *
            """,
            user.id,
            listing_id,
        )
    except UniqueViolationError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have an application for this listing."
        ) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found.")
    return dict(row)
