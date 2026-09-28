package gateway_target

import (
	"fmt"
	svcapitypes "github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/apis/v1alpha1"
	ackcompare "github.com/aws-controllers-k8s/runtime/pkg/compare"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/bedrockagentcorecontrol/types"
	"k8s.io/apimachinery/pkg/api/equality"
)

func buildHTTPConfiguration(config *svcapitypes.TargetConfiguration) (svcsdktypes.TargetConfiguration, error) {
	if config.Mcp != nil || config.HTTP == nil || config.HTTP.AgentcoreRuntime == nil || config.HTTP.AgentcoreRuntime.ARN == nil {
		return nil, fmt.Errorf("HTTP target requires an AgentCore Runtime ARN and must not contain MCP")
	}
	runtime := config.HTTP.AgentcoreRuntime
	return &svcsdktypes.TargetConfigurationMemberHttp{Value: &svcsdktypes.HttpTargetConfigurationMemberAgentcoreRuntime{Value: svcsdktypes.RuntimeTargetConfiguration{Arn: runtime.ARN, Qualifier: runtime.Qualifier}}}, nil
}

func setObservedHTTP(resource *svcapitypes.GatewayTarget, configuration svcsdktypes.TargetConfiguration) {
	http, valid := configuration.(*svcsdktypes.TargetConfigurationMemberHttp)
	if !valid { return }
	runtime, valid := http.Value.(*svcsdktypes.HttpTargetConfigurationMemberAgentcoreRuntime)
	if !valid { return }
	resource.Spec.TargetConfiguration = &svcapitypes.TargetConfiguration{HTTP: &svcapitypes.HTTPRuntimeTargetConfiguration{AgentcoreRuntime: &svcapitypes.HTTPRuntimeConfiguration{ARN: runtime.Value.Arn, Qualifier: runtime.Value.Qualifier}}}
}

func compareHTTP(delta *ackcompare.Delta, desired *resource, observed *resource) {
	var desiredHTTP, observedHTTP *svcapitypes.HTTPRuntimeTargetConfiguration
	if desired.ko.Spec.TargetConfiguration != nil { desiredHTTP = desired.ko.Spec.TargetConfiguration.HTTP }
	if observed.ko.Spec.TargetConfiguration != nil { observedHTTP = observed.ko.Spec.TargetConfiguration.HTTP }
	if !equality.Semantic.DeepEqual(desiredHTTP, observedHTTP) { delta.Add("Spec.TargetConfiguration.HTTP", desiredHTTP, observedHTTP) }
}
