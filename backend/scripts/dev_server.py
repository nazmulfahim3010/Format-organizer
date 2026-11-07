"""Run the API for local development.

    python backend/scripts/dev_server.py [--data DIR] [--port 8000]

--data points the server at a separate data folder (database, uploads, generated files), e.g. a
throw-away folder for a test run, so it never touches backend/storage.
"""
import argparse
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="data directory (default: backend/storage)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    if args.data:
        data = os.path.abspath(args.data)
        os.makedirs(data, exist_ok=True)
        os.environ["SMARTDOC_DATA_DIR"] = data
        os.environ["SMARTDOC_DATABASE_URL"] = f"sqlite:///{os.path.join(data, 'smartdoc.db')}"
    os.chdir(BACKEND)
    sys.path.insert(0, BACKEND)
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
