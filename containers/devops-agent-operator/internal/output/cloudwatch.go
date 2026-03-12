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

package output

import (
	"context"
	"encoding/json"
	"fmt"
	"path"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs/types"
	"github.com/cawcaw253/devops-agent-operator/internal/collector"
	"github.com/go-logr/logr"
)

const (
	// maxEventBytes is the maximum size of a single CloudWatch Logs event (256KB minus overhead)
	maxEventBytes = 250 * 1024
)

// CloudWatchLogsClient handles uploading collected data to CloudWatch Logs
type CloudWatchLogsClient struct {
	client   *cloudwatchlogs.Client
	logGroup string
	logger   logr.Logger
}

// CloudWatchLogsClientConfig holds the configuration for creating a CloudWatchLogsClient
type CloudWatchLogsClientConfig struct {
	LogGroup string
	Region   string
}

// CloudWatchLogsUploadResult contains the result of a CloudWatch Logs upload
type CloudWatchLogsUploadResult struct {
	LogGroup  string `json:"logGroup"`
	LogStream string `json:"logStream"`
}

// logEvent represents a structured log event to write to CloudWatch Logs
type logEvent struct {
	Type       string      `json:"type"`
	Content    string      `json:"content,omitempty"`
	Container  string      `json:"container,omitempty"`
	Source     string      `json:"source,omitempty"`
	Previous   *bool       `json:"previous,omitempty"`
	Part       int         `json:"part,omitempty"`
	TotalParts int         `json:"totalParts,omitempty"`
	IncidentID string      `json:"incidentId,omitempty"`
	Failure    interface{} `json:"failure,omitempty"`
	Pod        interface{} `json:"pod,omitempty"`
	Node       interface{} `json:"node,omitempty"`
	Events     interface{} `json:"events,omitempty"`
}

// NewCloudWatchLogsClient creates a new CloudWatch Logs client
func NewCloudWatchLogsClient(cfg CloudWatchLogsClientConfig, logger logr.Logger) (*CloudWatchLogsClient, error) {
	awsCfg, err := awsconfig.LoadDefaultConfig(context.Background(),
		awsconfig.WithRegion(cfg.Region),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	return &CloudWatchLogsClient{
		client:   cloudwatchlogs.NewFromConfig(awsCfg),
		logGroup: cfg.LogGroup,
		logger:   logger,
	}, nil
}

// Upload uploads all collected data to CloudWatch Logs as structured events
func (c *CloudWatchLogsClient) Upload(ctx context.Context, data *collector.CollectedData) (*CloudWatchLogsUploadResult, error) {
	if data == nil {
		return nil, fmt.Errorf("no data to upload")
	}

	incidentID := data.GenerateIncidentID()
	logStream := path.Join("incidents", incidentID)

	// Create log stream
	_, err := c.client.CreateLogStream(ctx, &cloudwatchlogs.CreateLogStreamInput{
		LogGroupName:  aws.String(c.logGroup),
		LogStreamName: aws.String(logStream),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to create log stream %s: %w", logStream, err)
	}

	c.logger.Info("Created CloudWatch log stream",
		"logGroup", c.logGroup,
		"logStream", logStream,
	)

	// Build all log events
	events := c.buildLogEvents(data, incidentID)

	// Send events in batches (PutLogEvents has 1MB batch limit and 10,000 event limit)
	if err := c.putLogEvents(ctx, logStream, events); err != nil {
		return nil, fmt.Errorf("failed to put log events: %w", err)
	}

	c.logger.Info("CloudWatch Logs upload completed",
		"logGroup", c.logGroup,
		"logStream", logStream,
		"eventsCount", len(events),
	)

	return &CloudWatchLogsUploadResult{
		LogGroup:  c.logGroup,
		LogStream: logStream,
	}, nil
}

// buildLogEvents constructs all structured log events from collected data
func (c *CloudWatchLogsClient) buildLogEvents(data *collector.CollectedData, incidentID string) []types.InputLogEvent {
	var events []types.InputLogEvent
	now := time.Now().UnixMilli()

	// Event 1: summary
	summary := logEvent{
		Type:       "summary",
		IncidentID: incidentID,
		Failure:    data.Failure,
		Events:     data.Events,
	}
	if data.Pod != nil {
		summary.Pod = map[string]string{
			"name":      data.Pod.Name,
			"namespace": data.Pod.Namespace,
			"nodeName":  data.Pod.NodeName,
		}
	}
	if data.Node != nil {
		summary.Node = data.Node
	}
	events = append(events, c.marshalEvent(summary, now)...)
	now++

	// Event 2: pod-manifest
	if data.Pod != nil && data.Pod.Manifest != "" {
		events = append(events, c.buildContentEvents("pod-manifest", "", "", nil, data.Pod.Manifest, now)...)
		now += int64(len(events))
	}

	// Event 3: pod-describe
	if data.Pod != nil && data.Pod.Describe != "" {
		events = append(events, c.buildContentEvents("pod-describe", "", "", nil, data.Pod.Describe, now)...)
		now += int64(len(events))
	}

	// Event 4~N: container logs
	if data.Pod != nil {
		for containerName, logs := range data.Pod.Logs {
			if logs != "" {
				previous := false
				events = append(events, c.buildContentEvents("container-log", containerName, "", &previous, logs, now)...)
				now += int64(len(events))
			}
		}
		for containerName, logs := range data.Pod.PreviousLogs {
			if logs != "" {
				previous := true
				events = append(events, c.buildContentEvents("container-log", containerName, "", &previous, logs, now)...)
				now += int64(len(events))
			}
		}
	}

	// Event N+1~: node logs
	if data.NodeLogs != nil {
		nodeLogs := map[string]string{
			"kubelet":             data.NodeLogs.Kubelet,
			"containerd":          data.NodeLogs.Containerd,
			"ipamd":               data.NodeLogs.IPAMD,
			"ipamd-introspection": data.NodeLogs.IPAMDIntrospection,
			"dmesg":               data.NodeLogs.Dmesg,
			"networking":          data.NodeLogs.Networking,
			"disk-usage":          data.NodeLogs.DiskUsage,
			"inode-usage":         data.NodeLogs.InodeUsage,
			"mem-usage":           data.NodeLogs.MemUsage,
		}
		for source, content := range nodeLogs {
			if content != "" {
				events = append(events, c.buildContentEvents("node-log", "", source, nil, content, now)...)
				now += int64(len(events))
			}
		}
	}

	return events
}

// buildContentEvents creates one or more log events for content that may exceed 256KB
func (c *CloudWatchLogsClient) buildContentEvents(eventType, container, source string, previous *bool, content string, timestamp int64) []types.InputLogEvent {
	// Try single event first
	evt := logEvent{
		Type:      eventType,
		Content:   content,
		Container: container,
		Source:    source,
		Previous:  previous,
	}

	jsonData, err := json.Marshal(evt)
	if err != nil {
		c.logger.Error(err, "Failed to marshal log event", "type", eventType)
		return nil
	}

	// If it fits in a single event, return it
	if len(jsonData) <= maxEventBytes {
		return []types.InputLogEvent{
			{
				Message:   aws.String(string(jsonData)),
				Timestamp: aws.Int64(timestamp),
			},
		}
	}

	// Split content into multiple parts
	return c.splitContentEvent(eventType, container, source, previous, content, timestamp)
}

// splitContentEvent splits a large content into multiple events with part/totalParts
func (c *CloudWatchLogsClient) splitContentEvent(eventType, container, source string, previous *bool, content string, timestamp int64) []types.InputLogEvent {
	// Calculate overhead: JSON envelope without content
	overhead := logEvent{
		Type:       eventType,
		Container:  container,
		Source:     source,
		Previous:   previous,
		Part:       1,
		TotalParts: 1,
		Content:    "",
	}
	overheadJSON, _ := json.Marshal(overhead)
	// Available space per chunk (subtract overhead + some margin for longer part numbers)
	chunkSize := maxEventBytes - len(overheadJSON) - 100

	if chunkSize <= 0 {
		chunkSize = maxEventBytes / 2
	}

	// Split content into chunks
	var chunks []string
	contentBytes := []byte(content)
	for len(contentBytes) > 0 {
		end := chunkSize
		if end > len(contentBytes) {
			end = len(contentBytes)
		}
		chunks = append(chunks, string(contentBytes[:end]))
		contentBytes = contentBytes[end:]
	}

	totalParts := len(chunks)
	var events []types.InputLogEvent

	for i, chunk := range chunks {
		evt := logEvent{
			Type:       eventType,
			Content:    chunk,
			Container:  container,
			Source:     source,
			Previous:   previous,
			Part:       i + 1,
			TotalParts: totalParts,
		}

		jsonData, err := json.Marshal(evt)
		if err != nil {
			c.logger.Error(err, "Failed to marshal split event", "type", eventType, "part", i+1)
			continue
		}

		events = append(events, types.InputLogEvent{
			Message:   aws.String(string(jsonData)),
			Timestamp: aws.Int64(timestamp + int64(i)),
		})
	}

	c.logger.Info("Split large event into parts",
		"type", eventType,
		"totalParts", totalParts,
		"originalSize", len(content),
	)

	return events
}

// marshalEvent marshals a logEvent and returns it as InputLogEvent(s)
func (c *CloudWatchLogsClient) marshalEvent(evt logEvent, timestamp int64) []types.InputLogEvent {
	jsonData, err := json.Marshal(evt)
	if err != nil {
		c.logger.Error(err, "Failed to marshal log event", "type", evt.Type)
		return nil
	}

	return []types.InputLogEvent{
		{
			Message:   aws.String(string(jsonData)),
			Timestamp: aws.Int64(timestamp),
		},
	}
}

// putLogEvents sends log events to CloudWatch Logs in batches
func (c *CloudWatchLogsClient) putLogEvents(ctx context.Context, logStream string, events []types.InputLogEvent) error {
	if len(events) == 0 {
		return nil
	}

	// PutLogEvents limit: 1MB per batch, 10,000 events per batch
	const maxBatchBytes = 1024 * 1024
	const maxBatchEvents = 10000

	var batch []types.InputLogEvent
	batchSize := 0

	for _, event := range events {
		eventSize := len(aws.ToString(event.Message)) + 26 // 26 bytes overhead per event

		// If adding this event would exceed limits, flush the batch
		if len(batch) >= maxBatchEvents || (batchSize+eventSize > maxBatchBytes && len(batch) > 0) {
			if err := c.sendBatch(ctx, logStream, batch); err != nil {
				return err
			}
			batch = nil
			batchSize = 0
		}

		batch = append(batch, event)
		batchSize += eventSize
	}

	// Flush remaining events
	if len(batch) > 0 {
		return c.sendBatch(ctx, logStream, batch)
	}

	return nil
}

// sendBatch sends a single batch of events to CloudWatch Logs
func (c *CloudWatchLogsClient) sendBatch(ctx context.Context, logStream string, events []types.InputLogEvent) error {
	_, err := c.client.PutLogEvents(ctx, &cloudwatchlogs.PutLogEventsInput{
		LogGroupName:  aws.String(c.logGroup),
		LogStreamName: aws.String(logStream),
		LogEvents:     events,
	})
	if err != nil {
		return fmt.Errorf("failed to put log events to %s/%s: %w", c.logGroup, logStream, err)
	}

	c.logger.V(1).Info("Sent log events batch",
		"logStream", logStream,
		"eventsCount", len(events),
	)

	return nil
}

// GetLogStreamURL returns the CloudWatch Logs console URL for the log stream
func (r *CloudWatchLogsUploadResult) GetLogStreamURL(region string) string {
	return fmt.Sprintf("https://%s.console.aws.amazon.com/cloudwatch/home?region=%s#logsV2:log-groups/log-group/%s/log-events/%s",
		region, region, r.LogGroup, r.LogStream)
}
