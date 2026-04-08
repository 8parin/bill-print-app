"""
Database module for Neon PostgreSQL connection
Handles company profile persistence
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager


def get_db_connection():
    """Get database connection using DATABASE_URL from environment"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")

    conn = psycopg2.connect(database_url, sslmode='require')
    return conn


@contextmanager
def get_db_cursor(commit=False):
    """Context manager for database operations"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def init_database():
    """Initialize database tables with profile support"""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_info (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                tax_id VARCHAR(50),
                address TEXT,
                phone VARCHAR(50),
                branch_code VARCHAR(50) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add profile_name column if it doesn't exist (migration)
        cursor.execute("""
            ALTER TABLE company_info
            ADD COLUMN IF NOT EXISTS profile_name VARCHAR(100)
        """)

        # Set existing NULL profile_name rows to 'Default'
        cursor.execute("""
            UPDATE company_info SET profile_name = 'Default'
            WHERE profile_name IS NULL
        """)

        # Add unique constraint if not exists
        cursor.execute("""
            DO $$ BEGIN
                ALTER TABLE company_info ADD CONSTRAINT company_info_profile_name_unique
                UNIQUE (profile_name);
            EXCEPTION
                WHEN duplicate_table THEN NULL;
                WHEN duplicate_object THEN NULL;
            END $$;
        """)

        # Create updated_at trigger
        cursor.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)

        cursor.execute("""
            DROP TRIGGER IF EXISTS update_company_info_updated_at ON company_info;
            CREATE TRIGGER update_company_info_updated_at
                BEFORE UPDATE ON company_info
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)


def get_all_profiles():
    """Get list of all company profiles for dropdown"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT id, profile_name FROM company_info ORDER BY profile_name")
        return [dict(row) for row in cursor.fetchall()]


def get_profile(profile_name):
    """Get full company profile by name"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM company_info WHERE profile_name = %s",
            (profile_name,)
        )
        result = cursor.fetchone()
        return dict(result) if result else None


def save_profile(profile_name, name, tax_id, address, phone, branch_code=''):
    """Save or update a company profile (upsert by profile_name)"""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT id FROM company_info WHERE profile_name = %s",
            (profile_name,)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE company_info
                SET name = %s, tax_id = %s, address = %s, phone = %s, branch_code = %s
                WHERE profile_name = %s
            """, (name, tax_id, address, phone, branch_code, profile_name))
        else:
            cursor.execute("""
                INSERT INTO company_info (profile_name, name, tax_id, address, phone, branch_code)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (profile_name, name, tax_id, address, phone, branch_code))


def delete_profile(profile_name):
    """Delete a company profile by name"""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "DELETE FROM company_info WHERE profile_name = %s",
            (profile_name,)
        )
        return cursor.rowcount > 0
