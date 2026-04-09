from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings


def _db_path() -> Path:
    settings.support_db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings.support_db_path


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            workspace_id TEXT,
            customer_id TEXT,
            invoice_id TEXT,
            last_question TEXT,
            last_updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS case_turns (
            turn_id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            asked_at TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            escalation_required INTEGER NOT NULL,
            tool_trace_json TEXT NOT NULL,
            action_proposal_json TEXT,
            FOREIGN KEY(case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS case_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            note TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS action_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL,
            result_summary TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS observability_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """
    )


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    _initialize_schema(connection)
    return connection


def describe_db_location(table_name: str, identifier: str | None = None) -> str:
    suffix = table_name if identifier is None else f"{table_name}:{identifier}"
    return f"{_db_path()}#{suffix}"
