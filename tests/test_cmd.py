import pytest

from kube_downscaler.cmd import check_include_resources
from kube_downscaler.cmd import get_parser


def test_parse_args():
    config = {
        "NAMESPACE": "default",
        "INCLUDE_RESOURCES": "deployments",
        "GRACE_PERIOD": "600",
        "UPSCALE_PERIOD": "never",
        "DEFAULT_UPTIME": "always",
        "DOWNSCALE_PERIOD": "never",
        "DEFAULT_DOWNTIME": "never",
        "EXCLUDE_NAMESPACES": "kube-system",
        "EXCLUDE_DEPLOYMENTS": "py-kube-downscaler",
        "DOWNTIME_REPLICAS": "0",
        "MATCHING_LABELS": "app=my-app",
        "ADMISSION_CONTROLLER": "kyverno"
    }
    parser = get_parser(config)
    config = parser.parse_args(["--dry-run"])

    assert config.dry_run
    assert config.grace_period == 600


def test_check_include_resources():
    assert check_include_resources("deployments,cronjobs") == "deployments,cronjobs"


def test_check_include_resources_invalid():
    with pytest.raises(Exception) as excinfo:
        check_include_resources("deployments,foo")
    assert (
        "--include-resources argument should contain a subset of [cronjobs, daemonsets, deployments, horizontalpodautoscalers, jobs, poddisruptionbudgets, rollouts, scaledobjects, stacks, statefulsets]"
        in str(excinfo.value)
    )
