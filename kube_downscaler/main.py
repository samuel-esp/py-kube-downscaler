#!/usr/bin/env python3
import logging
import re
import time
import os

from kube_downscaler import __version__
from kube_downscaler import cmd
from kube_downscaler import shutdown
from kube_downscaler.scaler import scale

logger = logging.getLogger("downscaler")

'''
def config(args=None):
    config = cmd.load_config('/etc/config')
    parser = cmd.get_parser(config)
    args = parser.parse_args(args)  # Parse the args, which could be None or a list
    return args
'''
def main(args=None):
    '''
    if args is None or isinstance(args, list):
        args = config(args)  # Now config() can handle the list of args
    '''
    config = cmd.load_config('/etc/config')
    parser = cmd.get_parser(config)
    args = parser.parse_args(args)

    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO,
    )

    config_str = ", ".join(f"{k}={v}" for k, v in sorted(vars(args).items()))
    logger.info(f"Downscaler v{__version__} started with {config_str}")

    if args.dry_run:
        logger.info("**DRY-RUN**: no downscaling will be performed!")

    return run_loop(
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
        args.downtime_replicas,
        args.deployment_time_annotation,
        args.enable_events,
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
    downtime_replicas,
    deployment_time_annotation=None,
    enable_events=False,
):
    handler = shutdown.GracefulShutdown()
    config_directory = '/etc/config'
    last_mod_time = os.path.getmtime(config_directory)

    if namespace == "":
        namespaces = []
    else:
        namespaces = frozenset(namespace.split(","))

    if len(namespaces) >= 1:
        constrained_downscaler = True
        logging.info("Namespace argument is not empty, the downscaler will run in constrained mode")
    else:
        constrained_downscaler = False

    while True:

        current_mod_time = os.path.getmtime(config_directory)
        if current_mod_time != last_mod_time:
            logger.info("**CONFIGMAP UPDATED**")
            last_mod_time = current_mod_time

            args = update_config()
            config_str = ", ".join(f"{k}={v}" for k, v in sorted(vars(args).items()))
            logger.info(f"Downscaler v{__version__} updated with {config_str}")

            namespace=args.namespace
            include_resources=args.include_resources
            matching_labels=args.matching_labels
            admission_controller=args.admission_controller
            upscale_period=args.upscale_period
            downscale_period=args.downscale_period
            default_uptime=args.default_uptime
            default_downtime=args.default_downtime
            exclude_namespaces=args.exclude_namespaces
            exclude_deployments=args.exclude_deployments
            grace_period=args.grace_period
            downtime_replicas= args.downtime_replicas

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
            return False

        with handler.safe_exit():
            time.sleep(interval)