class LeaderElectionRecord:
    def __init__(self, holder_identity, lease_duration, renew_time):
        self.holder_identity = holder_identity
        self.lease_duration = lease_duration
        self.renew_time = renew_time