
import csv
import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()

CSV_FILE = "data/listings.csv"
TABLE_NAME = "stg_listings"


# Database connection
conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)

try:
    # Read the CSV header
    with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        columns = next(reader)

    with conn.cursor() as cur:

        # Create the staging table
        column_definitions = [
            sql.SQL("{} TEXT").format(sql.Identifier(col))
            for col in columns
        ]

        create_table = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {} ({})"
        ).format(
            sql.Identifier(TABLE_NAME),
            sql.SQL(", ").join(column_definitions)
        )

        cur.execute(create_table)

        # Clear existing data to prevent duplicates
        cur.execute(
            sql.SQL("TRUNCATE TABLE {}").format(
                sql.Identifier(TABLE_NAME)
            )
        )

        # Bulk import CSV
        with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
            copy_query = sql.SQL(
                "COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
            ).format(
                sql.Identifier(TABLE_NAME),
                sql.SQL(", ").join(
                    sql.Identifier(col) for col in columns
                )
            )

            cur.copy_expert(copy_query.as_string(conn), f)

        # Verify import
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(TABLE_NAME)
            )
        )

        count = cur.fetchone()[0]

    conn.commit()
    print(f"Successfully imported {count:,} rows into {TABLE_NAME}")

except Exception:
    conn.rollback()
    raise

finally:
    conn.close()
