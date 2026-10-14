
import os
import math
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

IMPORTANT_FIELDS = [
    "id",
    "name",
    "host_id",
    "neighbourhood_cleansed",
    "room_type",
    "accommodates",
    "bedrooms",
    "beds",
    "price",
    "review_scores_rating"
]


def check_missing_values(cur):
    print("\n--- MISSING VALUES ---")

    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'clean_listings'
        ORDER BY ordinal_position
    """)

    columns = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM clean_listings")
    total = cur.fetchone()[0]

    results = []

    for column in columns:
        query = sql.SQL("""
            SELECT COUNT(*)
            FROM clean_listings
            WHERE {} IS NULL OR TRIM({}) = ''
        """).format(
            sql.Identifier(column),
            sql.Identifier(column)
        )

        cur.execute(query)
        missing = cur.fetchone()[0]
        results.append((column, missing))

    for column, missing in results:
        if column in IMPORTANT_FIELDS:
            percentage = (missing / total * 100) if total else 0
            print(
                f"{column:30} {missing:6,} "
                f"({percentage:.2f}%)"
            )

    print("\nColumns with missing values:")

    for column, missing in sorted(
        results, key=lambda x: x[1], reverse=True
    ):
        if missing > 0:
            print(f"{column:35} {missing:,}")

    return results


def check_invalid_values(cur):
    print("\n--- INVALID VALUES ---")

    numeric_fields = {
        "accommodates": (1, None),
        "bedrooms": (0, None),
        "beds": (0, None),
        "latitude": (-90, 90),
        "longitude": (-180, 180),
        "review_scores_rating": (0, 5),
    }

    for column, (minimum, maximum) in numeric_fields.items():

        query = sql.SQL("""
            SELECT {}
            FROM clean_listings
            WHERE {} IS NOT NULL
              AND TRIM({}) <> ''
        """).format(
            sql.Identifier(column),
            sql.Identifier(column),
            sql.Identifier(column)
        )

        cur.execute(query)
        values = cur.fetchall()

        invalid = 0

        for (value,) in values:
            try:
                number = float(value)

                if (
                    not math.isfinite(number)
                    or number < minimum
                    or (
                        maximum is not None
                        and number > maximum
                    )
                ):
                    invalid += 1

            except (ValueError, TypeError):
                invalid += 1

        print(f"{column:30} {invalid:,} invalid values")

    # Check price values
    cur.execute("""
        SELECT price
        FROM clean_listings
        WHERE price IS NOT NULL
          AND TRIM(price) <> ''
    """)

    invalid_prices = 0

    for (price,) in cur.fetchall():
        try:
            value = float(
                price.replace("$", "")
                     .replace(",", "")
                     .strip()
            )

            if not math.isfinite(value) or value < 0:
                invalid_prices += 1

        except (ValueError, TypeError):
            invalid_prices += 1

    print(f"{'price':30} {invalid_prices:,} invalid values")


def check_duplicates(cur):
    print("\n--- DUPLICATE CHECK ---")

    cur.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT id
            FROM stg_listings
            GROUP BY id
            HAVING COUNT(*) > 1
        ) duplicates
    """)

    duplicate_ids = cur.fetchone()[0]

    print(f"Duplicate listing IDs in staging: {duplicate_ids:,}")

    cur.execute("""
        SELECT COUNT(*)
        FROM (
            SELECT id
            FROM clean_listings
            GROUP BY id
            HAVING COUNT(*) > 1
        ) duplicates
    """)

    clean_duplicates = cur.fetchone()[0]

    print(f"Duplicate listing IDs in clean table: {clean_duplicates:,}")


def main():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "airbnb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.environ["DB_PASSWORD"]
    )

    try:
        with conn.cursor() as cur:

            print("--- CLEANING ---")

            # Count original records
            cur.execute("SELECT COUNT(*) FROM stg_listings")
            original_count = cur.fetchone()[0]

            # Rebuild clean table from staging
            cur.execute("DROP TABLE IF EXISTS clean_listings")

            cur.execute("""
                CREATE TABLE clean_listings AS
                SELECT DISTINCT ON (id) *
                FROM stg_listings
                ORDER BY id, last_scraped DESC NULLS LAST, ctid
            """)

            # Remove records with missing IDs
            cur.execute("""
                DELETE FROM clean_listings
                WHERE id IS NULL OR TRIM(id) = ''
            """)

            removed_missing_ids = cur.rowcount

            # Remove records with missing prices
            cur.execute("""
                DELETE FROM clean_listings
                WHERE price IS NULL OR TRIM(price) = ''
            """)

            removed_missing_prices = cur.rowcount

            # Enforce unique listing IDs
            cur.execute("""
                ALTER TABLE clean_listings
                ADD PRIMARY KEY (id)
            """)

            # Count cleaned records
            cur.execute("SELECT COUNT(*) FROM clean_listings")
            clean_count = cur.fetchone()[0]

            print(f"Original records: {original_count:,}")
            print(f"Missing IDs removed: {removed_missing_ids:,}")
            print(
                "Missing prices removed: "
                f"{removed_missing_prices:,}"
            )
            print(f"Clean records: {clean_count:,}")
            print(
                f"Total records removed: "
                f"{original_count - clean_count:,}"
            )

            # Data quality checks
            check_duplicates(cur)
            check_missing_values(cur)
            check_invalid_values(cur)

        conn.commit()
        print("\nCleaning completed successfully.")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()