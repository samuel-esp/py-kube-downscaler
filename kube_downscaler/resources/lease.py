import logging

from pykube.objects import NamespacedAPIObject

from kube_downscaler import helper
from kube_downscaler.leader_election.leaderelectionrecord import LeaderElectionRecord


class Lease(NamespacedAPIObject):
    """Support the Lease resource (https://kubernetes.io/docs/concepts/architecture/leases/)."""

    version = "coordination.k8s.io/v1"
    endpoint = "leases"
    kind = "Lease"

    @staticmethod
    def create_lease(name, namespace, identity, leases_duration_second, renew_time, api):
        obj = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": name,
                "namespace": namespace
            },
            "spec": {
                "holderIdentity": identity,
                "leaseDurationSeconds": leases_duration_second,
                "renewTime": renew_time
            }
        }
        try:
            Lease(api, obj).create()
        except Exception as e:
            return False, e

        return True, None

    @staticmethod
    def get_lease(name, namespace, api):
        try:
            lease_object = Lease.objects(api).filter(namespace=namespace).get_or_none(name=name)
        except Exception as e:
             return False, None, e

        if lease_object is not None:
            identity = lease_object.obj["spec"].get("holderIdentity", "none")
            lease_duration = lease_object.obj["spec"].get("leaseDurationSeconds", 0)
            renew_time = lease_object.obj["spec"].get("renewTime", "1970-01-01T00:00:00.000000Z")

            return True, LeaderElectionRecord(identity, lease_duration, renew_time), None
        else:
            return False, None, None


    @staticmethod
    def update_lease(name, namespace, election_record, api):
        obj = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": {
                "name": name,
                "namespace": namespace
            },
            "spec": {
                "holderIdentity": election_record.holder_identity,
                "leaseDurationSeconds": election_record.lease_duration,
                "renewTime": election_record.renew_time
            }
        }

        try:
            Lease(api, obj).update()
        except Exception as e:
            return False, e

        return True, None

    @staticmethod
    def update_lease_before_terminating_if_leader(name, namespace, identity, timeout):
        api = helper.get_kube_api(timeout)
        try:
            lease_object = Lease.objects(api).filter(namespace=namespace).get_or_none(name=name)
        except Exception as e:
             return False, e

        if lease_object is None:
            return True, None

        if lease_object.obj["spec"].get("holderIdentity", "none") == identity:
            obj = {
                "apiVersion": "coordination.k8s.io/v1",
                "kind": "Lease",
                "metadata": {
                    "name": name,
                    "namespace": namespace
                },
                "spec": None
            }

            try:
                Lease(api, obj).update()
            except Exception as e:
                return False, e

            return True, None

        return True, None