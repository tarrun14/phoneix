import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aquafair.db")

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database does not exist, nothing to migrate.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    try:
        # Check if column already exists
        cursor = conn.execute("PRAGMA table_info(officers)")
        columns = [row[1] for row in cursor.fetchall()]
        if "password" not in columns:
            print("Adding 'password' column to 'officers' table...")
            conn.execute("ALTER TABLE officers ADD COLUMN password TEXT")
            # Set default password for existing officers
            conn.execute("UPDATE officers SET password = 'password'")
            conn.commit()
            print("Migration successful.")
        else:
            print("Column 'password' already exists.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
