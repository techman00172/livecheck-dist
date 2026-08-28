import sqlite3
import csv
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
CSV_PATH = os.path.join(PROJECT_ROOT, "src", "FORTH.csv")
DB_PATH = os.path.join(PROJECT_ROOT, "mecrisp_stellaris.db")


def create_database():
    if not os.path.exists(CSV_PATH):
        print(f"Error: FORTH.csv not found at {CSV_PATH}")
        return

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE FORTH(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            stack TEXT,
            description TEXT,
            example TEXT
        )
    """)

    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append((
                row["word"],
                row.get("stack", ""),
                row.get("description", ""),
                row.get("example", ""),
            ))

    cursor.executemany(
        "INSERT INTO FORTH (word, stack, description, example) VALUES (?, ?, ?, ?)",
        rows
    )

    conn.commit()
    conn.close()

    print(f"Database created: {DB_PATH}")
    print(f"Inserted {len(rows)} Forth words into table FORTH")


if __name__ == "__main__":
    create_database()
