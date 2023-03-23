# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Implementation of aws specific details of the kubernetes manifests."""
import logging
import pickle
from hashlib import md5
from typing import Dict, Optional

from lightkube.models.core_v1 import Toleration
from ops.manifests import ManifestLabel, Manifests, Patch

log = logging.getLogger(__file__)


class UpdateControllerDaemonSet(Patch):
    """Update the Controller DaemonSet object to target juju control plane."""

    def __call__(self, obj):
        """Update the DaemonSet object in the deployment."""
        if not (obj.kind == "DaemonSet" and obj.metadata.name == "aws-cloud-controller-manager"):
            return
        node_selector = self.manifests.config.get("control-node-selector")
        if not isinstance(node_selector, dict):
            log.error(
                f"provider control-node-selector was an unexpected type: {type(node_selector)}"
            )
            return
        obj.spec.template.spec.nodeSelector = node_selector
        node_selector_text = " ".join('{0}: "{1}"'.format(*t) for t in node_selector.items())
        log.info(f"Applying provider Control Node Selector as {node_selector_text}")

        current_keys = {toleration.key for toleration in obj.spec.template.spec.tolerations}
        missing_tolerations = [
            Toleration(
                key=taint.key,
                value=taint.value,
                effect=taint.effect,
            )
            for taint in self.manifests.config.get("control-node-taints", [])
            if taint.key not in current_keys
        ]
        obj.spec.template.spec.tolerations += missing_tolerations
        log.info("Adding provider tolerations from control-plane")

        args = {
            "cluster-provider": "aws",
            "v": 2,
            "cluster-tag": self.manifests.config.get("cluster_tag"),
        }
        args.update(**self.manifests.config.get("controller-extra-args"))
        containers = obj.spec.template.spec.containers
        containers[0].args = [f"--{name}={value}" for name, value in args.items()]
        log.info("Adjusting container arguments from control-plane")


class AWSProviderManifests(Manifests):
    """Deployment Specific details for cloud-provider-aws."""

    def __init__(self, charm, charm_config, kube_control):
        manipulations = [
            ManifestLabel(self),
            UpdateControllerDaemonSet(self),
        ]
        super().__init__(
            "cloud-provider-aws", charm.model, "upstream/cloud_provider", manipulations
        )
        self.charm_config = charm_config
        self.kube_control = kube_control

    @property
    def config(self) -> Dict:
        """Returns current config available from charm config and joined relations."""
        config = {}
        if self.kube_control.is_ready:
            config["image-registry"] = self.kube_control.get_registry_location()
            config["control-node-taints"] = self.kube_control.get_controller_taints() or [
                Toleration("NoSchedule", "node-role.kubernetes.io/control-plane"),
                Toleration("NoSchedule", "node.cloudprovider.kubernetes.io/uninitialized", "true"),
            ]  # by default
            config["control-node-selector"] = {
                label.key: label.value for label in self.kube_control.get_controller_labels()
            } or {"juju-application": self.kube_control.relation.app.name}
            config["cluster-tag"] = self.kube_control.get_cluster_tag()

        config.update(**self.charm_config.available_data)

        for key, value in dict(**config).items():
            if value == "" or value is None:
                del config[key]

        config["release"] = config.pop("provider-release", None)

        return config

    def hash(self) -> int:
        """Calculate a hash of the current configuration."""
        return int(md5(pickle.dumps(self.config)).hexdigest(), 16)

    def evaluate(self) -> Optional[str]:
        """Determine if manifest_config can be applied to manifests."""
        props = ["control-node-selector", "cluster-tag"]
        for prop in props:
            value = self.config.get(prop)
            if not value:
                return f"Provider manifests waiting for definition of {prop}"
        return None
