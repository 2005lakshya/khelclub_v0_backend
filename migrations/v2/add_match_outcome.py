#!/usr/bin/env python3
"""
Migration: add match outcome columns (outcome, outcome_reason, outcome_decided_by,
outcome_decided_at) to the `match` table.

Safe to run more than once: only missing columns are added.
Same change as add_match_outcome.sql, for environments where running Python is easier.

Usage (from the backend root):  python migrations/v2/add_match_outcome.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from config import Config
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import bindparam, text

COLUMNS = {
    'outcome': "ADD COLUMN `outcome` VARCHAR(20) NOT NULL DEFAULT 'normal'",
    'outcome_reason': "ADD COLUMN `outcome_reason` VARCHAR(255) NULL",
    'outcome_decided_by': "ADD COLUMN `outcome_decided_by` VARCHAR(100) NULL",
    'outcome_decided_at': "ADD COLUMN `outcome_decided_at` DATETIME NULL",
}


def run_migration():
    app = Flask(__name__)
    app.config.from_object(Config)
    db = SQLAlchemy(app)

    with app.app_context():
        try:
            result = db.session.execute(text("""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = :db_name
                AND TABLE_NAME = 'match'
                AND COLUMN_NAME IN :names
            """).bindparams(bindparam('names', expanding=True)),
                {'db_name': Config.DB_NAME, 'names': list(COLUMNS)})
            existing = {row[0] for row in result.fetchall()}

            to_add = [ddl for name, ddl in COLUMNS.items() if name not in existing]
            if not to_add:
                print("All outcome columns already exist. Migration not needed.")
                return

            alter_sql = f"ALTER TABLE `match` {', '.join(to_add)}"
            print(f"Executing: {alter_sql}")
            db.session.execute(text(alter_sql))
            db.session.commit()
            print("Migration completed successfully!")
        except Exception as e:
            print(f"Error running migration: {str(e)}")
            db.session.rollback()
            raise


if __name__ == '__main__':
    run_migration()
