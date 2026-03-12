"""Integration test fixtures — mock LLM with canned responses for full pipeline."""

import pytest

from hypomnema.llm.mock import MockLLMClient

_CANNED_RESPONSES: dict[str, dict] = {
    "Quantum": {
        "entities": [
            {"name": "Quantum Computing", "description": "Computing using quantum mechanical phenomena"},
            {"name": "Qubit", "description": "Basic unit of quantum information"},
        ]
    },
    "Neural": {
        "entities": [
            {"name": "Neural Network", "description": "Computing system inspired by biological neural networks"},
            {"name": "Backpropagation", "description": "Algorithm for training neural networks"},
        ]
    },
    "Graph": {
        "entities": [
            {"name": "Graph Theory", "description": "Mathematical study of graphs"},
            {"name": "Vertex", "description": "Fundamental unit of a graph"},
        ]
    },
    "Cryptography": {
        "entities": [
            {"name": "Cryptography", "description": "Practice of secure communication"},
        ]
    },
    "Database": {
        "entities": [
            {"name": "Database Systems", "description": "Organized collection of structured data"},
        ]
    },
    "Normalize these entity names": {"mapping": {}},
    "Source concept:": {"edges": []},
}


@pytest.fixture
def int_llm() -> MockLLMClient:
    return MockLLMClient(responses=_CANNED_RESPONSES)
