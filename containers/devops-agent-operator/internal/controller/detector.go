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

package controller

import (
	corev1 "k8s.io/api/core/v1"

	"github.com/cawcaw253/devops-agent-operator/internal/collector"
)

// Failure categories indicate which lifecycle phase a failure belongs to.
const (
	CategoryContainerWaiting    = "ContainerWaiting"
	CategoryContainerTerminated = "ContainerTerminated"
	CategoryPodPhase            = "PodPhase"
	CategoryPodStatus           = "PodStatus"
	CategoryPodCondition        = "PodCondition"
)

// normalWaitingReasons is the whitelist of waiting reasons that are NOT failures.
// Any waiting reason NOT in this set is treated as abnormal.
var normalWaitingReasons = map[string]bool{
	"ContainerCreating": true,
	"PodInitializing":   true,
}

// timeoutWaitingReasons are normal waiting reasons that become failures after a timeout.
var timeoutWaitingReasons = map[string]bool{
	"ContainerCreating": true,
}

// timeoutConditionReasons are pod condition reasons that require a timeout period
// before being treated as failures (e.g., Unschedulable may be transient during scaling).
var timeoutConditionReasons = map[string]bool{
	"Unschedulable": true,
}

// DetectionResult holds the outcome of pod failure detection.
type DetectionResult struct {
	// Failure is the detected failure info, nil if no failure.
	Failure *collector.FailureInfo

	// RequiresTimeout is true if the pod is in a timeout-eligible state
	// (e.g., ContainerCreating, Unschedulable). The caller should requeue and check again after timeout.
	RequiresTimeout bool

	// WaitingReason is the raw reason for timeout tracking.
	WaitingReason string

	// Container is the container name associated with timeout tracking (empty for pod-level conditions).
	Container string

	// Category is the failure category for timeout promotion (e.g., CategoryContainerWaiting, CategoryPodCondition).
	Category string

	// Message is the original message preserved for timeout promotion.
	Message string
}

// waitingCheckResult is an internal result from checking a container's waiting state.
type waitingCheckResult struct {
	failure         *collector.FailureInfo
	requiresTimeout bool
	waitingReason   string
}

// conditionCheckResult is an internal result from checking pod conditions.
type conditionCheckResult struct {
	failure         *collector.FailureInfo
	requiresTimeout bool
	waitingReason   string
	message         string
}

// detectPodFailure performs unified failure detection across all pod lifecycle phases.
//
// Detection layers (in priority order):
//
//	Layer 1: Pod Status Reason  → Evicted, DeadlineExceeded (root cause signals)
//	Layer 2: Container Waiting  → whitelist-based (init + regular)
//	Layer 3: Container Terminated → exit code != 0 (init + regular)
//	Layer 4: Pod Phase          → Failed, Unknown
//	Layer 5: Pod Conditions     → Unschedulable (PodScheduled=False)
func detectPodFailure(pod *corev1.Pod) *DetectionResult {
	result := &DetectionResult{}

	// Layer 1: Pod status reason (root cause signals that supersede container-level details)
	if f := checkPodStatusReason(pod); f != nil {
		result.Failure = f
		return result
	}

	// Layer 2 + 3: Init containers (they run before regular containers)
	for _, cs := range pod.Status.InitContainerStatuses {
		if wr := checkContainerWaiting(cs, true); wr != nil {
			if wr.requiresTimeout {
				result.RequiresTimeout = true
				result.WaitingReason = wr.waitingReason
				result.Container = cs.Name
				result.Category = CategoryContainerWaiting
				continue
			}
			result.Failure = wr.failure
			return result
		}
		if f := checkContainerTerminated(cs, true); f != nil {
			result.Failure = f
			return result
		}
	}

	// Layer 2 + 3: Regular containers
	for _, cs := range pod.Status.ContainerStatuses {
		if wr := checkContainerWaiting(cs, false); wr != nil {
			if wr.requiresTimeout {
				result.RequiresTimeout = true
				result.WaitingReason = wr.waitingReason
				result.Container = cs.Name
				result.Category = CategoryContainerWaiting
				continue
			}
			result.Failure = wr.failure
			return result
		}
		if f := checkContainerTerminated(cs, false); f != nil {
			result.Failure = f
			return result
		}
	}

	// Layer 4: Pod phase
	if f := checkPodPhase(pod); f != nil {
		result.Failure = f
		return result
	}

	// Layer 5: Pod conditions (with timeout support for transient states like Unschedulable)
	if cr := checkPodConditions(pod); cr != nil {
		if cr.requiresTimeout {
			result.RequiresTimeout = true
			result.WaitingReason = cr.waitingReason
			result.Category = CategoryPodCondition
			result.Message = cr.message
			return result
		}
		result.Failure = cr.failure
		return result
	}

	return result
}

// checkPodStatusReason detects root-cause pod-level failures from pod.status.reason.
func checkPodStatusReason(pod *corev1.Pod) *collector.FailureInfo {
	switch pod.Status.Reason {
	case "Evicted":
		return &collector.FailureInfo{
			Type:     "Evicted",
			Category: CategoryPodStatus,
			Reason:   pod.Status.Reason,
			Message:  pod.Status.Message,
		}
	case "DeadlineExceeded":
		return &collector.FailureInfo{
			Type:     "DeadlineExceeded",
			Category: CategoryPodStatus,
			Reason:   pod.Status.Reason,
			Message:  pod.Status.Message,
		}
	}
	return nil
}

// checkContainerWaiting checks a container's waiting state against the whitelist.
// Returns nil if the container is not waiting or waiting reason is normal (non-timeout).
func checkContainerWaiting(cs corev1.ContainerStatus, isInit bool) *waitingCheckResult {
	if cs.State.Waiting == nil || cs.State.Waiting.Reason == "" {
		return nil
	}

	reason := cs.State.Waiting.Reason

	// Normal waiting reason
	if normalWaitingReasons[reason] {
		if timeoutWaitingReasons[reason] {
			return &waitingCheckResult{
				requiresTimeout: true,
				waitingReason:   reason,
			}
		}
		return nil
	}

	// Abnormal waiting reason → failure
	return &waitingCheckResult{
		failure: &collector.FailureInfo{
			Type:            reason,
			Category:        CategoryContainerWaiting,
			IsInitContainer: isInit,
			Container:       cs.Name,
			Reason:          reason,
			Message:         cs.State.Waiting.Message,
		},
	}
}

// checkContainerTerminated checks a container's last termination state.
// Returns nil if no termination or exit code is 0.
func checkContainerTerminated(cs corev1.ContainerStatus, isInit bool) *collector.FailureInfo {
	if cs.LastTerminationState.Terminated == nil {
		return nil
	}

	term := cs.LastTerminationState.Terminated
	if term.ExitCode == 0 {
		return nil
	}

	failureType := term.Reason
	if failureType == "" {
		failureType = "NonZeroExit"
	}

	return &collector.FailureInfo{
		Type:            failureType,
		Category:        CategoryContainerTerminated,
		IsInitContainer: isInit,
		Container:       cs.Name,
		ExitCode:        term.ExitCode,
		Reason:          term.Reason,
		Message:         term.Message,
	}
}

// checkPodPhase detects failures from pod phase.
func checkPodPhase(pod *corev1.Pod) *collector.FailureInfo {
	switch pod.Status.Phase {
	case corev1.PodFailed:
		return &collector.FailureInfo{
			Type:     "PodFailed",
			Category: CategoryPodPhase,
			Reason:   pod.Status.Reason,
			Message:  pod.Status.Message,
		}
	case corev1.PodUnknown:
		return &collector.FailureInfo{
			Type:     "PodUnknown",
			Category: CategoryPodPhase,
			Reason:   pod.Status.Reason,
			Message:  pod.Status.Message,
		}
	}
	return nil
}

// checkPodConditions detects failures from pod conditions.
// Returns a conditionCheckResult with timeout support for transient conditions.
func checkPodConditions(pod *corev1.Pod) *conditionCheckResult {
	for _, cond := range pod.Status.Conditions {
		if cond.Type == corev1.PodScheduled && cond.Status == corev1.ConditionFalse {
			if timeoutConditionReasons[cond.Reason] {
				return &conditionCheckResult{
					requiresTimeout: true,
					waitingReason:   cond.Reason,
					message:         cond.Message,
				}
			}
			return &conditionCheckResult{
				failure: &collector.FailureInfo{
					Type:     cond.Reason,
					Category: CategoryPodCondition,
					Reason:   cond.Reason,
					Message:  cond.Message,
				},
			}
		}
	}
	return nil
}
