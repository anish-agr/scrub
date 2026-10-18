"""pytest: controller tests never write the shared ledger (ledger.log goes to MongoDB, Tiger and Backboard when
their keys are set, so a test Controller with fake_arm=False showed up in Atlas as real runs at 0.4 s)."""
from controller import core

core.ledger = None  # tests that need a ledger swap in their own fake and restore None
