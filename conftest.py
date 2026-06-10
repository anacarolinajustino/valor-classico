"""
Configuração global de testes — adiciona a raiz do projeto ao sys.path.
"""
import sys
from pathlib import Path

# Garantir que imports de 'src.*' funcionam sem instalação do pacote
sys.path.insert(0, str(Path(__file__).parent))
