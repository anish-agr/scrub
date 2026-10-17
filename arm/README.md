# arm

Owner: Anish. Tasks A3, A6, A7 in `docs/TASKS.md`. Steps in `docs/ARM.md`.

`real_arm.py` implements the arm interface in `docs/CONTRACTS.md` with LeRobot and the fine-tuned Isaac 0.5 policy. `rig.json` holds the home, carry and safe-spot poses and the handoff region. Only the controller imports this folder.

Done when: the controller runs a real "pick the hemostat" with `--real-arm`, and `move_to` reaches test points within about 2 cm.

## Robotics API (A2)

Install: `python -m pip install -r arm/requirements.txt`. Run from the repo root:

```text
python -m arm.train capabilities
python -m arm.train register-hf <user>/scrub --name scrub --idempotency-key scrub-hf-v1
python -m arm.train upload <dataset-root> --name scrub --idempotency-key scrub-upload-v1
python -m arm.train status dataset <dataset-id>
python -m arm.train validation <dataset-id>
python -m arm.train train <dataset-id> --idempotency-key scrub-run-1 --confirmed-replay-and-cadence
python -m arm.train follow <job-id>
python -m arm.train deployments
python -m arm.train contract <deployment-id>
python -m unittest arm.test_perceptron -v
```

Put `PERCEPTRON_TEAM_API_KEY` in the root `.env`, never in a command or git.
Use the same idempotency key AND body when retrying a logical registration or
job submission. No automatic retries: stale predicts must not be resent.
Training requires a ready dataset and explicit confirmation that replay/cadence
were checked. Read validation evidence before submitting; only two successful
jobs are budgeted. `follow` reads logs/metrics with their returned cursors,
prints checkpoint/deployment information on job completion; export can still be
pending, so use `deployments` until the desired deployment is ready.

Control and inference have separate HTTP clients. Inference uses a grant's
`endpoint_url`, falling back to `/v1/inference` on the control host per workshop
notes. This routing is offline-tested, not yet confirmed with a live grant.
Signed uploads use a third, unauthenticated client; a 303 is followed by GET
without replaying upload bytes or headers. Local datasets are read only when
the operator explicitly invokes `upload`; no dataset was inspected in setup.
