"""Serve the original saved-output viewer without loading the inference engine."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root=Path(__file__).resolve().parent/'static'
handler=partial(SimpleHTTPRequestHandler,directory=str(root))
print('Saved SENBA demo: http://127.0.0.1:8942',flush=True)
ThreadingHTTPServer(('127.0.0.1',8942),handler).serve_forever()
