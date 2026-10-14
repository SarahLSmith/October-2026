import sqlite3

def get_db_connection(db_file="airbnb.db"):
    """Establish a connection to the SQLite database."""
    return sqlite3.connect(db_file)

