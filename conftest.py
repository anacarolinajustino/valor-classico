"""
Configuração global de testes — adiciona a raiz do projeto ao sys.path.
"""
import sys
from pathlib import Path

import pytest

from app import app

# Garantir que imports de 'src.*' funcionam sem instalação do pacote
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture()
def client():
	app.config["TESTING"] = True
	with app.test_client() as test_client:
		yield test_client
