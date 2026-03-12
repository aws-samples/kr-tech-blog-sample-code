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

import (
	"fmt"
	"time"
)

// CollectedData contains all collected troubleshooting data
type CollectedData struct {
	Timestamp  time.Time    `json:"timestamp"`
	IncidentID string       `json:"incidentId,omitempty"`
	Pod        *PodInfo     `json:"pod,omitempty"`
	Events     []EventInfo  `json:"events,omitempty"`
	Node       *NodeInfo    `json:"node,omitempty"`
	NodeLogs   *NodeLogs    `json:"nodeLogs,omitempty"`
	Failure    *FailureInfo `json:"failure,omitempty"`
}

// GenerateIncidentID creates a unique incident ID for the collected data
// Format: <timestamp>/<namespace>/<pod-name> for hierarchical S3 storage
// Timestamp-first allows easy identification of recent incidents
// This allows easy navigation: incidents/<timestamp>/<namespace>/<pod-name>/
func (d *CollectedData) GenerateIncidentID() string {
	if d.IncidentID != "" {
		return d.IncidentID
	}

	// Human-readable timestamp: 2025-02-09T12-00-00Z (colons replaced with dashes for S3 compatibility)
	timestamp := d.Timestamp.UTC().Format("2006-01-02T15-04-05Z")

	if d.Pod == nil {
		d.IncidentID = fmt.Sprintf("%s/unknown/unknown", timestamp)
	} else {
		d.IncidentID = fmt.Sprintf("%s/%s/%s",
			timestamp,
			d.Pod.Namespace,
			d.Pod.Name,
		)
	}
	return d.IncidentID
}

// PodInfo contains Pod troubleshooting information
// Each field contains raw kubectl output for analysis
type PodInfo struct {
	Name         string            `json:"name"`
	Namespace    string            `json:"namespace"`
	NodeName     string            `json:"nodeName"`
	Manifest     string            `json:"manifest,omitempty"`     // kubectl get pod -o yaml
	Describe     string            `json:"describe,omitempty"`     // kubectl describe pod
	Logs         map[string]string `json:"logs,omitempty"`         // container name -> kubectl logs (last 100 lines)
	PreviousLogs map[string]string `json:"previousLogs,omitempty"` // container name -> kubectl logs --previous (last 100 lines)
}

// EventInfo contains Kubernetes Event information
type EventInfo struct {
	Type       string    `json:"type"`
	Reason     string    `json:"reason"`
	Message    string    `json:"message"`
	Count      int32     `json:"count"`
	FirstTime  time.Time `json:"firstTime,omitempty"`
	LastTime   time.Time `json:"lastTime,omitempty"`
	SourceHost string    `json:"sourceHost,omitempty"`
	Component  string    `json:"component,omitempty"`
}

// NodeInfo contains Node metadata
type NodeInfo struct {
	Name       string          `json:"name"`
	InstanceID string          `json:"instanceId,omitempty"`
	Region     string          `json:"region,omitempty"`
	Conditions []NodeCondition `json:"conditions,omitempty"`
}

// NodeCondition represents a node condition
type NodeCondition struct {
	Type    string `json:"type"`
	Status  string `json:"status"`
	Reason  string `json:"reason,omitempty"`
	Message string `json:"message,omitempty"`
}

// NodeLogs contains logs collected via SSM
type NodeLogs struct {
	Kubelet            string `json:"kubelet,omitempty"`
	Containerd         string `json:"containerd,omitempty"`
	IPAMD              string `json:"ipamd,omitempty"`
	IPAMDIntrospection string `json:"ipamdIntrospection,omitempty"`
	Dmesg              string `json:"dmesg,omitempty"`
	Networking         string `json:"networking,omitempty"`
	DiskUsage          string `json:"diskUsage,omitempty"`
	InodeUsage         string `json:"inodeUsage,omitempty"`
	MemUsage           string `json:"memUsage,omitempty"`
}

// FailureInfo contains failure detection details
type FailureInfo struct {
	Type            string `json:"type"`
	Category        string `json:"category,omitempty"`        // Detection layer: ContainerWaiting, ContainerTerminated, PodPhase, PodStatus, PodCondition
	IsInitContainer bool   `json:"isInitContainer,omitempty"` // true if failure is in an init container
	Container       string `json:"container,omitempty"`
	ExitCode        int32  `json:"exitCode,omitempty"`
	Reason          string `json:"reason,omitempty"`
	Message         string `json:"message,omitempty"`
}
