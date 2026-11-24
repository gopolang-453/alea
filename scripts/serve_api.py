#!/usr/bin/env python3
"""Run the ALEA prediction API (Stage 11).

Configuration (flags override environment variables):
  ALEA_LEDGER                 path to the prospective ledger SQLite (required to exist)
  ALEA_REGISTRY               path to config/model_registry.json
  ALEA_HOST / ALEA_PORT       bind address (default 127.0.0.1:8080)
  ALEA_MAX_STALENESS_HOURS    /health reports "degraded" beyond this run age (default 216)
  ALEA_LOG_FILE               optional JSON-lines request log file

The server is a threaded stdlib WSGI server, adequate for low request volume
behind a reverse proxy. It opens the ledger read-only on every request, so
the scheduled pipeline can update the ledger file without restarting it.
No credentials are needed or read.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage11.api import ForecastAPI  # noqa: E402


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):  # request logging is done by the app as JSON
        pass


def build_app(args) -> ForecastAPI:
    ledger = Path(args.ledger)
    if not ledger.is_file():
        raise SystemExit(f"ledger not found: {ledger} (refusing to start against a missing store)")
    return ForecastAPI(ledger, args.registry, root=ROOT, max_staleness_hours=args.max_staleness_hours)


def main(argv=None) -> int:
    env = os.environ.get
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", default=env("ALEA_LEDGER", str(ROOT / "results/prospective/ledger.sqlite")))
    parser.add_argument("--registry", default=env("ALEA_REGISTRY", str(ROOT / "config/model_registry.json")))
    parser.add_argument("--host", default=env("ALEA_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(env("ALEA_PORT", "8080")))
    parser.add_argument("--max-staleness-hours", type=float, default=float(env("ALEA_MAX_STALENESS_HOURS", "216")))
    parser.add_argument("--log-file", default=env("ALEA_LOG_FILE"))
    args = parser.parse_args(argv)
    handlers = [logging.StreamHandler(sys.stderr)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        handlers=handlers)
    app = build_app(args)
    with make_server(args.host, args.port, app, server_class=ThreadingWSGIServer,
                     handler_class=QuietHandler) as server:
        logging.getLogger("alea.api").info("serving on http://%s:%s (ledger %s)", args.host,
                                           server.server_port, args.ledger)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
