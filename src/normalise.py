"""Transform public.clean_listings into six related analytics tables.

Run from the project root: python src/normalise.py
Requires: pip install psycopg2-binary python-dotenv
"""
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

SCHEMA = 'analytics'


def text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def number(value):
    value = text(value)
    if value is None:
        return None
    value = value.replace(',', '').replace('$', '').replace('£', '')
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def integer(value):
    n = number(value)
    return int(n) if n is not None and n == n.to_integral_value() else None


def boolean(value):
    value = text(value)
    if value is None:
        return None
    value = value.lower()
    if value in ('t', 'true', 'yes', 'y', '1'):
        return True
    if value in ('f', 'false', 'no', 'n', '0'):
        return False
    return None


def date_value(value):
    value = text(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def valid_id(value):
    result = integer(value)
    return result if result is not None and 0 <= result <= 9223372036854775807 else None


def field(row, name):
    return row.get(name)


def insert_rows(cur, table, columns, rows):
    if not rows:
        return
    statement = sql.SQL('INSERT INTO {}.{} ({}) VALUES %s').format(
        sql.Identifier(SCHEMA),
        sql.Identifier(table),
        sql.SQL(', ').join(map(sql.Identifier, columns)),
    ).as_string(cur.connection)
    execute_values(cur, statement, rows, page_size=1000)


def main():
    connection = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'airbnb'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD'),
    )
    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM public.clean_listings')
                source = cur.fetchall()

            with connection.cursor() as cur:
                cur.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(SCHEMA)))
                # Rebuild only these six tables; do not touch staging/clean data.
                for table in ('listing_reviews', 'listing_availability', 'listing_pricing',
                              'properties', 'listings', 'hosts'):
                    cur.execute(sql.SQL('DROP TABLE IF EXISTS {}.{}').format(
                        sql.Identifier(SCHEMA), sql.Identifier(table)))

                cur.execute('''CREATE TABLE analytics.hosts (
                    host_id BIGINT PRIMARY KEY,
                    host_name TEXT,
                    host_location TEXT,
                    host_is_superhost BOOLEAN,
                    host_identity_verified BOOLEAN
                )''')
                cur.execute('''CREATE TABLE analytics.listings (
                    listing_id BIGINT PRIMARY KEY,
                    host_id BIGINT NOT NULL REFERENCES analytics.hosts(host_id),
                    listing_name TEXT,
                    listing_url TEXT,
                    neighbourhood TEXT,
                    latitude DOUBLE PRECISION,
                    longitude DOUBLE PRECISION,
                    last_scraped DATE
                )''')
                cur.execute('''CREATE TABLE analytics.properties (
                    listing_id BIGINT PRIMARY KEY REFERENCES analytics.listings(listing_id),
                    property_type TEXT,
                    room_type TEXT,
                    accommodates INTEGER,
                    bedrooms INTEGER,
                    beds INTEGER,
                    bathrooms_text TEXT,
                    amenities TEXT
                )''')
                cur.execute('''CREATE TABLE analytics.listing_pricing (
                    listing_id BIGINT PRIMARY KEY REFERENCES analytics.listings(listing_id),
                    nightly_price NUMERIC(12,2),
                    quoted_nightly_price NUMERIC(12,2),
                    minimum_nights INTEGER,
                    maximum_nights INTEGER
                )''')
                cur.execute('''CREATE TABLE analytics.listing_availability (
                    listing_id BIGINT PRIMARY KEY REFERENCES analytics.listings(listing_id),
                    has_availability BOOLEAN,
                    availability_30 INTEGER,
                    availability_60 INTEGER,
                    availability_90 INTEGER,
                    availability_365 INTEGER
                )''')
                cur.execute('''CREATE TABLE analytics.listing_reviews (
                    listing_id BIGINT PRIMARY KEY REFERENCES analytics.listings(listing_id),
                    number_of_reviews INTEGER,
                    reviews_per_month NUMERIC(10,2),
                    first_review DATE,
                    last_review DATE,
                    review_scores_rating NUMERIC(4,2),
                    review_scores_cleanliness NUMERIC(4,2),
                    review_scores_location NUMERIC(4,2)
                )''')

                # Prefer the most recently scraped record when hosts repeat.
                source.sort(key=lambda r: date_value(field(r, 'last_scraped')) or date.min)
                hosts = {}
                listings, properties, pricing, availability, reviews = [], [], [], [], []
                seen_listings = set()
                skipped = 0
                for row in source:
                    listing_id = valid_id(field(row, 'id'))
                    host_id = valid_id(field(row, 'host_id'))
                    if listing_id is None or host_id is None or listing_id in seen_listings:
                        skipped += 1
                        continue
                    seen_listings.add(listing_id)
                    hosts[host_id] = (
                        host_id, text(field(row, 'host_name')),
                        text(field(row, 'host_location')),
                        boolean(field(row, 'host_is_superhost')),
                        boolean(field(row, 'host_identity_verified')),
                    )
                    lat, lon = number(field(row, 'latitude')), number(field(row, 'longitude'))
                    listings.append((
                        listing_id, host_id, text(field(row, 'name')),
                        text(field(row, 'listing_url')),
                        text(field(row, 'neighbourhood_cleansed')),
                        float(lat) if lat is not None and -90 <= lat <= 90 else None,
                        float(lon) if lon is not None and -180 <= lon <= 180 else None,
                        date_value(field(row, 'last_scraped')),
                    ))
                    properties.append((
                        listing_id, text(field(row, 'property_type')),
                        text(field(row, 'room_type')), integer(field(row, 'accommodates')),
                        integer(field(row, 'bedrooms')), integer(field(row, 'beds')),
                        text(field(row, 'bathrooms_text')), text(field(row, 'amenities')),
                    ))
                    pricing.append((
                        listing_id, number(field(row, 'price')),
                        number(field(row, 'price_quote_price_per_night')),
                        integer(field(row, 'minimum_nights')),
                        integer(field(row, 'maximum_nights')),
                    ))
                    availability.append((
                        listing_id, boolean(field(row, 'has_availability')),
                        integer(field(row, 'availability_30')),
                        integer(field(row, 'availability_60')),
                        integer(field(row, 'availability_90')),
                        integer(field(row, 'availability_365')),
                    ))
                    reviews.append((
                        listing_id, integer(field(row, 'number_of_reviews')),
                        number(field(row, 'reviews_per_month')),
                        date_value(field(row, 'first_review')),
                        date_value(field(row, 'last_review')),
                        number(field(row, 'review_scores_rating')),
                        number(field(row, 'review_scores_cleanliness')),
                        number(field(row, 'review_scores_location')),
                    ))

                insert_rows(cur, 'hosts',
                    ('host_id', 'host_name', 'host_location', 'host_is_superhost', 'host_identity_verified'),
                    list(hosts.values()))
                insert_rows(cur, 'listings',
                    ('listing_id', 'host_id', 'listing_name', 'listing_url', 'neighbourhood',
                     'latitude', 'longitude', 'last_scraped'), listings)
                insert_rows(cur, 'properties',
                    ('listing_id', 'property_type', 'room_type', 'accommodates', 'bedrooms',
                     'beds', 'bathrooms_text', 'amenities'), properties)
                insert_rows(cur, 'listing_pricing',
                    ('listing_id', 'nightly_price', 'quoted_nightly_price',
                     'minimum_nights', 'maximum_nights'), pricing)
                insert_rows(cur, 'listing_availability',
                    ('listing_id', 'has_availability', 'availability_30', 'availability_60',
                     'availability_90', 'availability_365'), availability)
                insert_rows(cur, 'listing_reviews',
                    ('listing_id', 'number_of_reviews', 'reviews_per_month', 'first_review',
                     'last_review', 'review_scores_rating', 'review_scores_cleanliness',
                     'review_scores_location'), reviews)

                print(f'Source records: {len(source):,}')
                print(f'Skipped (missing/invalid IDs or duplicate listing IDs): {skipped:,}')
                for table in ('hosts', 'listings', 'properties', 'listing_pricing',
                              'listing_availability', 'listing_reviews'):
                    cur.execute(sql.SQL('SELECT COUNT(*) FROM {}.{}').format(
                        sql.Identifier(SCHEMA), sql.Identifier(table)))
                    print(f'analytics.{table}: {cur.fetchone()[0]:,} rows')
        print('Transformation committed successfully.')
    finally:
        connection.close()


if __name__ == '__main__':
    main()