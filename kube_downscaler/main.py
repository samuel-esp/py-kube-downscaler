#!/usr/bin/env python3
import logging
import re
import sys
import time

from kube_downscaler import __version__
from kube_downscaler import cmd
from kube_downscaler import shutdown
from kube_downscaler.helper import get_hostname, get_current_namespace
from kube_downscaler.leader_election.leaderelection import LeaderElection
from kube_downscaler.leader_election.leaderelectionconfig import ElectionConfig
from kube_downscaler.leader_election.leaderlelectionlock import LeaderElectionLock
from kube_downscaler.resources.lease import Lease
from kube_downscaler.scaler import scale

logger = logging.getLogger("downscaler")


def main(args=None):
    global lock_namespace, lock_name
    parser = cmd.get_parser()
    args = parser.parse_args(args)

    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
    )

    config_str = ", ".join(f"{k}={v}" for k, v in sorted(vars(args).items()))
    logger.info(f"Downscaler v{__version__} started with {config_str}")

    if args.dry_run:
        logger.info("**DRY-RUN**: no downscaling will be performed!")

    leader_election_enabled = True
    leader_election_fallback_enabled = False

    if leader_election_enabled:
        try:
            lock_name = get_hostname()
            lock_namespace = get_current_namespace()
        except RuntimeError as e:
            if "Failed to get hostname" in str(e):
                logger.warning("Failed to get hostname, cannot complete leader election: %s", e)
            elif "Failed to read namespace file" in str(e):
                logger.warning("Failed to get namespace, cannot complete leader election: %s", e)
            else:
                logger.warning("Unexpected error during leader election: %s", e)
            logger.warning("Proceeding without leader election, conflict errors may occur if running with multiple downscaler replicas")
            leader_election_enabled = False

    if leader_election_enabled:
        lock = LeaderElectionLock("downscaler", lock_namespace, lock_name)
        leader_election_config = ElectionConfig(
            lock,
            lease_duration=30,
            renew_deadline=20,
            retry_period=5,
            onstarted_leading=lambda: run_loop(
                args.once,
                args.namespace,
                args.include_resources,
                args.matching_labels,
                args.admission_controller,
                args.upscale_period,
                args.downscale_period,
                args.default_uptime,
                args.default_downtime,
                args.exclude_namespaces,
                args.exclude_deployments,
                args.grace_period,
                args.interval,
                args.upscale_target_only,
                args.dry_run,
                args.api_server_timeout,
                args.max_retries_on_conflict,
                args.downtime_replicas,
                args.deployment_time_annotation,
                args.enable_events,
                lock,
            ),
            onstopped_leading=None,
            logging=logger
        )
        try:
            LeaderElection(leader_election_config, logger, args.api_server_timeout).run()
        except Exception as e:
            logger.warning("Failed to run leader election: %s", e)
            logger.warning("Proceeding without leader election, conflict errors may occur if running with multiple "
                           "downscaler replicas")
            leader_election_fallback_enabled = True

    if leader_election_fallback_enabled or (not leader_election_enabled):
        lock = None
        run_loop(
            args.once,
            args.namespace,
            args.include_resources,
            args.matching_labels,
            args.admission_controller,
            args.upscale_period,
            args.downscale_period,
            args.default_uptime,
            args.default_downtime,
            args.exclude_namespaces,
            args.exclude_deployments,
            args.grace_period,
            args.interval,
            args.upscale_target_only,
            args.dry_run,
            args.api_server_timeout,
            args.max_retries_on_conflict,
            args.downtime_replicas,
            args.deployment_time_annotation,
            args.enable_events,
            lock
        )


def run_loop(
    run_once,
    namespace,
    include_resources,
    matching_labels,
    admission_controller,
    upscale_period,
    downscale_period,
    default_uptime,
    default_downtime,
    exclude_namespaces,
    exclude_deployments,
    grace_period,
    interval,
    upscale_target_only,
    dry_run,
    api_server_timeout,
    max_retries_on_conflict,
    downtime_replicas,
    deployment_time_annotation=None,
    enable_events=False,
    lock=None,
):
    handler = shutdown.GracefulShutdown()

    if namespace == "":
        namespaces = []
    else:
        namespaces = frozenset(namespace.split(","))

    if len(namespaces) >= 1:
        constrained_downscaler = True
        logging.info(
            "Namespace argument is not empty, the downscaler will run in constrained mode"
        )
    else:
        constrained_downscaler = False

    while True:
        try:
            scale(
                namespaces,
                upscale_period,
                downscale_period,
                default_uptime,
                default_downtime,
                upscale_target_only,
                include_resources=frozenset(include_resources.split(",")),
                exclude_namespaces=frozenset(
                    re.compile(pattern) for pattern in exclude_namespaces.split(",")
                ),
                exclude_deployments=frozenset(exclude_deployments.split(",")),
                dry_run=dry_run,
                grace_period=grace_period,
                admission_controller=admission_controller,
                constrained_downscaler=constrained_downscaler,
                api_server_timeout=api_server_timeout,
                max_retries_on_conflict=max_retries_on_conflict,
                downtime_replicas=downtime_replicas,
                deployment_time_annotation=deployment_time_annotation,
                enable_events=enable_events,
                matching_labels=frozenset(
                    re.compile(pattern) for pattern in matching_labels.split(",")
                ),
            )
        except Exception as e:
            logger.exception(f"Failed to autoscale: {e}")
        if run_once or handler.shutdown_now:
            logger.info("hitting here")
            if lock is not None:
                try:
                    logger.info("Deleting lease before shutting down...")
                    delete_lease_status, delete_exception = Lease.update_lease_before_terminating_if_leader(lock.name, lock.namespace, lock.identity, api_server_timeout)
                    if not delete_lease_status:
                        logger.exception(f"Failed to delete lease before shutting down: {delete_exception}")
                except Exception as e:
                    logger.exception(f"Unexpected error during lease deletion: {e}")
                logger.info("almost terminating...")
                sys.exit(0)
            logger.info("Shutting down...")
            return
        with handler.safe_exit():
            time.sleep(interval)
