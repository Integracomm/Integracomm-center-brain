"""Registro de agentes — encaixar um novo agente = registrar aqui.

A casca itera sobre o registry para agendar execuções e montar o painel
(cada agente aparece sob o papel declarado em ``Agent.role``). Nenhuma
outra parte da casca precisa conhecer agentes concretos.
"""
from __future__ import annotations

from .base import Agent

_REGISTRY: dict[str, Agent] = {}


def register(agent: Agent) -> Agent:
    if not getattr(agent, "key", None):
        raise ValueError("Agente precisa de um 'key' estável.")
    if agent.key in _REGISTRY:
        raise ValueError(f"Agente '{agent.key}' já registrado.")
    _REGISTRY[agent.key] = agent
    return agent


def get(key: str) -> Agent:
    return _REGISTRY[key]


def all_agents() -> list[Agent]:
    return list(_REGISTRY.values())


def agents_for_role(role: str) -> list[Agent]:
    """RBAC: admin vê todos; gestor vê só os do seu papel."""
    if role == "admin":
        return all_agents()
    return [a for a in _REGISTRY.values() if a.role == role]
