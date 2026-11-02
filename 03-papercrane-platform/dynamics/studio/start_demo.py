"""Start local SENBA inference with this Python environment and the released checkpoint."""
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
env = os.environ.copy()
env.setdefault('SENBA_ROOT', str(HERE.parent / 'source-original/senba-sprint'))
env['MPLCONFIGDIR'] = str(HERE / 'runtime/matplotlib')
env['PYTHONDONTWRITEBYTECODE'] = '1'
os.execve(sys.executable, [sys.executable, str(HERE / 'server.py'), '--port', '8941'], env)
