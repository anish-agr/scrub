import unittest
from unittest.mock import Mock, patch

from .perceptron import APIError
from .sessions import PolicySession


class SessionTests(unittest.TestCase):
    @patch("arm.sessions.Inference")
    @patch("arm.sessions.Perceptron")
    def test_grant_session_reset_delete_and_contract_pin(self, control_class, inference_class):
        control, inference = control_class.return_value, inference_class.return_value
        control.contract.return_value = {"contract_id": "verified-test-contract", "contract": {}}

        def grant(deployment, session_id):
            return {"session_id": session_id, "endpoint_url": "https://gpu.example/infer",
                    "application_session_token": "application-test", "modal_session_token": "modal-test"}

        control.grant.side_effect = grant

        def create(deployment, instruction, contract_id):
            session_id = control.grant.call_args.args[1]
            return {"session_id": session_id, "contract_id": contract_id}

        inference.create_session.side_effect = create
        session = PolicySession("deployment", "pick the hemostat", "verified-test-contract")
        self.assertTrue(session.session_id.startswith("scrub-"))
        inference.create_session.assert_called_once_with("deployment", "pick the hemostat", "verified-test-contract")
        session.reset()
        inference.reset.assert_called_once_with(session.session_id)
        session.close()
        inference.delete.assert_called_once_with(session.session_id)
        inference.close.assert_called_once()
        control.close.assert_called_once()

    @patch("arm.sessions.Perceptron")
    def test_changed_contract_fails_before_grant(self, control_class):
        control = control_class.return_value
        control.contract.return_value = {"contract_id": "unexpected"}
        with self.assertRaisesRegex(APIError, "not pinned"):
            PolicySession("deployment", "pick the hemostat", "verified")
        control.grant.assert_not_called()
        control.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
