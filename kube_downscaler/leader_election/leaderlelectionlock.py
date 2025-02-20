class LeaderElectionLock:
    def __init__(self, name, namespace, identity):
        self.name = name
        self.namespace = namespace
        self.identity = identity