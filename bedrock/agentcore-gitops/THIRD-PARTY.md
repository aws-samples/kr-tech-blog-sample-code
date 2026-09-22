# Third-party source attribution

This directory contains a sample implementation and limited material derived from the projects listed below. The parent repository's MIT-0 license does not replace the licenses of third-party material. Full dependency source trees and container binaries are not checked in here.

## AWS Controllers for Kubernetes

- Project: `aws-controllers-k8s/bedrockagentcorecontrol-controller`.
- Source revision: `ba36b95fc5ec9ad1e8fa306fe339d227246bf601`, release `v1.15.1`.
- Source: `https://github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/tree/ba36b95fc5ec9ad1e8fa306fe339d227246bf601`.
- License: Apache License 2.0. See [upstream license](third-party/ack-LICENSE.txt) and [upstream notice](third-party/ack-NOTICE.txt).
- Relevant files: `patches/ack-controller/endpoint-version.patch` and the upstream fragments used by `patches/ack-controller/extend_gateway.py`.

The sample modifies endpoint version reconciliation and request mapping, and adds HTTP Runtime target types, CRD schema and controller mappings. The build downloads the pinned upstream source and applies the documented modifications locally. These changes are sample extensions, not an upstream release or an upstream endorsement.

When distributing a resulting controller image or additional upstream source, preserve applicable license and notice obligations for the controller and its dependencies. The files included here are attribution for the material accompanying this sample, not a complete software bill of materials for a built container.

## AWS Load Balancer Controller

- Project: `kubernetes-sigs/aws-load-balancer-controller`, release `v3.5.0`.
- Source: `https://github.com/kubernetes-sigs/aws-load-balancer-controller/blob/v3.5.0/docs/install/iam_policy.json`.
- Relevant file: `infra/policies/load-balancer-controller.json`. Its JSON content matches the upstream policy at this release.
- License: Apache License 2.0. See [upstream license](third-party/load-balancer-LICENSE.txt).

## Dependencies and figures

JavaScript and Python dependencies are referenced through package manifests and lockfiles, not vendored. Their licenses remain applicable when installed or distributed. Base images and the Go controller dependencies also have their own license terms.

The editable diagrams were authored for this sample using draw.io. Embedded AWS resource icons identify AWS services; including an icon does not grant trademark rights or imply certification of the sample. Review the applicable AWS architecture icon terms before reusing the icons outside this documentation.
