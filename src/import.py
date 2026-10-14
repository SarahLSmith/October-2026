
#Imports csv into sqlite database table. This is a staging table for further processing.
import csv
import sqlite3

CSV_FILE = "data/listings.csv"
DB_FILE = "airbnb.db"
TABLE_NAME = "stg_listings"


# Database connection (SQLite stores everything in a single file)
conn = sqlite3.connect(DB_FILE)

try:
    # Read the CSV header and rows
    with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        columns = next(reader)
        rows = list(reader)

    quoted_columns = ", ".join(f'"{col}"' for col in columns)
    column_definitions = ", ".join(f'"{col}" TEXT' for col in columns)
    placeholders = ", ".join("?" for _ in columns)

    cur = conn.cursor()

    # Create the staging table
    cur.execute(
        f'CREATE TABLE IF NOT EXISTS "{TABLE_NAME}" ({column_definitions})'
    )

    # Clear existing data to prevent duplicates (SQLite has no TRUNCATE)
    cur.execute(f'DELETE FROM "{TABLE_NAME}"')

    # Bulk import CSV rows
    cur.executemany(
        f'INSERT INTO "{TABLE_NAME}" ({quoted_columns}) VALUES ({placeholders})',
        rows
    )

    # Verify import
    count = cur.execute(f'SELECT COUNT(*) FROM "{TABLE_NAME}"').fetchone()[0]

    conn.commit()
    print(f"Successfully imported {count:,} rows into {TABLE_NAME}")

except Exception:
    conn.rollback()
    raise

finally:
    conn.close()