import csv
import sqlite3
import os
from pathlib import Path
from sources import _SIMULATED

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aquafair.db")
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_farms.csv")

def migrate():
    conn = sqlite3.connect(DB_PATH)
    
    # Insert sources
    for source_id, data in _SIMULATED.items():
        conn.execute("""
            INSERT OR IGNORE INTO sources 
            (source_id, name, type, capacity_L, live_storage_L, conveyance_efficiency, command_area_ha, wua)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source_id,
            data["name"],
            data["type"],
            data["capacity_L"],
            data["live_storage_L"],
            data["conveyance_efficiency"],
            data["command_area_ha"],
            data["wua"]
        ))
        
    # Insert demo farms
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute("""
                INSERT OR IGNORE INTO demo_farms
                (source_id, farm_id, farmer_name, crop, stage, area_m2, fairness_debt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row["source_id"],
                row["farm_id"],
                row["farmer_name"],
                row["crop"],
                row["stage"],
                float(row["area_m2"]),
                float(row["fairness_debt"])
            ))
            
    conn.commit()
    conn.close()
    print("Migration complete. DB populated.")

if __name__ == "__main__":
    import db
    db.init_db()  # Creates the tables if they don't exist
    migrate()
