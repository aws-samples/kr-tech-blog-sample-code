package v1alpha1

type HTTPRuntimeTargetConfiguration struct {
	AgentcoreRuntime *HTTPRuntimeConfiguration `json:"agentcoreRuntime"`
}

type HTTPRuntimeConfiguration struct {
	ARN *string `json:"arn"`
	Qualifier *string `json:"qualifier,omitempty"`
}

func (in *HTTPRuntimeTargetConfiguration) DeepCopy() *HTTPRuntimeTargetConfiguration {
	if in == nil { return nil }
	out := *in
	if in.AgentcoreRuntime != nil {
		runtime := *in.AgentcoreRuntime
		if runtime.ARN != nil { value := *runtime.ARN; runtime.ARN = &value }
		if runtime.Qualifier != nil { value := *runtime.Qualifier; runtime.Qualifier = &value }
		out.AgentcoreRuntime = &runtime
	}
	return &out
}
