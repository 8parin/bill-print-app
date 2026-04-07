"""
Database module for Neon PostgreSQL connection
Handles company info persistence
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
    
    # Render's PostgreSQL URL needs sslmode=require
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
    """Initialize database tables"""
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


def get_company_info():
    """Get company info from database"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM company_info ORDER BY id DESC LIMIT 1")
            result = cursor.fetchone()
            if result:
                return dict(result)
            return None
    except Exception:
        return None


def save_company_info(name, tax_id, address, phone, branch_code=''):
    """Save or update company info"""
    with get_db_cursor(commit=True) as cursor:
        # Check if exists
        cursor.execute("SELECT id FROM company_info LIMIT 1")
        existing = cursor.fetchone()
        
        if existing:
            # Update
            cursor.execute("""
                UPDATE company_info 
                SET name = %s, tax_id = %s, address = %s, phone = %s, branch_code = %s
                WHERE id = %s
            """, (name, tax_id, address, phone, branch_code, existing['id']))
        else:
            # Insert
            cursor.execute("""
                INSERT INTO company_info (name, tax_id, address, phone, branch_code)
                VALUES (%s, %s, %s, %s, %s)
            """, (name, tax_id, address, phone, branch_code))