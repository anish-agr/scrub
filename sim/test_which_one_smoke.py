"""The offline proof must never reuse another stack's voice endpoint."""
import os
from unittest.mock import patch

import pytest

from sim import which_one_smoke as smoke


def test_occupied_port_is_refused_before_services_or_commands():
    with patch.dict(os.environ), patch.object(smoke.R, "port_busy", return_value=True), \
         patch.object(smoke.R, "bring_up") as start, patch.object(smoke.httpx, "Client") as client:
        with pytest.raises(AssertionError, match="occupied"):
            smoke.run(8300)
        start.assert_not_called()
        client.assert_not_called()
