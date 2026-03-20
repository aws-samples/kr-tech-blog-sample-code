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
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func newPod() *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test-pod",
			Namespace: "default",
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
		},
	}
}

// --- Layer 1: Pod Status Reason ---

func TestDetect_Evicted(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodFailed
	pod.Status.Reason = "Evicted"
	pod.Status.Message = "The node was low on resource: memory."

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for Evicted pod")
	}
	if result.Failure.Type != "Evicted" {
		t.Errorf("expected Type=Evicted, got %s", result.Failure.Type)
	}
	if result.Failure.Category != CategoryPodStatus {
		t.Errorf("expected Category=%s, got %s", CategoryPodStatus, result.Failure.Category)
	}
}

func TestDetect_DeadlineExceeded(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodFailed
	pod.Status.Reason = "DeadlineExceeded"

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for DeadlineExceeded pod")
	}
	if result.Failure.Type != "DeadlineExceeded" {
		t.Errorf("expected Type=DeadlineExceeded, got %s", result.Failure.Type)
	}
}

// Evicted should take priority over container terminated state
func TestDetect_Evicted_PrioritizedOverContainerTerminated(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodFailed
	pod.Status.Reason = "Evicted"
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 137,
					Reason:   "OOMKilled",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure")
	}
	if result.Failure.Type != "Evicted" {
		t.Errorf("expected Evicted to take priority, got %s", result.Failure.Type)
	}
}

// --- Layer 2: Container Waiting (Whitelist) ---

func TestDetect_CrashLoopBackOff(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason:  "CrashLoopBackOff",
					Message: "back-off 5m0s restarting failed container",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for CrashLoopBackOff")
	}
	if result.Failure.Type != "CrashLoopBackOff" {
		t.Errorf("expected Type=CrashLoopBackOff, got %s", result.Failure.Type)
	}
	if result.Failure.Category != CategoryContainerWaiting {
		t.Errorf("expected Category=%s, got %s", CategoryContainerWaiting, result.Failure.Category)
	}
	if result.Failure.IsInitContainer {
		t.Error("expected IsInitContainer=false")
	}
	if result.Failure.Container != "app" {
		t.Errorf("expected Container=app, got %s", result.Failure.Container)
	}
}

func TestDetect_ImagePullBackOff(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "ImagePullBackOff",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for ImagePullBackOff")
	}
	if result.Failure.Type != "ImagePullBackOff" {
		t.Errorf("expected Type=ImagePullBackOff, got %s", result.Failure.Type)
	}
}

func TestDetect_ErrImagePull(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "ErrImagePull",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for ErrImagePull")
	}
	if result.Failure.Type != "ErrImagePull" {
		t.Errorf("expected Type=ErrImagePull, got %s", result.Failure.Type)
	}
}

func TestDetect_CreateContainerConfigError(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason:  "CreateContainerConfigError",
					Message: "secret \"my-secret\" not found",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for CreateContainerConfigError")
	}
	if result.Failure.Type != "CreateContainerConfigError" {
		t.Errorf("expected Type=CreateContainerConfigError, got %s", result.Failure.Type)
	}
}

func TestDetect_InvalidImageName(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "InvalidImageName",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for InvalidImageName")
	}
	if result.Failure.Type != "InvalidImageName" {
		t.Errorf("expected Type=InvalidImageName, got %s", result.Failure.Type)
	}
}

func TestDetect_RunContainerError(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "RunContainerError",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for RunContainerError")
	}
	if result.Failure.Type != "RunContainerError" {
		t.Errorf("expected Type=RunContainerError, got %s", result.Failure.Type)
	}
}

// Unknown/future waiting reasons should also be detected
func TestDetect_UnknownWaitingReason(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "SomeFutureKubernetesReason",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for unknown waiting reason")
	}
	if result.Failure.Type != "SomeFutureKubernetesReason" {
		t.Errorf("expected Type=SomeFutureKubernetesReason, got %s", result.Failure.Type)
	}
}

// ContainerCreating should NOT be a failure, but RequiresTimeout
func TestDetect_ContainerCreating_RequiresTimeout(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "ContainerCreating",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for ContainerCreating, got %s", result.Failure.Type)
	}
	if !result.RequiresTimeout {
		t.Error("expected RequiresTimeout=true for ContainerCreating")
	}
	if result.WaitingReason != "ContainerCreating" {
		t.Errorf("expected WaitingReason=ContainerCreating, got %s", result.WaitingReason)
	}
	if result.Container != "app" {
		t.Errorf("expected Container=app, got %s", result.Container)
	}
	if result.Category != CategoryContainerWaiting {
		t.Errorf("expected Category=%s, got %s", CategoryContainerWaiting, result.Category)
	}
}

// PodInitializing should be completely ignored (no failure, no timeout)
func TestDetect_PodInitializing_Normal(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "PodInitializing",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for PodInitializing, got %s", result.Failure.Type)
	}
	if result.RequiresTimeout {
		t.Error("expected RequiresTimeout=false for PodInitializing")
	}
}

// Empty waiting reason should be ignored
func TestDetect_EmptyWaitingReason_Ignored(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for empty waiting reason, got %s", result.Failure.Type)
	}
}

// Init container waiting failures
func TestDetect_InitContainer_CrashLoopBackOff(t *testing.T) {
	pod := newPod()
	pod.Status.InitContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "init-db",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "CrashLoopBackOff",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for init container CrashLoopBackOff")
	}
	if result.Failure.Type != "CrashLoopBackOff" {
		t.Errorf("expected Type=CrashLoopBackOff, got %s", result.Failure.Type)
	}
	if !result.Failure.IsInitContainer {
		t.Error("expected IsInitContainer=true")
	}
	if result.Failure.Container != "init-db" {
		t.Errorf("expected Container=init-db, got %s", result.Failure.Container)
	}
}

func TestDetect_InitContainer_ImagePullBackOff(t *testing.T) {
	pod := newPod()
	pod.Status.InitContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "init-setup",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "ImagePullBackOff",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for init container ImagePullBackOff")
	}
	if result.Failure.Type != "ImagePullBackOff" {
		t.Errorf("expected Type=ImagePullBackOff, got %s", result.Failure.Type)
	}
	if !result.Failure.IsInitContainer {
		t.Error("expected IsInitContainer=true")
	}
}

// --- Layer 3: Container Terminated ---

func TestDetect_OOMKilled(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 137,
					Reason:   "OOMKilled",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for OOMKilled")
	}
	if result.Failure.Type != "OOMKilled" {
		t.Errorf("expected Type=OOMKilled, got %s", result.Failure.Type)
	}
	if result.Failure.Category != CategoryContainerTerminated {
		t.Errorf("expected Category=%s, got %s", CategoryContainerTerminated, result.Failure.Category)
	}
	if result.Failure.ExitCode != 137 {
		t.Errorf("expected ExitCode=137, got %d", result.Failure.ExitCode)
	}
}

func TestDetect_Error(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 1,
					Reason:   "Error",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for Error")
	}
	if result.Failure.Type != "Error" {
		t.Errorf("expected Type=Error, got %s", result.Failure.Type)
	}
}

func TestDetect_NonZeroExit(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 2,
					Reason:   "",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for NonZeroExit")
	}
	if result.Failure.Type != "NonZeroExit" {
		t.Errorf("expected Type=NonZeroExit, got %s", result.Failure.Type)
	}
}

// Exit code 0 should not be a failure
func TestDetect_ExitCodeZero_NoFailure(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 0,
					Reason:   "Completed",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for exit code 0, got %s", result.Failure.Type)
	}
}

func TestDetect_InitContainer_Terminated(t *testing.T) {
	pod := newPod()
	pod.Status.InitContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "init-db",
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 1,
					Reason:   "Error",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for init container terminated")
	}
	if result.Failure.Type != "Error" {
		t.Errorf("expected Type=Error, got %s", result.Failure.Type)
	}
	if !result.Failure.IsInitContainer {
		t.Error("expected IsInitContainer=true")
	}
}

// --- Layer 4: Pod Phase ---

func TestDetect_PodFailed(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodFailed
	pod.Status.Reason = "BackoffLimitExceeded"

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for PodFailed")
	}
	if result.Failure.Type != "PodFailed" {
		t.Errorf("expected Type=PodFailed, got %s", result.Failure.Type)
	}
	if result.Failure.Category != CategoryPodPhase {
		t.Errorf("expected Category=%s, got %s", CategoryPodPhase, result.Failure.Category)
	}
}

func TestDetect_PodUnknown(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodUnknown

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure for PodUnknown")
	}
	if result.Failure.Type != "PodUnknown" {
		t.Errorf("expected Type=PodUnknown, got %s", result.Failure.Type)
	}
}

// --- Layer 5: Pod Conditions ---

// Unschedulable should NOT be an immediate failure, but RequiresTimeout (like ContainerCreating)
func TestDetect_Unschedulable_RequiresTimeout(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodPending
	pod.Status.Conditions = []corev1.PodCondition{
		{
			Type:    corev1.PodScheduled,
			Status:  corev1.ConditionFalse,
			Reason:  "Unschedulable",
			Message: "0/3 nodes are available: insufficient memory.",
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no immediate failure for Unschedulable, got %s", result.Failure.Type)
	}
	if !result.RequiresTimeout {
		t.Error("expected RequiresTimeout=true for Unschedulable")
	}
	if result.WaitingReason != "Unschedulable" {
		t.Errorf("expected WaitingReason=Unschedulable, got %s", result.WaitingReason)
	}
	if result.Category != CategoryPodCondition {
		t.Errorf("expected Category=%s, got %s", CategoryPodCondition, result.Category)
	}
	if result.Message != "0/3 nodes are available: insufficient memory." {
		t.Errorf("expected scheduler message to be preserved, got %s", result.Message)
	}
}

// PodScheduled=True should not trigger
func TestDetect_PodScheduled_True_NoFailure(t *testing.T) {
	pod := newPod()
	pod.Status.Conditions = []corev1.PodCondition{
		{
			Type:   corev1.PodScheduled,
			Status: corev1.ConditionTrue,
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for PodScheduled=True, got %s", result.Failure.Type)
	}
}

// --- Priority / layer ordering ---

// Waiting failure should take priority over terminated failure on same pod
func TestDetect_WaitingPrioritizedOverTerminated(t *testing.T) {
	pod := newPod()
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name: "app",
			State: corev1.ContainerState{
				Waiting: &corev1.ContainerStateWaiting{
					Reason: "CrashLoopBackOff",
				},
			},
			LastTerminationState: corev1.ContainerState{
				Terminated: &corev1.ContainerStateTerminated{
					ExitCode: 137,
					Reason:   "OOMKilled",
				},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure == nil {
		t.Fatal("expected failure")
	}
	// Waiting (Layer 2) checked before Terminated (Layer 3)
	if result.Failure.Type != "CrashLoopBackOff" {
		t.Errorf("expected CrashLoopBackOff to take priority, got %s", result.Failure.Type)
	}
}

// --- Normal / healthy pod ---

func TestDetect_HealthyRunningPod_NoFailure(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodRunning
	pod.Status.ContainerStatuses = []corev1.ContainerStatus{
		{
			Name:  "app",
			Ready: true,
			State: corev1.ContainerState{
				Running: &corev1.ContainerStateRunning{},
			},
		},
	}

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for healthy pod, got %s", result.Failure.Type)
	}
	if result.RequiresTimeout {
		t.Error("expected RequiresTimeout=false for healthy pod")
	}
}

func TestDetect_PendingPod_NoConditions_NoFailure(t *testing.T) {
	pod := newPod()
	pod.Status.Phase = corev1.PodPending

	result := detectPodFailure(pod)
	if result.Failure != nil {
		t.Errorf("expected no failure for pending pod without conditions, got %s", result.Failure.Type)
	}
}
