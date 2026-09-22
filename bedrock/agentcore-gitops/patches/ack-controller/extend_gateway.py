import argparse
from pathlib import Path

import yaml


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text()
    if content.count(old) != 1:
        raise ValueError(f"Expected one patch anchor in {path}: {old[:80]}")
    path.write_text(content.replace(old, new, 1))


def patch_method(path: Path, name: str, old: str, new: str) -> None:
    content = path.read_text()
    start = content.index(f"func (rm *resourceManager) {name}(")
    end = content.find("\nfunc ", start + 1)
    end = len(content) if end == -1 else end
    section = content[start:end]
    if section.count(old) != 1:
        raise ValueError(f"Unexpected {name} patch count in {path}")
    path.write_text(content[:start] + section.replace(old, new, 1) + content[end:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source
    assets = Path(__file__).parent
    api = source / "apis/v1alpha1"
    replace_once(api / "types.go", "type TargetConfiguration struct {", "type TargetConfiguration struct {\n\tHTTP *HTTPRuntimeTargetConfiguration `json:\"http,omitempty\"`")
    (api / "http_runtime.go").write_text((assets / "http_runtime.go").read_text())
    replace_once(api / "gateway.go", '// +kubebuilder:validation:Required\n\tProtocolType *string `json:"protocolType"`', 'ProtocolType *string `json:"protocolType,omitempty"`')
    replace_once(api / "zz_generated.deepcopy.go", 'func (in *TargetConfiguration) DeepCopyInto(out *TargetConfiguration) {\n\t*out = *in', 'func (in *TargetConfiguration) DeepCopyInto(out *TargetConfiguration) {\n\t*out = *in\n\tif in.HTTP != nil { out.HTTP = in.HTTP.DeepCopy() }')
    resource = source / "pkg/resource/gateway_target"
    for name in ["http_runtime.go", "http_runtime_test.go"]:
        (resource / name).write_text((assets / f"target_{name}").read_text())
    for method in ["sdkFind", "sdkCreate", "sdkUpdate"]:
        patch_method(resource / "sdk.go", method, '\trm.setStatusDefaults(ko)', '\tsetObservedHTTP(ko, resp.TargetConfiguration)\n\trm.setStatusDefaults(ko)')
    for method in ["newCreateRequestPayload", "newUpdateRequestPayload"]:
        patch_method(resource / "sdk.go", method, '\treturn res, nil', '\tif r.ko.Spec.TargetConfiguration != nil && r.ko.Spec.TargetConfiguration.HTTP != nil {\n\t\tconfiguration, err := buildHTTPConfiguration(r.ko.Spec.TargetConfiguration)\n\t\tif err != nil { return nil, err }\n\t\tres.TargetConfiguration = configuration\n\t}\n\treturn res, nil')
    replace_once(resource / "delta.go", '\tcompareInlinePayloadToolDefinitions(delta, a, b)', '\tcompareInlinePayloadToolDefinitions(delta, a, b)\n\tcompareHTTP(delta, a, b)')
    http_schema = {
        "type": "object", "required": ["agentcoreRuntime"],
        "properties": {"agentcoreRuntime": {
            "type": "object", "required": ["arn"],
            "properties": {"arn": {"type": "string", "minLength": 20}, "qualifier": {"type": "string", "default": "DEFAULT"}},
        }},
    }
    for directory in [source / "helm/crds", source / "config/crd/bases"]:
        gateway_path = directory / "bedrockagentcorecontrol.services.k8s.aws_gateways.yaml"
        gateway = yaml.safe_load(gateway_path.read_text())
        for version in gateway["spec"]["versions"]:
            spec = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
            spec["required"].remove("protocolType")
        gateway_path.write_text(yaml.safe_dump(gateway, sort_keys=False))
        target_path = directory / "bedrockagentcorecontrol.services.k8s.aws_gatewaytargets.yaml"
        target = yaml.safe_load(target_path.read_text())
        for version in target["spec"]["versions"]:
            config = version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["targetConfiguration"]
            config["properties"]["http"] = http_schema
            config["x-kubernetes-validations"] = [{"rule": "has(self.http) != has(self.mcp)", "message": "Specify exactly one of http or mcp"}]
        target_path.write_text(yaml.safe_dump(target, sort_keys=False))


if __name__ == "__main__":
    main()
