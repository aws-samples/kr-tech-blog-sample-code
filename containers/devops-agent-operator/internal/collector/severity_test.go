/*
Copyright 2024.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package collector

import "testing"

func TestDetermineSeverity_KnownTypes(t *testing.T) {
	tests := []struct {
		failureType string
		expected    string
	}{
		{"OOMKilled", SeverityCritical},
		{"CrashLoopBackOff", SeverityHigh},
		{"Evicted", SeverityHigh},
		{"ImagePullBackOff", SeverityHigh},
		{"ErrImagePull", SeverityHigh},
		{"CreateContainerConfigError", SeverityMedium},
		{"CreateContainerError", SeverityMedium},
		{"InvalidImageName", SeverityMedium},
		{"RunContainerError", SeverityMedium},
		{"Error", SeverityMedium},
		{"NonZeroExit", SeverityMedium},
		{"PodFailed", SeverityMedium},
		{"PodUnknown", SeverityMedium},
		{"Unschedulable", SeverityMedium},
		{"DeadlineExceeded", SeverityMedium},
		{"ContainerCreatingTimeout", SeverityLow},
	}

	for _, tt := range tests {
		t.Run(tt.failureType, func(t *testing.T) {
			failure := &FailureInfo{Type: tt.failureType}
			got := DetermineSeverity(failure)
			if got != tt.expected {
				t.Errorf("DetermineSeverity(%s) = %s, want %s", tt.failureType, got, tt.expected)
			}
		})
	}
}

func TestDetermineSeverity_UnknownType(t *testing.T) {
	failure := &FailureInfo{Type: "SomeFutureKubernetesReason"}
	got := DetermineSeverity(failure)
	if got != DefaultSeverity {
		t.Errorf("DetermineSeverity(unknown) = %s, want %s", got, DefaultSeverity)
	}
}

func TestDetermineSeverity_NilFailure(t *testing.T) {
	got := DetermineSeverity(nil)
	if got != DefaultSeverity {
		t.Errorf("DetermineSeverity(nil) = %s, want %s", got, DefaultSeverity)
	}
}
