"""
Configuração global de testes — adiciona a raiz do projeto ao sys.path.
"""
import os
import sys
from pathlib import Path

import pytest

# IMPORTANTE: força os testes a usar um banco separado do banco de
# desenvolvimento, nunca o DATABASE_URL real do .env. test_persistence.py
# trunca anuncios/historico_precos/search_log antes de cada teste — rodar
# isso contra o banco real apaga os dados coletados.
os.environ["DATABASE_URL"] = (
    "postgresql://valorclassico_local:valorclassico_local@localhost:5432/valorclassicodb_test"
)

from app import app

# Garantir que imports de 'src.*' funcionam sem instalação do pacote
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture()
def client():
	app.config["TESTING"] = True
	with app.test_client() as test_client:
		yield test_client
