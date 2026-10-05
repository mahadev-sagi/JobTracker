"""
Assign the pre-multi-user applications to one account.

Migration 003 moved the old single-user table aside as
``legacy_applications``. Run this once, after the owner has signed in for the
first time (so their user row exists):

    docker compose exec backend python -m scripts.claim_legacy_data you@gmail.com

Copies every live row that had moved past UNAPPLIED (plus manual and
email-created rows) into ``applications`` for that user, linking each to its
shared listing where the URL matches, then drops the legacy table.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg
from src.core.config import get_settings


async def claim(email: str, keep: bool) -> int:
    conn = await asyncpg.connect(get_settings().DATABASE_URL)
    try:
        exists = await conn.fetchval("SELECT to_regclass('legacy_applications') IS NOT NULL")
        if not exists:
            print("No legacy_applications table; nothing to claim.")
            return 0
        user_id = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", email.lower()
        )
        if user_id is None:
            print(f"No user {email}. Sign in to the app once first.", file=sys.stderr)
            return 1

        async with conn.transaction():
            result = await conn.execute(
                """
                INSERT INTO applications
                    (user_id, listing_id, company, role, location, url, date_posted,
                     source, status, notes, email_thread_id, created_at, updated_at)
                SELECT $1, l.id, la.company, la.role, la.location, la.url,
                       la.date_posted, la.source, la.status, la.notes,
                       la.email_thread_id, la.created_at, la.updated_at
                FROM legacy_applications la
                LEFT JOIN listings l ON l.url = la.url
                WHERE la.deleted_at IS NULL
                  AND (la.status <> 'UNAPPLIED' OR la.source IS DISTINCT FROM 'SIMPLIFY_SCRAPER')
                """,
                user_id,
            )
            if not keep:
                await conn.execute("DROP TABLE legacy_applications")
        print(f"Claimed {result.split()[-1]} application(s) for {email}.")
        return 0
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email", help="Address of the account that owns the old data")
    parser.add_argument(
        "--keep", action="store_true", help="Leave legacy_applications in place"
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(claim(args.email, args.keep)))


if __name__ == "__main__":
    main()
