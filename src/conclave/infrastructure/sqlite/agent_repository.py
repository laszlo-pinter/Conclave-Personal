# src/conclave/infrastructure/sqlite/agent_repository.py

import sqlite3
from datetime import datetime, UTC

from conclave.domain.agent import Agent
from conclave.infrastructure.crypto import CryptoService


class SQLiteAgentRepository:
    def __init__(self, connection: sqlite3.Connection, crypto: CryptoService) -> None:
        self._connection = connection
        self._crypto = crypto

    def save(self, agent: Agent) -> None:
        enc = self._crypto.encrypt(agent.api_key) if agent.api_key else ""
        self._connection.execute(
            """
            INSERT INTO agents (id, name, provider, model, api_key_enc, role, topic,
                                system_prompt, preset, api_url, response_path,
                                message_format, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name           = excluded.name,
                provider       = excluded.provider,
                model          = excluded.model,
                api_key_enc    = excluded.api_key_enc,
                role           = excluded.role,
                topic          = excluded.topic,
                system_prompt  = excluded.system_prompt,
                preset         = excluded.preset,
                api_url        = excluded.api_url,
                response_path  = excluded.response_path,
                message_format = excluded.message_format
            """,
            (
                agent.id, agent.name, agent.provider, agent.model, enc,
                agent.role, agent.topic, agent.system_prompt,
                agent.preset, agent.api_url, agent.response_path,
                agent.message_format, agent.created_at.isoformat(),
            ),
        )
        self._connection.commit()

    def get(self, agent_id: str) -> Agent | None:
        row = self._connection.execute(
            "SELECT id, name, provider, model, api_key_enc, role, topic, "
            "system_prompt, created_at, preset, api_url, response_path, message_format "
            "FROM agents WHERE id = ?",
            (agent_id,),
        ).fetchone()
        return self._row_to_agent(row) if row else None

    def list_all(self) -> list[Agent]:
        rows = self._connection.execute(
            "SELECT id, name, provider, model, api_key_enc, role, topic, "
            "system_prompt, created_at, preset, api_url, response_path, message_format "
            "FROM agents ORDER BY created_at ASC"
        ).fetchall()
        return [self._row_to_agent(r) for r in rows]

    def delete(self, agent_id: str) -> None:
        self._connection.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        self._connection.commit()

    def _row_to_agent(self, row) -> Agent:
        enc = row[4]
        api_key = self._crypto.decrypt(enc) if enc else ""
        return Agent(
            id=row[0], name=row[1], provider=row[2], model=row[3],
            api_key=api_key, role=row[5], topic=row[6], system_prompt=row[7],
            created_at=datetime.fromisoformat(row[8]),
            preset=row[9] if len(row) > 9 else "",
            api_url=row[10] if len(row) > 10 else "",
            response_path=row[11] if len(row) > 11 else "",
            message_format=row[12] if len(row) > 12 else "standard",
        )
