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

const (
	SeverityCritical = "CRITICAL"
	SeverityHigh     = "HIGH"
	SeverityMedium   = "MEDIUM"
	SeverityLow      = "LOW"
)

// severityMap maps failure Type strings to severity levels.
// Types not in this map fall through to DefaultSeverity.
var severityMap = map[string]string{
	// Critical - immediate action required
	"OOMKilled": SeverityCritical,

	// High - deployment/operation failure
	"CrashLoopBackOff": SeverityHigh,
	"Evicted":          SeverityHigh,
	"ImagePullBackOff": SeverityHigh,
	"ErrImagePull":     SeverityHigh,

	// Medium - configuration or runtime errors
	"CreateContainerConfigError": SeverityMedium,
	"CreateContainerError":       SeverityMedium,
	"InvalidImageName":           SeverityMedium,
	"ErrImageNeverPull":          SeverityMedium,
	"RunContainerError":          SeverityMedium,
	"PostStartHookError":         SeverityMedium,
	"PreCreateHookError":         SeverityMedium,
	"PreStartHookError":          SeverityMedium,
	"Error":                      SeverityMedium,
	"NonZeroExit":                SeverityMedium,
	"PodFailed":                  SeverityMedium,
	"PodUnknown":                 SeverityMedium,
	"Unschedulable":              SeverityMedium,
	"DeadlineExceeded":           SeverityMedium,

	// Low - timeout-based or transient
	"ContainerCreatingTimeout": SeverityLow,
	"UnschedulableTimeout":     SeverityMedium,
}

// DefaultSeverity is returned for failure types not in the severity map.
const DefaultSeverity = SeverityLow

// DetermineSeverity returns the severity level for a given failure.
// Returns DefaultSeverity for unknown or nil failures.
func DetermineSeverity(failure *FailureInfo) string {
	if failure == nil {
		return DefaultSeverity
	}
	if severity, ok := severityMap[failure.Type]; ok {
		return severity
	}
	return DefaultSeverity
}
