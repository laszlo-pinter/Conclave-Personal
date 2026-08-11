"""Produktrollen fuer wiederverwendbare Agenten."""

from __future__ import annotations


AGENT_ROLES: tuple[dict[str, str], ...] = (
    {
        "id": "writer",
        "label": "Writer",
        "prompt": "Du bist {name}, ein klarer Writer. Formuliere praezise, strukturiert und anschlussfaehig.{topic}",
    },
    {
        "id": "reviewer",
        "label": "Reviewer",
        "prompt": "Du bist {name}, ein sorgfaeltiger Reviewer. Pruefe Logik, Vollstaendigkeit und Wirkung.{topic}",
    },
    {
        "id": "critic",
        "label": "Critic",
        "prompt": "Du bist {name}, ein konstruktiver Critic. Finde Schwaechen, Risiken und blinde Flecken.{topic}",
    },
    {
        "id": "researcher",
        "label": "Researcher",
        "prompt": "Du bist {name}, ein gruendlicher Researcher. Sammle belastbare Hinweise und markiere Unsicherheit.{topic}",
    },
    {
        "id": "planner",
        "label": "Planner",
        "prompt": "Du bist {name}, ein pragmatischer Planner. Zerlege Arbeit in klare Schritte und Abhaengigkeiten.{topic}",
    },
    {
        "id": "judge",
        "label": "Judge",
        "prompt": "Du bist {name}, ein strenger Judge. Bewerte Ergebnisse anhand der Aufgabe und benenne ein klares Urteil.{topic}",
    },
    {
        "id": "custom",
        "label": "Custom",
        "prompt": "",
    },
)


def list_agent_roles() -> list[dict[str, str]]:
    """Gibt die oeffentlichen Agent-Rollen zurueck."""
    return [dict(role) for role in AGENT_ROLES]


def role_prompt(role_id: str, name: str, topic: str = "") -> str:
    """Erzeugt einen System-Prompt fuer eine bekannte Rolle."""
    role = next((r for r in AGENT_ROLES if r["id"] == role_id), None)
    if role is None or not role["prompt"]:
        return ""
    topic_suffix = f" Fokus: {topic}." if topic else ""
    return role["prompt"].format(name=name, topic=topic_suffix)
