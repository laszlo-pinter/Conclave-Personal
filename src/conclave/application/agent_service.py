# src/conclave/application/agent_service.py

from conclave.application.ports import AgentRepository
from conclave.domain.agent import Agent
from conclave.domain.errors import AgentAlreadyExists, AgentNotFound


class AgentService:
    def __init__(self, agent_repository: AgentRepository):
        self._repo = agent_repository

    def create_agent(self, agent: Agent) -> Agent:
        if self._repo.get(agent.id) is not None:
            raise AgentAlreadyExists(agent.id)
        self._repo.save(agent)
        return agent

    def update_agent(self, agent: Agent) -> Agent:
        if self._repo.get(agent.id) is None:
            raise AgentNotFound(agent.id)
        self._repo.save(agent)
        return agent

    def get_agent(self, agent_id: str) -> Agent:
        agent = self._repo.get(agent_id)
        if agent is None:
            raise AgentNotFound(agent_id)
        return agent

    def list_agents(self) -> list[Agent]:
        return self._repo.list_all()

    def delete_agent(self, agent_id: str) -> None:
        if self._repo.get(agent_id) is None:
            raise AgentNotFound(agent_id)
        self._repo.delete(agent_id)

    def upsert_agent(self, agent: Agent) -> Agent:
        """Erstellt oder aktualisiert – ohne Fehler bei Duplikaten."""
        self._repo.save(agent)
        return agent
