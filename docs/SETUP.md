# Setup

## Everyone, first 15 minutes

1. `git clone https://github.com/anish-agr/dubhacks-2026.git`.
2. Copy `.env.example` to `.env` at the repo root. Fill it from the keys Brandon, Anish and Caiden post in the group chat. **Never commit `.env`. Never paste a key into a file that's tracked or into an agent chat that writes files.**
3. Install Python 3.10 (the version LeRobot uses), Node 20+, and Git.
4. Make a virtual environment at the repo root, then install only your folders' requirements:
    ```
    python -m venv .venv
    .venv\Scripts\activate          (Windows)
    source .venv/bin/activate       (Mac)
    pip install -r controller/requirements.txt -r <your folder>/requirements.txt
    ```
    The controller is needed by everyone for testing, since it runs the fake arm.
5. Open the repo in your tool and paste the start prompt from `docs/PROMPTS.md`.

## Per person

| Who | Installs | Accounts and keys |
| --- | --- | --- |
| Anish | LeRobot with Feetech extras (`pip install -e ".[feetech]"` in a LeRobot checkout) | Hugging Face write token (huggingface.co/settings/tokens) |
| Caiden | FastAPI, uvicorn; Node with Photon's SDK; cloudflared or ngrok for the tunnel | Photon project and SMS number (app.photon.codes), ElevenLabs agent and API key, Gemini API key (Google AI Studio) |
| Brandon | OpenCV, MediaPipe, requests | The Perceptron API key: posts it in the chat. Later, the $50 vision credits (code DUBHACKS26: enter $50.00 at checkout, it totals $0) |
| Evan | pymongo | MongoDB Atlas free cluster (mlh.link/mongodb), Vultr with MLH credits, a GoDaddy domain through MLH's GoDaddy Registry offer (Saturday night) |

## Status of accounts

| Thing | Status | Who |
| --- | --- | --- |
| Gemini API key | have it | Anish |
| ElevenLabs API key | have it | Anish |
| Cursor Pro | have it | everyone except Anish |
| Perceptron arm slot | have it | team |
| Perceptron API key | have it | Brandon |
| Perceptron vision credits | later: redeem code DUBHACKS26 | Brandon |
| Photon SMS number | waiting on Photon's reply on Discord about the card. Backup: a teammate's card, since the $100 credit covers the weekend | Caiden |
| Hugging Face token | needed if LeRobot pushes datasets to the Hub. Otherwise record with `--dataset.push_to_hub=false` | Anish |
| MongoDB Atlas | to do | Evan |
| Vultr | to do, Saturday night | Evan |
| GoDaddy domain | to do, Saturday night | Evan |
| GitHub access | done | everyone |
| Devpost team | done | everyone |
| MLH Commit Fellowship form | Sunday, after submitting | Anish |

## Things to have at the table

- Operating room: scalpel handle (no blade), hemostat, Mayo scissors
- Dental: mouth mirror, explorer, cotton pliers
- Bench: needle-nose pliers, wire cutters, hex key
- A tray or box per setting, a blue towel under the tray, painter's tape for positions
- The brightest lamp we have; a lux-meter phone app
- Nitrile gloves in two sizes (the hand tracker gets tested with them)
- A USB webcam and a way to mount it overhead, if Perceptron's setup has no overhead camera we can use
- A phone for the speakerphone call to the Photon number
- A power strip and an extension cord; laptop and phone chargers
