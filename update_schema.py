import os
import sqlite3

# Path to the database file
DB_PATH = 'instance/ai_website_monitor.db'

def add_notify_only_changes_column():
    """Add the notify_only_changes column to the User table."""
    try:
        # Connect to the database
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if the column already exists
        cursor.execute("PRAGMA table_info(user)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'notify_only_changes' not in column_names:
            print("Adding notify_only_changes column to User table...")
            # Add the new column with default value of True
            cursor.execute("ALTER TABLE user ADD COLUMN notify_only_changes BOOLEAN DEFAULT 1")
            conn.commit()
            print("Column added successfully!")
        else:
            print("Column notify_only_changes already exists in User table.")
        
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating schema: {e}")
        return False

if __name__ == "__main__":
    # Check if database file exists
    if not os.path.exists(DB_PATH):
        print(f"Database file not found at {DB_PATH}")
        exit(1)
    
    # Add the new column
    if add_notify_only_changes_column():
        print("Schema update completed successfully.")
    else:
        print("Schema update failed.") 