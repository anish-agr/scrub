import json

from ledger import stats

if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
