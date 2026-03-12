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
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/cawcaw253/devops-agent-operator/internal/collector"
	"github.com/go-logr/logr"
)

// WebhookClient handles sending incidents to AWS DevOps Agent webhook
type WebhookClient struct {
	URL         string
	Secret      string
	ClusterName string
	Region      string
	AccountID   string
	HTTPClient  *http.Client
	Timeout     time.Duration
	Logger      logr.Logger
}

// WebhookPayload represents the AWS DevOps Agent incident payload
// Schema: https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-capabilities-for-aws-devops-agent-invoking-devops-agent-through-webhook.html
type WebhookPayload struct {
	EventType   string       `json:"eventType"`             // Required: "incident"
	IncidentID  string       `json:"incidentId"`            // Required: unique identifier
	Action      string       `json:"action"`                // Required: "created" | "updated" | "closed" | "resolved"
	Priority    string       `json:"priority"`              // Required: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "MINIMAL"
	Title       string       `json:"title"`                 // Required: incident title
	Description string       `json:"description,omitempty"` // Optional: detailed description
	Timestamp   string       `json:"timestamp,omitempty"`   // Optional: ISO 8601 timestamp
	Service     string       `json:"service,omitempty"`     // Optional: service name
	Data        *WebhookData `json:"data,omitempty"`        // Optional: original event data
}

// WebhookData contains the detailed incident data
type WebhookData struct {
	// Context provides structured analysis instructions for AI agent
	// This field contains investigation guidance and relevant context for automated analysis
	Context string `json:"context,omitempty"`

	Metadata *WebhookMetadata       `json:"metadata,omitempty"`
	Failure  *collector.FailureInfo `json:"failure,omitempty"`
	Pod      *collector.PodInfo     `json:"pod,omitempty"`
	Events   []collector.EventInfo  `json:"events,omitempty"`
	Node     *collector.NodeInfo    `json:"node,omitempty"`
	NodeLogs *collector.NodeLogs    `json:"nodeLogs,omitempty"`
	// S3 offload mode
	DataLocation string `json:"dataLocation,omitempty"`
	S3URL        string `json:"s3URL,omitempty"`
}

// WebhookMetadata contains cluster and environment metadata
type WebhookMetadata struct {
	Cluster     string `json:"cluster,omitempty"`
	Region      string `json:"region,omitempty"`
	AccountID   string `json:"accountId,omitempty"`
	Environment string `json:"environment,omitempty"`
}

// WebhookClientConfig holds the configuration for creating a WebhookClient
type WebhookClientConfig struct {
	URL         string
	Secret      string
	ClusterName string
	Region      string
	AccountID   string
	Timeout     time.Duration
}

// NewWebhookClient creates a new webhook client
func NewWebhookClient(cfg WebhookClientConfig, logger logr.Logger) *WebhookClient {
	return &WebhookClient{
		URL:         cfg.URL,
		Secret:      cfg.Secret,
		ClusterName: cfg.ClusterName,
		Region:      cfg.Region,
		AccountID:   cfg.AccountID,
		HTTPClient: &http.Client{
			Timeout: cfg.Timeout,
		},
		Timeout: cfg.Timeout,
		Logger:  logger,
	}
}

// Send sends a webhook with S3 URL reference to AWS DevOps Agent
func (c *WebhookClient) Send(ctx context.Context, data *collector.CollectedData, s3URL string) error {
	payload := c.buildPayload(data, s3URL)

	// Log the generated context before sending
	if payload.Data != nil && payload.Data.Context != "" {
		c.Logger.Info("Generated webhook context",
			"incidentId", payload.IncidentID,
			"context", payload.Data.Context,
		)
	}

	jsonData, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	timestamp := time.Now().UTC().Format("2006-01-02T15:04:05.000Z")
	signature := c.generateSignature(timestamp, jsonData)

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.URL, bytes.NewReader(jsonData))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("x-amzn-event-timestamp", timestamp)
	req.Header.Set("x-amzn-event-signature", signature)

	c.Logger.Info("Sending webhook request with S3 reference",
		"url", c.URL,
		"incidentId", payload.IncidentID,
		"s3URL", s3URL,
	)

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to send webhook request: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("webhook returned status %d: %s", resp.StatusCode, string(body))
	}

	c.Logger.Info("Webhook request with S3 reference successful",
		"incidentId", payload.IncidentID,
		"status", resp.StatusCode,
	)

	return nil
}

// buildPayload creates the webhook payload with S3 reference
func (c *WebhookClient) buildPayload(data *collector.CollectedData, s3URL string) *WebhookPayload {
	incidentID := data.GenerateIncidentID()
	priority := c.determinePriority(data.Failure)
	title := c.generateTitle(data)
	description := c.generateDescription(data, s3URL)
	context := c.generateContext(data, s3URL)

	return &WebhookPayload{
		EventType:   "incident",
		IncidentID:  incidentID,
		Action:      "created",
		Priority:    priority,
		Title:       title,
		Description: description,
		Timestamp:   data.Timestamp.UTC().Format(time.RFC3339),
		Service:     "EKS",
		Data: &WebhookData{
			Context: context,
			Metadata: &WebhookMetadata{
				Cluster:   c.ClusterName,
				Region:    c.Region,
				AccountID: c.AccountID,
			},
			DataLocation: "s3",
			S3URL:        s3URL,
		},
	}
}

// generateSignature creates HMAC-SHA256 signature for the request
func (c *WebhookClient) generateSignature(timestamp string, payload []byte) string {
	message := timestamp + ":" + string(payload)
	h := hmac.New(sha256.New, []byte(c.Secret))
	h.Write([]byte(message))
	return base64.StdEncoding.EncodeToString(h.Sum(nil))
}

// determinePriority maps failure type to incident priority using data-driven severity map
func (c *WebhookClient) determinePriority(failure *collector.FailureInfo) string {
	return collector.DetermineSeverity(failure)
}

// generateTitle creates a concise incident title
func (c *WebhookClient) generateTitle(data *collector.CollectedData) string {
	failureType := "Unknown"
	if data.Failure != nil {
		failureType = data.Failure.Type
	}

	if data.Pod == nil {
		return fmt.Sprintf("Pod %s detected", failureType)
	}

	return fmt.Sprintf("Pod %s: %s/%s",
		failureType,
		data.Pod.Namespace,
		data.Pod.Name,
	)
}

// generateDescription creates a detailed incident description with S3 data location
func (c *WebhookClient) generateDescription(data *collector.CollectedData, s3URL string) string {
	var desc string

	// Cluster context
	desc = fmt.Sprintf("**EKS Cluster:** %s\n**Region:** %s\n**Account ID:** %s\n\n",
		c.ClusterName,
		c.Region,
		c.AccountID,
	)

	if data.Pod != nil {
		desc += fmt.Sprintf("**Pod Information:**\n"+
			"- Name: %s/%s\n"+
			"- Node: %s\n",
			data.Pod.Namespace,
			data.Pod.Name,
			data.Pod.NodeName,
		)
	}

	if data.Failure != nil {
		desc += fmt.Sprintf("\n**Failure Details:**\n"+
			"- Type: %s\n"+
			"- Container: %s\n"+
			"- Exit Code: %d\n"+
			"- Reason: %s\n",
			data.Failure.Type,
			data.Failure.Container,
			data.Failure.ExitCode,
			data.Failure.Reason,
		)

		// Include failure message if available
		if data.Failure.Message != "" {
			desc += fmt.Sprintf("- Message: %s\n", data.Failure.Message)
		}
	}

	// S3 Data Location - critical for investigation
	desc += fmt.Sprintf("\n**S3 Data Location:**\n"+
		"- Path: %s\n"+
		"- File: %s/collected-data.json\n",
		s3URL,
		s3URL,
	)

	return desc
}

// generateContext creates investigation context that points AI agent to S3 data
func (c *WebhookClient) generateContext(data *collector.CollectedData, s3URL string) string {
	var ctx strings.Builder

	// Investigation target
	ctx.WriteString("## Investigation Target\n")
	ctx.WriteString(fmt.Sprintf("EKS Cluster: %s (Region: %s, Account: %s)\n", c.ClusterName, c.Region, c.AccountID))

	if data.Pod != nil {
		ctx.WriteString(fmt.Sprintf("Pod: %s/%s on Node: %s\n", data.Pod.Namespace, data.Pod.Name, data.Pod.NodeName))
	}

	// Failure summary
	ctx.WriteString("\n## Failure Summary\n")
	if data.Failure != nil {
		ctx.WriteString(fmt.Sprintf("Type: %s\n", data.Failure.Type))
		if data.Failure.Container != "" {
			ctx.WriteString(fmt.Sprintf("Container: %s\n", data.Failure.Container))
		}
		if data.Failure.ExitCode != 0 {
			ctx.WriteString(fmt.Sprintf("Exit Code: %d\n", data.Failure.ExitCode))
		}
		if data.Failure.Reason != "" {
			ctx.WriteString(fmt.Sprintf("Reason: %s\n", data.Failure.Reason))
		}
	}

	// S3 data location - explicit path for direct access
	ctx.WriteString("\n## S3 Data Location (USE THIS PATH DIRECTLY)\n")
	ctx.WriteString(fmt.Sprintf("**Full Path: %s**\n\n", s3URL))

	// Path breakdown for clarity
	ctx.WriteString("### Path Structure\n")
	ctx.WriteString("```\n")
	ctx.WriteString("s3://<bucket>/incidents/<timestamp>/<namespace>/<pod-name>/\n")
	ctx.WriteString("```\n")
	ctx.WriteString("- Timestamp format: YYYY-MM-DDTHH-MM-SSZ (e.g., 2025-02-09T12-00-00Z)\n")
	ctx.WriteString("- Timestamp is in UTC\n\n")

	ctx.WriteString("### How to Access\n")
	ctx.WriteString("Use S3 GetObject with the exact path above.\n")
	ctx.WriteString(fmt.Sprintf("- collected-data.json: %s/collected-data.json\n", s3URL))
	ctx.WriteString(fmt.Sprintf("- failure-info.json: %s/failure-info.json\n\n", s3URL))

	ctx.WriteString("### Available Files\n")
	ctx.WriteString("| File | Description |\n")
	ctx.WriteString("|------|-------------|\n")
	ctx.WriteString("| collected-data.json | All collected data in single JSON (START HERE) |\n")
	ctx.WriteString("| failure-info.json | Failure type, container, exit code, reason |\n")
	ctx.WriteString("| pod-manifest.yaml | Full Pod spec (kubectl get pod -o yaml) |\n")
	ctx.WriteString("| pod-describe.yaml | Pod status details (kubectl describe pod) |\n")
	ctx.WriteString("| logs/<container>.log | Current container stdout/stderr logs |\n")
	ctx.WriteString("| logs/<container>-previous.log | Previous container logs (before crash) |\n")
	ctx.WriteString("| node-logs/kubelet.log | Kubelet logs (pod lifecycle issues) |\n")
	ctx.WriteString("| node-logs/containerd.log | Container runtime logs (OOM events) |\n")
	ctx.WriteString("| node-logs/dmesg.log | Kernel logs (OOM killer, hardware errors) |\n")
	ctx.WriteString("| node-logs/ipamd.log | AWS VPC CNI logs (network issues) |\n")
	ctx.WriteString("| node-logs/ipamd-introspection.log | IPAMD introspection data (ENI/Pod mappings) |\n")
	ctx.WriteString("| node-logs/networking.txt | Network diagnostics (ip route, iptables, conntrack) |\n")
	ctx.WriteString("| node-logs/disk-usage.txt | Disk space status (df -h) |\n")
	ctx.WriteString("| node-logs/inode-usage.txt | Inode usage status (df --inodes) |\n")
	ctx.WriteString("| node-logs/mem-usage.txt | Memory status (free -h) |\n")

	return ctx.String()
}
