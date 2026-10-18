import json
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from ledger.serve import serve

        serve()
    elif len(sys.argv) > 1 and sys.argv[1] == "log":
        from ledger.logbook import log_cli

        log_cli(sys.argv[2:])
    else:
        from ledger import stats

        print(json.dumps(stats(), indent=2))
