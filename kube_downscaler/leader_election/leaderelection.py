"""
This package implements leader election using an annotation in a Kubernetes object.
The onstarted_leading function is run in a thread and when it returns, if it does
it might not be safe to run it again in a process.

At first all candidates are considered followers. The one to create a lock or update
an existing lock first becomes the leader and remains so until it keeps renewing its
lease.
"""

import datetime
import sys
import time
import threading

from kube_downscaler import helper
from kube_downscaler.leader_election.leaderelectionrecord import LeaderElectionRecord
from kube_downscaler.resources.lease import Lease


class LeaderElection:
    def __init__(self, election_config, logging, timeout):
        if election_config is None:
            sys.exit("argument config not passed")

        self.logging = logging

        # Latest record observed in the created lock object
        self.observed_record = None

        # The configuration set for this candidate
        self.election_config = election_config

        # Latest update time of the lock
        self.observed_time_milliseconds = 0

        self.api = helper.get_kube_api(timeout)

    # Point of entry to Leader election
    def run(self):
        # Try to create/ acquire a lock
        if self.acquire():
            self.logging.info("{} successfully acquired lease".format(self.election_config.lock.identity))

            # Start leading and call OnStartedLeading()
            threading.daemon = True
            threading.Thread(target=self.election_config.onstarted_leading).start()

            self.renew_loop()

            # Failed to update lease, run OnStoppedLeading callback
            self.election_config.onstopped_leading()

    def acquire(self):
        # Follower
        self.logging.info("{} is a follower".format(self.election_config.lock.identity))
        retry_period = self.election_config.retry_period

        while True:
            succeeded = self.try_acquire_or_renew()

            if succeeded:
                return True

            time.sleep(retry_period)

    def renew_loop(self):
        # Leader
        self.logging.info("Leader has entered renew loop and will try to update lease continuously")

        retry_period = self.election_config.retry_period
        renew_deadline = self.election_config.renew_deadline * 1000

        while True:
            timeout = int(time.time() * 1000) + renew_deadline
            succeeded = False

            while int(time.time() * 1000) < timeout:
                succeeded = self.try_acquire_or_renew()

                if succeeded:
                    break
                time.sleep(retry_period)

            if succeeded:
                time.sleep(retry_period)
                continue

            # failed to renew, return
            return

    def try_acquire_or_renew(self):
        now_timestamp = time.time()
        now = datetime.datetime.fromtimestamp(now_timestamp).isoformat(timespec="microseconds") + "Z"

        self.logging.info("Attempting to acquire or renew lease")

        # Fetch the current lease
        lock_status, old_lease, http_exception = Lease.get_lease(
            self.election_config.lock.name,
            self.election_config.lock.namespace,
            self.api
        )

        if not lock_status:
            if http_exception:
                if "is forbidden" in str(http_exception).lower():
                    self.logging.warning(
                        f"KubeDownscaler is not authorized to get Leases inside the Namespace {self.election_config.lock.namespace} (403). "
                        "Please check your RBAC settings and ensure the ServiceAccount has proper RoleBindings."
                    )
                else:
                    self.logging.warning(f"Error while retrieving lease record: {http_exception}")
                raise Exception(f"Error while retrieving lease record: {http_exception}")

            # Attempt to create a new lease
            self.logging.info(f"{self.election_config.lock.identity} is attempting to create a new lease")

            create_status, create_exception = Lease.create_lease(
                self.election_config.lock.name,
                self.election_config.lock.namespace,
                self.election_config.lock.identity,
                self.election_config.lease_duration,
                now,
                self.api
            )

            if not create_status:
                if "is forbidden" in str(http_exception).lower():
                    self.logging.warning(
                        f"KubeDownscaler is not authorized to create Leases inside the Namespace {self.election_config.lock.namespace} (403). "
                        "Please check your RBAC settings and ensure the ServiceAccount has proper RoleBindings."
                    )
                else:
                    self.logging.warning(f"Error while creating lease record: {http_exception}")
                raise Exception(f"Error while retrieving lease record: {http_exception}")

            self.observed_record = LeaderElectionRecord(
                holder_identity=self.election_config.lock.identity,
                lease_duration=self.election_config.lease_duration,
                renew_time=now
            )
            self.observed_time_milliseconds = int(now_timestamp * 1000)
            return True

        # A lease already exists, validate the current record
        self.logging.info("Lease already exists. Validating...")

        if old_lease is None or old_lease is None:
            self.logging.warning("Lease object or its spec is malformed. Attempting to update lock.")
            return self.update_lock(LeaderElectionRecord(
                holder_identity=self.election_config.lock.identity,
                lease_duration=self.election_config.lease_duration,
                renew_time=now
            ))

        holder_identity = old_lease.holder_identity
        lease_duration_seconds = old_lease.lease_duration
        renew_time = old_lease.renew_time

        if not holder_identity or not lease_duration_seconds or not renew_time:
            self.logging.warning("Lease spec fields are incomplete. Attempting to update lock.")
            return self.update_lock(LeaderElectionRecord(
                holder_identity=self.election_config.lock.identity,
                lease_duration=self.election_config.lease_duration,
                renew_time=now
            ))

        # Report leader transitions
        if self.observed_record and self.observed_record.holder_identity != holder_identity:
            self.logging.info(f"Lease is actually owned by {holder_identity}")

        if self.observed_record is None or self.observed_record != old_lease:
            self.observed_record = old_lease
            self.observed_time_milliseconds = int(datetime.datetime.fromisoformat(old_lease.renew_time.rstrip('Z')).timestamp() * 1000)

        # Check if this instance is not the leader and the lease is still valid
        lease_expiry_time = self.observed_time_milliseconds + lease_duration_seconds * 1000
        if self.election_config.lock.identity != holder_identity and lease_expiry_time > int(now_timestamp * 1000):
            self.logging.info(f"Lease is held by {holder_identity} and has not expired. Cannot acquire lock.")
            self.logging.debug(
                    f"Observed time: {datetime.datetime.fromtimestamp(self.observed_time_milliseconds / 1000)}, "
                    f"Lease expiry: {datetime.datetime.fromtimestamp(lease_expiry_time / 1000)}, "
                    f"Current time: {datetime.datetime.fromtimestamp(now_timestamp)}")
            return False

        # Attempt to update the lease
        return self.update_lock(LeaderElectionRecord(
            holder_identity=self.election_config.lock.identity,
            lease_duration=self.election_config.lease_duration,
            renew_time=now
        ))

    def update_lock(self, leader_election_record):
        # Update object with latest election record
        update_status, http_exception = Lease.update_lease(self.election_config.lock.name,
                                           self.election_config.lock.namespace,
                                           leader_election_record, self.api)


        if update_status is False:
            if "is forbidden" in str(http_exception).lower():
                self.logging.warning(
                    f"KubeDownscaler is not authorized to patch Leases inside the Namespace {self.election_config.lock.namespace} (403). "
                    "Please check your RBAC settings and ensure the ServiceAccount has proper RoleBindings."
                )
            else:
                self.logging.warning(f"Error while retrieving lease record: {http_exception}")
            raise Exception(f"Error while patching lease record: {http_exception}")

        self.observed_record = leader_election_record
        self.observed_time_milliseconds = int(time.time() * 1000)
        self.logging.info("leader {} has successfully acquired lease".format(leader_election_record.holder_identity))
        return True
