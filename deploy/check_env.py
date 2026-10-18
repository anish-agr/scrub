"""List .env keys per laptop and probe each service. Never prints a secret."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# 1x1 gray JPEG. The detect call only checks that the key is accepted.
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb00430008060607060508070707090908"
    "0a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c303134"
    "34341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101"
    "010100000000000000000102030405060708090a0bffc400b510000201030302040305050404"
    "0000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433"
    "627282090a161718191a25262728292a3435363738393a434445464748494a53545556575859"
    "5a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5"
    "a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6"
    "e7e8e9eaf1f2f3f4f5f6f7f8f9faffda00080001000100003f00fbffd9"
)

# name, required. Optional keys are listed but a missing one is not a hole.
ROLES = {
    "arm laptop": {
        "controller": [("CONTROLLER_URL", False)],
        "arm": [
            ("PERCEPTRON_TEAM_API_KEY", True),
            ("PERCEPTRON_DEPLOYMENT_ID", True),
            ("HF_TOKEN", True),
            ("SO101_PORT", True),
        ],
        "ledger": [
            ("MONGODB_URI", True),
            ("TIGER_DATABASE_URL", True),
            ("BACKBOARD_API_KEY", True),
            ("BACKBOARD_ASSISTANT_ID", True),
        ],
        "vision": [
            ("PERCEPTRON_API_KEY", True),
            ("CAMERA_INDEX", False),
            ("VISION_URL", False),
            ("SIM_URL", False),
        ],
    },
    "voice laptop": {
        "voice": [
            ("GEMINI_API_KEY", True),
            ("ELEVENLABS_API_KEY", True),
            ("ELEVENLABS_AGENT_ID", True),
            ("VOICE_LLM_SECRET", False),
            ("PHOTON_API_KEY", True),
            ("PHOTON_PROJECT_ID", True),
            ("PHOTON_SUMMARY_TO", False),
            ("SCRUB_PUBLIC_URL", False),
            ("SCRUB_SERVER_IP", False),
            ("VOICE_PORT", False),
            ("CONTROLLER_URL", False),
        ],
    },
}


def load() -> None:
    load_dotenv(ROOT / ".env")


# Same fallbacks as voice/src/config.ts: the Spectrum names work when the Photon names are empty.
ALIASES = {"PHOTON_PROJECT_ID": "SPECTRUM_PROJECT_ID", "PHOTON_API_KEY": "SPECTRUM_PROJECT_SECRET"}


def value(name: str) -> str:
    """The key's value, or its alias's. Never print the result."""
    found = os.getenv(name, "").strip()
    if not found and name in ALIASES:
        found = os.getenv(ALIASES[name], "").strip()
    return found


def present(name: str) -> bool:
    return bool(value(name))


def redact(text: str) -> str:
    cleaned = text.replace("\n", " ")
    for name in os.environ:
        value = os.environ.get(name) or ""
        if len(value) >= 6 and value in cleaned:
            cleaned = cleaned.replace(value, "***")
    return cleaned[:160]


def row(name: str, ok: bool, detail: str) -> tuple[str, str, str]:
    return name, "PASS" if ok else "FAIL", redact(detail)


def need(name: str) -> tuple[str, str, str] | None:
    if present(name):
        return None
    return row(name, False, f"missing {name}")


def http_ok(response: httpx.Response) -> tuple[bool, str]:
    if response.status_code == 200:
        return True, "HTTP 200"
    return False, f"HTTP {response.status_code}"


def check_robotics() -> tuple[str, str, str]:
    blocked = need("PERCEPTRON_TEAM_API_KEY")
    if blocked:
        return ("Perceptron robotics", *blocked[1:])
    try:
        response = httpx.get(
            "https://robotics.perceptron.inc/v1/capabilities",
            headers={"Authorization": f"Bearer {os.environ['PERCEPTRON_TEAM_API_KEY']}"},
            timeout=20,
        )
        ok, detail = http_ok(response)
        return row("Perceptron robotics", ok, detail)
    except httpx.HTTPError as exc:
        return row("Perceptron robotics", False, type(exc).__name__)


def detect_verdict(status: int) -> tuple[bool, str]:
    """The test image is 1x1, so a good key can answer 400. 401 and 403 mean the key is bad."""
    if status == 400:
        return True, "key ok, HTTP 400 on test image"
    if status == 200:
        return True, "HTTP 200"
    return False, f"HTTP {status}"


def check_detect() -> tuple[str, str, str]:
    blocked = need("PERCEPTRON_API_KEY")
    if blocked:
        return ("Perceptron detect", *blocked[1:])
    import base64

    payload = {
        "media": {
            "type": "image",
            "image_url": "data:image/jpeg;base64," + base64.b64encode(TINY_JPEG).decode("ascii"),
        },
        "categories": ["hemostat"],
        "config": {"output": "box", "reasoning_effort": "none"},
    }
    for attempt in (1, 2):  # the API sometimes takes over 20 s on the first call; vision itself sees 2 s
        try:
            response = httpx.post(
                "https://api.perceptron.inc/v1/detect",
                json=payload,
                headers={"Authorization": f"Bearer {os.environ['PERCEPTRON_API_KEY']}"},
                timeout=30,
            )
            ok, detail = detect_verdict(response.status_code)
            return row("Perceptron detect", ok, detail)
        except httpx.HTTPError as exc:
            if attempt == 2 or not isinstance(exc, httpx.TimeoutException):
                return row("Perceptron detect", False, type(exc).__name__)


def check_deployment() -> tuple[str, str, str]:
    """--real-arm needs a deployment that exists. The id in .env is only a name until run 1 writes it."""
    blocked = need("PERCEPTRON_TEAM_API_KEY") or need("PERCEPTRON_DEPLOYMENT_ID")
    if blocked:
        return ("Perceptron deployment", *blocked[1:])
    try:
        response = httpx.get(
            "https://robotics.perceptron.inc/v1/deployments",
            headers={"Authorization": f"Bearer {os.environ['PERCEPTRON_TEAM_API_KEY']}"},
            timeout=20,
        )
        if response.status_code != 200:
            return row("Perceptron deployment", False, f"HTTP {response.status_code}")
        ids = [str(item.get("id") or item.get("deployment_id")) for item in response.json().get("items", [])]
        found = os.environ["PERCEPTRON_DEPLOYMENT_ID"].strip() in ids
        return row("Perceptron deployment", found, "found" if found else f"id not among {len(ids)} deployments")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        return row("Perceptron deployment", False, type(exc).__name__)


def check_public() -> tuple[str, str, str]:
    """Vultr page: SCRUB_PUBLIC_URL (the domain) or SCRUB_SERVER_IP, and it must serve /api/stats from the ledger."""
    base = os.getenv("SCRUB_PUBLIC_URL", "").strip().rstrip("/")
    if not base and os.getenv("SCRUB_SERVER_IP", "").strip():
        base = "http://" + os.environ["SCRUB_SERVER_IP"].strip()
    if not base:
        return row("Vultr public page", False, "missing SCRUB_PUBLIC_URL or SCRUB_SERVER_IP")
    try:
        response = httpx.get(base + "/api/stats", timeout=10)
        ok, detail = http_ok(response)
        return row("Vultr public page", ok, detail)
    except httpx.HTTPError as exc:
        return row("Vultr public page", False, type(exc).__name__)


def check_gemini() -> tuple[str, str, str]:
    blocked = need("GEMINI_API_KEY")
    if blocked:
        return ("Gemini", *blocked[1:])
    try:
        response = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            timeout=20,
        )
        ok, detail = http_ok(response)
        return row("Gemini", ok, detail)
    except httpx.HTTPError as exc:
        return row("Gemini", False, type(exc).__name__)


def check_elevenlabs() -> tuple[str, str, str]:
    blocked = need("ELEVENLABS_API_KEY")
    if blocked:
        return ("ElevenLabs", *blocked[1:])
    try:
        response = httpx.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
            timeout=20,
        )
        ok, detail = http_ok(response)
        if ok and present("ELEVENLABS_AGENT_ID"):
            agent = httpx.get(
                "https://api.elevenlabs.io/v1/convai/agents/" + os.environ["ELEVENLABS_AGENT_ID"].strip(),
                headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                timeout=20,
            )
            if agent.status_code != 200:
                return row("ElevenLabs", False, f"user ok, agent HTTP {agent.status_code}")
        return row("ElevenLabs", ok, detail)
    except httpx.HTTPError as exc:
        return row("ElevenLabs", False, type(exc).__name__)


def check_photon() -> tuple[str, str, str]:
    for name in ("PHOTON_API_KEY", "PHOTON_PROJECT_ID"):
        blocked = need(name)
        if blocked:
            return ("Photon", *blocked[1:])
    project = value("PHOTON_PROJECT_ID")
    try:
        response = httpx.get(
            f"https://api.photon.codes/v1/projects/{project}",
            headers={"Authorization": f"Bearer {value('PHOTON_API_KEY')}"},
            timeout=20,
        )
        ok, detail = http_ok(response)
        return row("Photon", ok, detail)
    except httpx.HTTPError as exc:
        return row("Photon", False, type(exc).__name__)


def check_mongo() -> tuple[str, str, str]:
    blocked = need("MONGODB_URI")
    if blocked:
        return ("MongoDB Atlas", *blocked[1:])
    try:
        from pymongo import MongoClient
    except ImportError:
        return row("MongoDB Atlas", False, "pymongo is not installed")
    try:
        client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
        client.close()
        return row("MongoDB Atlas", True, "ping ok")
    except Exception as exc:
        return row("MongoDB Atlas", False, type(exc).__name__)


def check_tiger() -> tuple[str, str, str]:
    blocked = need("TIGER_DATABASE_URL")
    if blocked:
        return ("Tiger Data", *blocked[1:])
    try:
        import psycopg
    except ImportError:
        return row("Tiger Data", False, "psycopg is not installed")
    try:
        with psycopg.connect(os.environ["TIGER_DATABASE_URL"], connect_timeout=8) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        return row("Tiger Data", True, "connected")
    except Exception as exc:
        return row("Tiger Data", False, type(exc).__name__)


def check_backboard() -> tuple[str, str, str]:
    if not present("BACKBOARD_API_KEY") or not present("BACKBOARD_ASSISTANT_ID"):
        return row("Backboard", False, "missing BACKBOARD_API_KEY or BACKBOARD_ASSISTANT_ID")
    assistant = os.environ["BACKBOARD_ASSISTANT_ID"].strip()
    try:
        response = httpx.get(
            f"https://app.backboard.io/api/assistants/{assistant}/memories",
            headers={"X-API-Key": os.environ["BACKBOARD_API_KEY"].strip()},
            params={"page": 1, "page_size": 1},
            timeout=15,
        )
        if response.status_code in (200, 201):
            return row("Backboard", True, "HTTP 200")
        return row("Backboard", False, f"HTTP {response.status_code}")
    except httpx.HTTPError as exc:
        return row("Backboard", False, type(exc).__name__)


def check_hf() -> tuple[str, str, str]:
    blocked = need("HF_TOKEN")
    if blocked:
        return ("Hugging Face", *blocked[1:])
    try:
        response = httpx.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {os.environ['HF_TOKEN']}"},
            timeout=20,
        )
        ok, detail = http_ok(response)
        return row("Hugging Face", ok, detail)
    except httpx.HTTPError as exc:
        return row("Hugging Face", False, type(exc).__name__)


VULTR_PAGE = "http://144.202.95.111/"


def check_page(name: str, url: str) -> tuple[str, str, str]:
    """The judge page. A 200 that contains the Scrub title counts as up."""
    if not url:
        return row(name, False, "missing SCRUB_PUBLIC_URL")
    try:
        response = httpx.get(url, timeout=8, follow_redirects=True)
    except httpx.HTTPError as exc:
        return row(name, False, type(exc).__name__)
    text = response.text[:400]
    if response.status_code == 200 and "Scrub" in text:
        return row(name, True, "HTTP 200")
    return row(name, False, f"HTTP {response.status_code}")


def check_port(name: str, url: str) -> tuple[str, str, str]:
    try:
        response = httpx.get(url, timeout=3)
        ok, detail = http_ok(response)
        return row(name, ok, detail)
    except httpx.HTTPError as exc:
        return row(name, False, type(exc).__name__)


def key_lines() -> list[str]:
    lines = []
    for role, services in ROLES.items():
        lines.append(role)
        for service, keys in services.items():
            lines.append(f"  {service}")
            for name, required in keys:
                if present(name):
                    state = "set" if os.getenv(name, "").strip() else f"set (as {ALIASES[name]})"
                elif required:
                    state = "MISSING"
                else:
                    state = "unset, has a default"
                lines.append(f"    {name:<28} {state}")
    return lines


def live_rows() -> list[tuple[str, str, str]]:
    controller = os.getenv("CONTROLLER_URL", "http://localhost:8000").rstrip("/")
    vision = os.getenv("VISION_URL", "http://localhost:8001").rstrip("/")
    voice_port = os.getenv("VOICE_PORT", "3000").strip() or "3000"
    return [
        check_robotics(),
        check_detect(),
        check_deployment(),
        check_gemini(),
        check_elevenlabs(),
        check_photon(),
        check_mongo(),
        check_tiger(),
        check_backboard(),
        check_hf(),
        check_public(),
        check_port("controller :8000", controller + "/state"),
        check_port("vision :8001", vision + "/health"),
        check_port("voice :3000", f"http://127.0.0.1:{voice_port}/health"),
        check_page("public page", VULTR_PAGE),
        check_page("public url", value("SCRUB_PUBLIC_URL")),
    ]


def format_table(rows: list[tuple[str, str, str]]) -> str:
    header = ("service", "result", "detail")
    widths = [len(part) for part in header]
    for cells in rows:
        for index, cell in enumerate(cells):
            widths[index] = max(widths[index], len(cell))
    def line(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells))
    body = [line(header), line(tuple("-" * width for width in widths))]
    body.extend(line(cells) for cells in rows)
    return "\n".join(body)


def main() -> None:
    load()
    print("\n".join(key_lines()))
    print()
    print(format_table(live_rows()))
    sys.exit(0)


if __name__ == "__main__":
    main()
