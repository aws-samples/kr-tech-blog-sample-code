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
	"bytes"
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/yaml"

	"github.com/cawcaw253/devops-agent-operator/internal/collector"
	"github.com/cawcaw253/devops-agent-operator/internal/config"
	"github.com/cawcaw253/devops-agent-operator/internal/output"
)

const (
	// AnnotationProcessed marks a pod as already processed
	AnnotationProcessed = "devops-agent.io/processed"
	// AnnotationProcessedAt stores the timestamp when the pod was processed
	AnnotationProcessedAt = "devops-agent.io/processed-at"
	// AnnotationFailureType stores the detected failure type
	AnnotationFailureType = "devops-agent.io/failure-type"
)

// PodReconciler reconciles Pod objects to detect failures
type PodReconciler struct {
	client.Client
	Scheme           *runtime.Scheme
	Config           *config.Config
	Webhook          *output.WebhookClient
	S3Client         *output.S3Client
	CloudWatchClient *output.CloudWatchLogsClient
	Clientset        *kubernetes.Clientset
	LogCollector     *collector.LogCollector
	SSMCollector     *collector.SSMCollector
}

// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list;watch;patch
// +kubebuilder:rbac:groups="",resources=pods/log,verbs=get;list
// +kubebuilder:rbac:groups="",resources=events,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=nodes,verbs=get;list

// Reconcile handles Pod events and detects failures
func (r *PodReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	// Check if namespace should be watched
	if !r.Config.IsNamespaceWatched(req.Namespace) {
		return ctrl.Result{}, nil
	}

	// Fetch the Pod
	var pod corev1.Pod
	if err := r.Get(ctx, req.NamespacedName, &pod); err != nil {
		// Pod might have been deleted
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Skip if already processed
	if r.isAlreadyProcessed(&pod) {
		return ctrl.Result{}, nil
	}

	// Detect failure using unified whitelist-based detection
	detection := detectPodFailure(&pod)

	// Handle timeout-eligible states (e.g., ContainerCreating, Unschedulable)
	if detection.Failure == nil && detection.RequiresTimeout && r.Config.FailureGracePeriod > 0 {
		elapsed := time.Since(pod.CreationTimestamp.Time)
		if elapsed < r.Config.FailureGracePeriod {
			logger.Info("Pod in timeout-eligible state, will recheck after interval",
				"pod", req.NamespacedName,
				"container", detection.Container,
				"reason", detection.WaitingReason,
				"elapsed", elapsed.Round(time.Second).String(),
				"recheckInterval", r.Config.FailureRecheckInterval.String(),
			)
			return ctrl.Result{RequeueAfter: r.Config.FailureRecheckInterval}, nil
		}
		// Timeout exceeded → promote to failure
		message := fmt.Sprintf("Pod stuck in %s for %s (threshold: %s)",
			detection.WaitingReason, elapsed.Round(time.Second), r.Config.FailureGracePeriod)
		if detection.Message != "" {
			message = fmt.Sprintf("%s: %s", message, detection.Message)
		}
		detection.Failure = &collector.FailureInfo{
			Type:      detection.WaitingReason + "Timeout",
			Category:  detection.Category,
			Container: detection.Container,
			Reason:    detection.WaitingReason,
			Message:   message,
		}
	}

	failure := detection.Failure
	if failure == nil {
		return ctrl.Result{}, nil
	}

	logger.Info("Failure detected",
		"pod", req.NamespacedName,
		"failureType", failure.Type,
		"container", failure.Container,
		"exitCode", failure.ExitCode,
	)

	// Capture node name immediately (before potential rescheduling)
	nodeName := pod.Spec.NodeName

	logger.Info("Capturing failure context",
		"pod", req.NamespacedName,
		"node", nodeName,
		"phase", pod.Status.Phase,
	)

	// Build collected data
	data := r.buildCollectedData(ctx, &pod, failure)

	// Evaluate filter once for all outputs
	severity := collector.DetermineSeverity(failure)
	shouldSend := r.Config.ShouldSendWebhook(failure.Category, severity, failure.Type)

	if !shouldSend {
		logger.Info("Outputs skipped by filter",
			"pod", req.NamespacedName,
			"category", failure.Category,
			"severity", severity,
		)
	}

	// Upload to CloudWatch Logs if configured (optional)
	if r.CloudWatchClient != nil && shouldSend {
		cwResult, err := r.CloudWatchClient.Upload(ctx, data)
		if err != nil {
			logger.Error(err, "Failed to upload data to CloudWatch Logs",
				"pod", req.NamespacedName,
			)
			return ctrl.Result{RequeueAfter: time.Minute}, err
		}
		logger.Info("Data uploaded to CloudWatch Logs",
			"pod", req.NamespacedName,
			"logGroup", cwResult.LogGroup,
			"logStream", cwResult.LogStream,
		)
	}

	// Upload to S3 if configured (optional)
	var s3URL string
	if r.S3Client != nil && shouldSend {
		uploadResult, err := r.S3Client.Upload(ctx, data)
		if err != nil {
			logger.Error(err, "Failed to upload data to S3",
				"pod", req.NamespacedName,
			)
			return ctrl.Result{RequeueAfter: time.Minute}, err
		}
		s3URL = uploadResult.GetCollectedDataURL()
		logger.Info("Data uploaded to S3",
			"pod", req.NamespacedName,
			"s3URL", s3URL,
			"filesUploaded", len(uploadResult.Keys),
		)
	}

	// Send to webhook if not filtered by category or severity
	if shouldSend {
		if err := r.Webhook.Send(ctx, data, s3URL); err != nil {
			logger.Error(err, "Failed to send webhook",
				"pod", req.NamespacedName,
			)
			// Continue to mark as processed even if webhook fails
		}
	}

	// Mark as processed
	if err := r.markAsProcessed(ctx, &pod, failure); err != nil {
		logger.Error(err, "Failed to mark pod as processed")
		return ctrl.Result{RequeueAfter: time.Minute}, err
	}

	logger.Info("Pod failure processed successfully",
		"pod", req.NamespacedName,
		"failureType", failure.Type,
	)

	return ctrl.Result{}, nil
}

// isAlreadyProcessed checks if the pod has already been processed
func (r *PodReconciler) isAlreadyProcessed(pod *corev1.Pod) bool {
	if pod.Annotations == nil {
		return false
	}

	processedAt, ok := pod.Annotations[AnnotationProcessedAt]
	if !ok {
		return false
	}

	// Check if processed within TTL
	t, err := time.Parse(time.RFC3339, processedAt)
	if err != nil {
		return false
	}

	return time.Since(t) < r.Config.ProcessedTTL
}

// markAsProcessed adds annotations to mark the pod as processed
func (r *PodReconciler) markAsProcessed(ctx context.Context, pod *corev1.Pod, failure *collector.FailureInfo) error {
	patch := client.MergeFrom(pod.DeepCopy())

	if pod.Annotations == nil {
		pod.Annotations = make(map[string]string)
	}

	pod.Annotations[AnnotationProcessed] = "true"
	pod.Annotations[AnnotationProcessedAt] = time.Now().Format(time.RFC3339)
	pod.Annotations[AnnotationFailureType] = failure.Type

	// Ignore NotFound error - pod may have been deleted during processing
	return client.IgnoreNotFound(r.Patch(ctx, pod, patch))
}

// SetupWithManager sets up the controller with the Manager
func (r *PodReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&corev1.Pod{}).
		WithEventFilter(predicate.Funcs{
			CreateFunc: func(e event.CreateEvent) bool {
				// Skip create events - we only care about status changes
				return false
			},
			UpdateFunc: func(e event.UpdateEvent) bool {
				oldPod, ok1 := e.ObjectOld.(*corev1.Pod)
				newPod, ok2 := e.ObjectNew.(*corev1.Pod)
				if !ok1 || !ok2 {
					return false
				}
				// Only process if failure state changed
				return r.hasFailureStateChanged(oldPod, newPod)
			},
			DeleteFunc: func(e event.DeleteEvent) bool {
				// Skip delete events
				return false
			},
			GenericFunc: func(e event.GenericEvent) bool {
				return false
			},
		}).
		Complete(r)
}

// hasFailureStateChanged checks if the pod's failure state has changed
func (r *PodReconciler) hasFailureStateChanged(oldPod, newPod *corev1.Pod) bool {
	oldResult := detectPodFailure(oldPod)
	newResult := detectPodFailure(newPod)

	oldHasFailure := oldResult.Failure != nil
	newHasFailure := newResult.Failure != nil

	// No failure in both states
	if !oldHasFailure && !newHasFailure {
		// Check if a new timeout-eligible waiting state appeared
		if r.Config.FailureGracePeriod > 0 {
			return !oldResult.RequiresTimeout && newResult.RequiresTimeout
		}
		return false
	}

	// New failure appeared
	if !oldHasFailure && newHasFailure {
		return true
	}

	// Failure cleared (unlikely but possible)
	if oldHasFailure && !newHasFailure {
		return false
	}

	// Different failure type or container
	return oldResult.Failure.Type != newResult.Failure.Type ||
		oldResult.Failure.Container != newResult.Failure.Container
}

// buildCollectedData creates a CollectedData struct from pod and failure info
func (r *PodReconciler) buildCollectedData(ctx context.Context, pod *corev1.Pod, failure *collector.FailureInfo) *collector.CollectedData {
	logger := log.FromContext(ctx)

	data := &collector.CollectedData{
		Timestamp: time.Now(),
		Failure:   failure,
	}

	if pod == nil {
		return data
	}

	// Build pod info with manifest, describe, and logs
	data.Pod = &collector.PodInfo{
		Name:      pod.Name,
		Namespace: pod.Namespace,
		NodeName:  pod.Spec.NodeName,
	}

	// Generate manifest (kubectl get pod -o yaml)
	manifest, err := yaml.Marshal(pod)
	if err != nil {
		logger.Error(err, "Failed to marshal pod to YAML")
	} else {
		data.Pod.Manifest = string(manifest)
	}

	// Generate describe output
	data.Pod.Describe = r.generateDescribe(ctx, pod)

	// Collect container names for log collection
	containerNames := r.getContainerNames(pod)

	// Collect logs for all containers
	if r.LogCollector != nil && len(containerNames) > 0 {
		podLogs := r.LogCollector.CollectAllContainerLogs(ctx, pod.Namespace, pod.Name, containerNames)
		if len(podLogs.Current) > 0 {
			data.Pod.Logs = podLogs.Current
		}
		if len(podLogs.Previous) > 0 {
			data.Pod.PreviousLogs = podLogs.Previous
		}
	}

	// Build basic node info
	if pod.Spec.NodeName != "" {
		data.Node = &collector.NodeInfo{
			Name: pod.Spec.NodeName,
		}

		// Collect node logs via SSM if enabled
		if r.SSMCollector != nil && r.Config.EnableSSMCollection {
			containerIDs := extractContainerIDs(pod)
			nodeLogs, err := r.SSMCollector.CollectNodeLogs(ctx, pod.Spec.NodeName, string(pod.UID), containerIDs)
			if err != nil {
				logger.Error(err, "Failed to collect node logs via SSM",
					"node", pod.Spec.NodeName,
				)
			} else {
				data.NodeLogs = nodeLogs
				// Log collected node logs at info level
				r.logNodeLogs(logger, nodeLogs)
			}
		}
	}

	return data
}

// logNodeLogs logs the collected node logs at info level
func (r *PodReconciler) logNodeLogs(logger logr.Logger, nodeLogs *collector.NodeLogs) {
	if nodeLogs == nil {
		return
	}

	if nodeLogs.Kubelet != "" {
		logger.Info("Node kubelet logs collected",
			"logType", "kubelet",
			"contentLen", len(nodeLogs.Kubelet),
		)
	}

	if nodeLogs.Containerd != "" {
		logger.Info("Node containerd logs collected",
			"logType", "containerd",
			"contentLen", len(nodeLogs.Containerd),
		)
	}

	if nodeLogs.IPAMD != "" {
		logger.Info("Node IPAMD logs collected",
			"logType", "ipamd",
			"contentLen", len(nodeLogs.IPAMD),
		)
	}

	if nodeLogs.IPAMDIntrospection != "" {
		logger.Info("Node IPAMD introspection collected",
			"logType", "ipamdIntrospection",
			"contentLen", len(nodeLogs.IPAMDIntrospection),
		)
	}

	if nodeLogs.Dmesg != "" {
		logger.Info("Node dmesg logs collected",
			"logType", "dmesg",
			"contentLen", len(nodeLogs.Dmesg),
		)
	}

	if nodeLogs.Networking != "" {
		logger.Info("Node networking info collected",
			"logType", "networking",
			"contentLen", len(nodeLogs.Networking),
		)
	}

	if nodeLogs.DiskUsage != "" {
		logger.Info("Node disk usage collected",
			"logType", "diskUsage",
			"content", nodeLogs.DiskUsage,
		)
	}

	if nodeLogs.MemUsage != "" {
		logger.Info("Node memory usage collected",
			"logType", "memUsage",
			"content", nodeLogs.MemUsage,
		)
	}
}

// extractContainerIDs extracts container IDs from pod status, stripping the runtime prefix.
// Returns IDs from both init containers and regular containers. Empty IDs are filtered out.
func extractContainerIDs(pod *corev1.Pod) []string {
	var ids []string
	for _, cs := range pod.Status.InitContainerStatuses {
		if id := stripContainerIDPrefix(cs.ContainerID); id != "" {
			ids = append(ids, id)
		}
	}
	for _, cs := range pod.Status.ContainerStatuses {
		if id := stripContainerIDPrefix(cs.ContainerID); id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

// stripContainerIDPrefix removes the runtime prefix (e.g., "containerd://", "docker://") from a container ID.
func stripContainerIDPrefix(containerID string) string {
	if idx := strings.Index(containerID, "://"); idx >= 0 {
		return containerID[idx+3:]
	}
	return containerID
}

// getContainerNames returns all container names from the pod (init + regular containers)
func (r *PodReconciler) getContainerNames(pod *corev1.Pod) []string {
	names := make([]string, 0)

	// Init containers
	for _, c := range pod.Spec.InitContainers {
		names = append(names, c.Name)
	}

	// Regular containers
	for _, c := range pod.Spec.Containers {
		names = append(names, c.Name)
	}

	return names
}

// generateDescribe creates a kubectl describe-like output for the pod
func (r *PodReconciler) generateDescribe(ctx context.Context, pod *corev1.Pod) string {
	var buf bytes.Buffer

	// Basic info
	buf.WriteString(fmt.Sprintf("Name:         %s\n", pod.Name))
	buf.WriteString(fmt.Sprintf("Namespace:    %s\n", pod.Namespace))
	buf.WriteString(fmt.Sprintf("Node:         %s\n", pod.Spec.NodeName))
	buf.WriteString(fmt.Sprintf("Start Time:   %s\n", pod.Status.StartTime))

	// Labels
	if len(pod.Labels) > 0 {
		buf.WriteString("Labels:       ")
		first := true
		for k, v := range pod.Labels {
			if first {
				buf.WriteString(fmt.Sprintf("%s=%s\n", k, v))
				first = false
			} else {
				buf.WriteString(fmt.Sprintf("              %s=%s\n", k, v))
			}
		}
	}

	// Annotations
	if len(pod.Annotations) > 0 {
		buf.WriteString("Annotations:  ")
		first := true
		for k, v := range pod.Annotations {
			if first {
				buf.WriteString(fmt.Sprintf("%s=%s\n", k, v))
				first = false
			} else {
				buf.WriteString(fmt.Sprintf("              %s=%s\n", k, v))
			}
		}
	}

	// Status
	buf.WriteString(fmt.Sprintf("Status:       %s\n", pod.Status.Phase))
	buf.WriteString(fmt.Sprintf("IP:           %s\n", pod.Status.PodIP))

	// Init Containers
	if len(pod.Status.InitContainerStatuses) > 0 {
		buf.WriteString("\nInit Containers:\n")
		for _, cs := range pod.Status.InitContainerStatuses {
			r.writeContainerStatus(&buf, cs)
		}
	}

	// Containers
	buf.WriteString("\nContainers:\n")
	for _, cs := range pod.Status.ContainerStatuses {
		r.writeContainerStatus(&buf, cs)
	}

	// Conditions
	buf.WriteString("\nConditions:\n")
	buf.WriteString("  Type              Status\n")
	for _, cond := range pod.Status.Conditions {
		buf.WriteString(fmt.Sprintf("  %-17s %s\n", cond.Type, cond.Status))
	}

	// Events
	events := r.getEventsForPod(ctx, pod)
	if len(events) > 0 {
		buf.WriteString("\nEvents:\n")
		buf.WriteString("  Type     Reason              Age                 From                    Message\n")
		buf.WriteString("  ----     ------              ---                 ----                    -------\n")
		for _, e := range events {
			age := formatAge(e.LastTimestamp.Time)
			buf.WriteString(fmt.Sprintf("  %-8s %-19s %-19s %-23s %s\n",
				e.Type, e.Reason, age, e.Source.Component, e.Message))
		}
	}

	return buf.String()
}

// writeContainerStatus writes container status in describe format
func (r *PodReconciler) writeContainerStatus(buf *bytes.Buffer, cs corev1.ContainerStatus) {
	buf.WriteString(fmt.Sprintf("  %s:\n", cs.Name))
	buf.WriteString(fmt.Sprintf("    Container ID:   %s\n", cs.ContainerID))
	buf.WriteString(fmt.Sprintf("    Image:          %s\n", cs.Image))
	buf.WriteString(fmt.Sprintf("    Image ID:       %s\n", cs.ImageID))

	// State
	if cs.State.Running != nil {
		buf.WriteString(fmt.Sprintf("    State:          Running\n"))
		buf.WriteString(fmt.Sprintf("      Started:      %s\n", cs.State.Running.StartedAt.Time))
	} else if cs.State.Waiting != nil {
		buf.WriteString(fmt.Sprintf("    State:          Waiting\n"))
		buf.WriteString(fmt.Sprintf("      Reason:       %s\n", cs.State.Waiting.Reason))
		if cs.State.Waiting.Message != "" {
			buf.WriteString(fmt.Sprintf("      Message:      %s\n", cs.State.Waiting.Message))
		}
	} else if cs.State.Terminated != nil {
		buf.WriteString(fmt.Sprintf("    State:          Terminated\n"))
		buf.WriteString(fmt.Sprintf("      Reason:       %s\n", cs.State.Terminated.Reason))
		buf.WriteString(fmt.Sprintf("      Exit Code:    %d\n", cs.State.Terminated.ExitCode))
		buf.WriteString(fmt.Sprintf("      Started:      %s\n", cs.State.Terminated.StartedAt.Time))
		buf.WriteString(fmt.Sprintf("      Finished:     %s\n", cs.State.Terminated.FinishedAt.Time))
	}

	// Last State
	if cs.LastTerminationState.Terminated != nil {
		term := cs.LastTerminationState.Terminated
		buf.WriteString(fmt.Sprintf("    Last State:     Terminated\n"))
		buf.WriteString(fmt.Sprintf("      Reason:       %s\n", term.Reason))
		buf.WriteString(fmt.Sprintf("      Exit Code:    %d\n", term.ExitCode))
		buf.WriteString(fmt.Sprintf("      Started:      %s\n", term.StartedAt.Time))
		buf.WriteString(fmt.Sprintf("      Finished:     %s\n", term.FinishedAt.Time))
	}

	buf.WriteString(fmt.Sprintf("    Ready:          %t\n", cs.Ready))
	buf.WriteString(fmt.Sprintf("    Restart Count:  %d\n", cs.RestartCount))
}

// getEventsForPod fetches events related to the pod
func (r *PodReconciler) getEventsForPod(ctx context.Context, pod *corev1.Pod) []corev1.Event {
	if r.Clientset == nil {
		return nil
	}

	eventList, err := r.Clientset.CoreV1().Events(pod.Namespace).List(ctx, metav1.ListOptions{
		FieldSelector: fmt.Sprintf("involvedObject.name=%s,involvedObject.namespace=%s,involvedObject.kind=Pod", pod.Name, pod.Namespace),
	})
	if err != nil {
		return nil
	}

	// Sort events by last timestamp
	events := eventList.Items
	sort.Slice(events, func(i, j int) bool {
		return events[i].LastTimestamp.Before(&events[j].LastTimestamp)
	})

	return events
}

// formatAge formats a time as a human-readable age string
func formatAge(t time.Time) string {
	if t.IsZero() {
		return "<unknown>"
	}

	d := time.Since(t)
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	if d < time.Hour {
		return fmt.Sprintf("%dm", int(d.Minutes()))
	}
	if d < 24*time.Hour {
		return fmt.Sprintf("%dh", int(d.Hours()))
	}
	return fmt.Sprintf("%dd", int(d.Hours()/24))
}
