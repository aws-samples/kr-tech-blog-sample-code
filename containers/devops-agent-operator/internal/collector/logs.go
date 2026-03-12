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
	"bufio"
	"context"
	"fmt"
	"io"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	// DefaultSinceSeconds is the default time range for log collection (15 minutes)
	DefaultSinceSeconds int64 = 15 * 60
	// MaxLogBytes is the maximum bytes to read from logs
	MaxLogBytes int64 = 10 * 1024 * 1024 // 10MB
)

// LogCollector collects container logs from pods
type LogCollector struct {
	clientset    *kubernetes.Clientset
	sinceSeconds int64
}

// NewLogCollector creates a new LogCollector
func NewLogCollector(clientset *kubernetes.Clientset) *LogCollector {
	return &LogCollector{
		clientset:    clientset,
		sinceSeconds: DefaultSinceSeconds,
	}
}

// WithSinceSeconds sets the time range for log collection in seconds
func (c *LogCollector) WithSinceSeconds(seconds int64) *LogCollector {
	c.sinceSeconds = seconds
	return c
}

// ContainerLogs holds current and previous logs for a container
type ContainerLogs struct {
	Current  string `json:"current,omitempty"`
	Previous string `json:"previous,omitempty"`
}

// CollectPodLogs collects logs for all containers in a pod
func (c *LogCollector) CollectPodLogs(ctx context.Context, namespace, podName string, containerNames []string) (map[string]*ContainerLogs, error) {
	result := make(map[string]*ContainerLogs)

	for _, containerName := range containerNames {
		logs := &ContainerLogs{}

		// Collect current logs
		current, err := c.getContainerLogs(ctx, namespace, podName, containerName, false)
		if err == nil {
			logs.Current = current
		}

		// Collect previous logs (from crashed container)
		previous, err := c.getContainerLogs(ctx, namespace, podName, containerName, true)
		if err == nil {
			logs.Previous = previous
		}

		result[containerName] = logs
	}

	return result, nil
}

// PodLogs holds logs for all containers keyed by container name
type PodLogs struct {
	Current  map[string]string // container name -> current logs
	Previous map[string]string // container name -> previous logs
}

// CollectAllContainerLogs collects logs from all containers in a pod
// Returns logs organized by container name
func (c *LogCollector) CollectAllContainerLogs(ctx context.Context, namespace, podName string, containerNames []string) *PodLogs {
	result := &PodLogs{
		Current:  make(map[string]string),
		Previous: make(map[string]string),
	}

	for _, containerName := range containerNames {
		// Collect current logs
		current, err := c.getContainerLogs(ctx, namespace, podName, containerName, false)
		if err == nil && current != "" {
			result.Current[containerName] = current
		}

		// Collect previous logs (from crashed container)
		previous, err := c.getContainerLogs(ctx, namespace, podName, containerName, true)
		if err == nil && previous != "" {
			result.Previous[containerName] = previous
		}
	}

	return result
}

// getContainerLogs fetches logs for a specific container
func (c *LogCollector) getContainerLogs(ctx context.Context, namespace, podName, containerName string, previous bool) (string, error) {
	opts := &corev1.PodLogOptions{
		Container:    containerName,
		SinceSeconds: &c.sinceSeconds,
		Previous:     previous,
	}

	req := c.clientset.CoreV1().Pods(namespace).GetLogs(podName, opts)
	stream, err := req.Stream(ctx)
	if err != nil {
		return "", fmt.Errorf("failed to get log stream: %w", err)
	}
	defer stream.Close()

	// Read with size limit
	limitedReader := io.LimitReader(stream, MaxLogBytes)
	var builder strings.Builder
	scanner := bufio.NewScanner(limitedReader)

	for scanner.Scan() {
		builder.WriteString(scanner.Text())
		builder.WriteString("\n")
	}

	if err := scanner.Err(); err != nil {
		// Return what we have so far
		return builder.String(), nil
	}

	return builder.String(), nil
}

// ExtractLastLogLines extracts the last N lines from a log string
func ExtractLastLogLines(logs string, n int) string {
	if logs == "" {
		return ""
	}

	lines := strings.Split(logs, "\n")
	if len(lines) <= n {
		return logs
	}

	// Take last n lines
	start := len(lines) - n
	if start < 0 {
		start = 0
	}
	return strings.Join(lines[start:], "\n")
}

// SummarizeLogs creates a brief summary of logs for the failure message
func SummarizeLogs(logs string, maxLines int) string {
	if logs == "" {
		return "No logs available"
	}

	lines := strings.Split(strings.TrimSpace(logs), "\n")
	if len(lines) == 0 {
		return "No logs available"
	}

	// Get the last few lines as summary
	if len(lines) <= maxLines {
		return strings.Join(lines, "\n")
	}

	return strings.Join(lines[len(lines)-maxLines:], "\n")
}
