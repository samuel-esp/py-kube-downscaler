import sys


class ElectionConfig:
    # Validate config, exit if an error is detected
    def __init__(self, lock, lease_duration, renew_deadline, retry_period, onstarted_leading, onstopped_leading, logging):
        self.jitter_factor = 1.2

        self.logging = logging

        if lock is None:
            sys.exit("lock cannot be None")
        self.lock = lock

        if lease_duration <= renew_deadline:
            sys.exit("lease_duration must be greater than renew_deadline")

        if renew_deadline <= self.jitter_factor * retry_period:
            sys.exit("renewDeadline must be greater than retry_period*jitter_factor")

        if lease_duration < 1:
            sys.exit("lease_duration must be greater than one")

        if renew_deadline < 1:
            sys.exit("renew_deadline must be greater than one")

        if retry_period < 1:
            sys.exit("retry_period must be greater than one")

        self.lease_duration = lease_duration
        self.renew_deadline = renew_deadline
        self.retry_period = retry_period

        if onstarted_leading is None:
            sys.exit("callback onstarted_leading cannot be None")
        self.onstarted_leading = onstarted_leading

        if onstopped_leading is None:
            self.onstopped_leading = self.on_stoppedleading_callback
        else:
            self.onstopped_leading = onstopped_leading

    # Default callback for when the current candidate if a leader, stops leading
    def on_stoppedleading_callback(self):
        self.logging.info("stopped leading".format(self.lock.identity))