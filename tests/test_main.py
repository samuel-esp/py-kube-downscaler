import os.path
import re
from unittest.mock import MagicMock

import pytest

from kube_downscaler.main import main


@pytest.fixture
def kubeconfig(tmpdir):
    kubeconfig = tmpdir.join("kubeconfig")
    kubeconfig.write(
        """
apiVersion: v1
clusters:
- cluster: {server: 'https://localhost:9443'}
  name: test
contexts:
- context: {cluster: test}
  name: test
current-context: test
kind: Config
    """
    )
    return kubeconfig


def test_main(kubeconfig, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda x: str(kubeconfig))

    mock_scale = MagicMock()
    monkeypatch.setattr("kube_downscaler.main.scale", mock_scale)

    main(["--dry-run", "--once"])

    mock_scale.assert_called_once()


def test_main_with_leader_election(kubeconfig, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda x: str(kubeconfig))
    monkeypatch.setattr("kube_downscaler.main.get_hostname", lambda: "lock-name")
    monkeypatch.setattr("kube_downscaler.main.get_current_namespace", lambda: "lock-namespace")

    mock_config_class = MagicMock()
    mock_configmaplock = MagicMock()
    mock_config_class.return_value = mock_configmaplock
    monkeypatch.setattr("kube_downscaler.main.electionconfig.Config", mock_config_class)

    graceful_exit_mock = MagicMock()
    monkeypatch.setattr("kube_downscaler.main.shutdown.GracefulShutdown", lambda: graceful_exit_mock)

    mock_run_loop = MagicMock()
    monkeypatch.setattr("kube_downscaler.main.run_loop", mock_run_loop)

    mock_scale = MagicMock()
    monkeypatch.setattr("kube_downscaler.main.scale", mock_scale)

    # Adjust the lambda properly
    mock_leaderelection = MagicMock()
    monkeypatch.setattr(
        "kube_downscaler.main.leaderelection.LeaderElection",
        lambda config: mock_leaderelection(config)  # Ensure it's calling the mock with the config
    )

    # Now define the config and onstarted_leading behavior
    leader_election_config = mock_config_class(
        mock_configmaplock,
        lease_duration=30,
        renew_deadline=20,
        retry_period=5,
        onstarted_leading=lambda: mock_run_loop(),
        onstopped_leading=graceful_exit_mock.exit_gracefully,
    )

    leader_election_instance = mock_leaderelection(leader_election_config)
    leader_election_instance.run = MagicMock(side_effect=lambda: leader_election_instance.onstarted_leading)

    main(["--dry-run", "--once"])

    leader_election_instance.run.assert_called_once()
    graceful_exit_mock.exit_gracefully.assert_not_called()
    leader_election_instance.onstarted_leading.assert_called_once()
    mock_run_loop.assert_called_once()
    mock_scale.assert_called_once()


def test_main_continue_on_failure(kubeconfig, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda x: str(kubeconfig))

    mock_shutdown = MagicMock()
    mock_handler = MagicMock()
    mock_handler.shutdown_now = False
    mock_shutdown.GracefulShutdown.return_value = mock_handler

    calls = []

    def mock_scale(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise Exception("scale fails on first run")
        elif len(calls) == 2:
            mock_handler.shutdown_now = True

    monkeypatch.setattr("kube_downscaler.main.scale", mock_scale)
    monkeypatch.setattr("kube_downscaler.main.shutdown", mock_shutdown)

    main(["--dry-run", "--interval=0"])

    assert len(calls) == 2


def test_main_exclude_namespaces(kubeconfig, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda x: str(kubeconfig))

    mock_scale = MagicMock()
    monkeypatch.setattr("kube_downscaler.main.scale", mock_scale)

    main(["--dry-run", "--once", "--exclude-namespaces=foo,.*-infra-.*"])

    mock_scale.assert_called_once()
    assert mock_scale.call_args.kwargs["exclude_namespaces"] == frozenset(
        [re.compile("foo"), re.compile(".*-infra-.*")]
    )


def test_main_matching_labels(kubeconfig, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda x: str(kubeconfig))

    mock_scale = MagicMock()
    monkeypatch.setattr("kube_downscaler.main.scale", mock_scale)

    main(["--dry-run", "--once", "--matching-labels=foo=bar,.*-type-.*=db"])

    mock_scale.assert_called_once()
    assert mock_scale.call_args.kwargs["matching_labels"] == frozenset(
        [re.compile("foo=bar"), re.compile(".*-type-.*=db")]
    )
