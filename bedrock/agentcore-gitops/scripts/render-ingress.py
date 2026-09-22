import argparse
import json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate-arn", required=True)
    parser.add_argument("--admin-cidr", required=True)
    args = parser.parse_args()
    print(json.dumps({
        "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
        "metadata": {"name": "argocd-admin", "namespace": "argocd", "annotations": {
            "alb.ingress.kubernetes.io/scheme": "internet-facing",
            "alb.ingress.kubernetes.io/target-type": "ip",
            "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
            "alb.ingress.kubernetes.io/certificate-arn": args.certificate_arn,
            "alb.ingress.kubernetes.io/inbound-cidrs": args.admin_cidr,
            "alb.ingress.kubernetes.io/backend-protocol": "HTTPS",
            "alb.ingress.kubernetes.io/healthcheck-protocol": "HTTPS",
            "alb.ingress.kubernetes.io/healthcheck-path": "/healthz",
            "alb.ingress.kubernetes.io/ssl-policy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
            "alb.ingress.kubernetes.io/tags": "Project=eks-ack-agentcore",
        }},
        "spec": {"ingressClassName": "alb", "rules": [{"http": {"paths": [{
            "path": "/", "pathType": "Prefix",
            "backend": {"service": {"name": "argocd-server", "port": {"number": 443}}},
        }]}}]},
    }))


if __name__ == "__main__":
    main()
