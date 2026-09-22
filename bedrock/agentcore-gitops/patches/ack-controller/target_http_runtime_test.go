package gateway_target

import (
	"context"
	"testing"
	svcapitypes "github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/apis/v1alpha1"
	ackcompare "github.com/aws-controllers-k8s/runtime/pkg/compare"
	"github.com/aws/aws-sdk-go-v2/aws"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/bedrockagentcorecontrol/types"
)

func httpResource(qualifier string) *resource {
	return &resource{ko: &svcapitypes.GatewayTarget{Spec: svcapitypes.GatewayTargetSpec{Name: aws.String("agent"), GatewayIdentifier: aws.String("test-1234567890"), TargetConfiguration: &svcapitypes.TargetConfiguration{HTTP: &svcapitypes.HTTPRuntimeTargetConfiguration{AgentcoreRuntime: &svcapitypes.HTTPRuntimeConfiguration{ARN: aws.String("arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/test-1234567890"), Qualifier: aws.String(qualifier)}}}}}}
}

func TestHTTPCreateAndUpdateMapping(t *testing.T) {
	manager := &resourceManager{}
	created, err := manager.newCreateRequestPayload(context.Background(), httpResource("DEFAULT"))
	if err != nil { t.Fatal(err) }
	updated, err := manager.newUpdateRequestPayload(context.Background(), httpResource("DEFAULT"), ackcompare.NewDelta())
	if err != nil { t.Fatal(err) }
	for _, config := range []svcsdktypes.TargetConfiguration{created.TargetConfiguration, updated.TargetConfiguration} {
		http := config.(*svcsdktypes.TargetConfigurationMemberHttp)
		runtime := http.Value.(*svcsdktypes.HttpTargetConfigurationMemberAgentcoreRuntime)
		if aws.ToString(runtime.Value.Qualifier) != "DEFAULT" { t.Fatal("qualifier missing") }
	}
}

func TestHTTPObservedDeltaAndDeepCopy(t *testing.T) {
	desired := httpResource("DEFAULT")
	observed := &resource{ko: desired.ko.DeepCopy()}
	config, err := buildHTTPConfiguration(httpResource("live").ko.Spec.TargetConfiguration)
	if err != nil { t.Fatal(err) }
	setObservedHTTP(observed.ko, config)
	if !newResourceDelta(desired, observed).DifferentAt("Spec.TargetConfiguration.HTTP") { t.Fatal("HTTP change was not detected") }
	*observed.ko.Spec.TargetConfiguration.HTTP.AgentcoreRuntime.Qualifier = "other"
	if aws.ToString(desired.ko.Spec.TargetConfiguration.HTTP.AgentcoreRuntime.Qualifier) != "DEFAULT" { t.Fatal("deepcopy shares state") }
}

func TestMixedTargetRejected(t *testing.T) {
	config := httpResource("DEFAULT").ko.Spec.TargetConfiguration
	config.Mcp = &svcapitypes.McpTargetConfiguration{}
	if _, err := buildHTTPConfiguration(config); err == nil { t.Fatal("mixed target must fail") }
}
