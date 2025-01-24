# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "aws_cloud_provider" {
  name         = var.app_name
  model        = var.model

  charm {
    name       = "aws-cloud-provider"
    channel    = var.channel
    revision   = var.revision
    base       = var.base
  }

  config       = var.config
  constraints  = var.constraints
}
