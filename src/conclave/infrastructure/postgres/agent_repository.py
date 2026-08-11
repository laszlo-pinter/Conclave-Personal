# src/conclave/infrastructure/postgres/agent_repository.py

from datetime import datetime, UTC

from conclave.domain.agent import Agent
from conclave.infrastructure.crypto import CryptoService


class PostgresAgentRepository:
    def __init__(self, connection, crypto: CryptoService) -> None:
        self._connection = connection
        self._crypto = crypto

    def save(self, agent: Agent) -> None:
        enc = self._crypto.encrypt(agent.api_key) if agent.api_key else ""
        with self._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agents
                    (id, name, provider, model, api_key_enc, role, topic,
                     system_prompt, preset, api_url, response_path,
                     message_format, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name           = EXCLUDED.name,
                    provider       = EXCLUDED.provider,
                    model          = EXCLUDED.model,
                    api_key_enc    = EXCLUDED.api_key_enc,
                    role           = EXCLUDED.role,
                    topic          = EXCLUDED.topic,
                    system_prompt  = EXCLUDED.system_prompt,
                    preset         = EXCLUDED.preset,
                    api_url        = EXCLUDED.api_url,
                    response_path  = EXCLUDED.response_path,
                    message_format = EXCLUDED.message_format
                """,
                (
                    agent.id, agent.name, agent.provider, agent.model,
                    enc, agent.role, agent.topic, agent.system_prompt,
                    agent.preset, agent.api_url, agent.response_path,
                    agent.message_format, agent.created_at,
                ),
            )
        self._connection.commit()

    def get(self, agent_id: str) -> Agent | None:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT id, name, provider, model, api_key_enc, role, topic, "
                "system_prompt, created_at, preset, api_url, response_path, message_format "
                "FROM agents WHERE id = %s",
                (agent_id,),
            )
            row = cur.fetchone()
        return self._row_to_agent(row) if row else None

    def list_all(self) -> list[Agent]:
        with self._connection.cursor() as cur:
            cur.execute(
                "SELECT id, name, provider, model, api_key_enc, role, topic, "
                "system_prompt, created_at, preset, api_url, response_path, message_format "
                "FROM agents ORDER BY created_at ASC"
            )
            rows = cur.fetchall()
        return [self._row_to_agent(r) for r in rows]

    def delete(self, agent_id: str) -> None:
        with self._connection.cursor() as cur:
            cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
        self._connection.commit()

    def _row_to_agent(self, row) -> Agent:
        enc = row[4]
        api_key = self._crypto.decrypt(enc) if enc else ""
        created_at = row[8] if isinstance(row[8], datetime) else datetime.fromisoformat(row[8])
        return Agent(
            id=row[0], name=row[1], provider=row[2], model=row[3],
            api_key=api_key, role=row[5], topic=row[6],
            system_prompt=row[7], created_at=created_at,
            preset=row[9] if len(row) > 9 else "",
            api_url=row[10] if len(row) > 10 else "",
            response_path=row[11] if len(row) > 11 else "",
            message_format=row[12] if len(row) > 12 else "standard",
        )
