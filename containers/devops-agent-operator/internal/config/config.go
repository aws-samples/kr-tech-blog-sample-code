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

package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds all configuration options for the DevOps Agent Operator
type Config struct {
	// WatchNamespaces is a list of namespaces to watch (empty means all)
	WatchNamespaces []string

	// ExcludeNamespaces is a list of namespaces to exclude from watching
	ExcludeNamespaces []string

	// EnableSSMCollection enables node log collection via AWS SSM
	EnableSSMCollection bool

	// WebhookURL is the DevOps Agent webhook URL (required)
	WebhookURL string

	// WebhookSecret is the HMAC secret for webhook authentication (required)
	WebhookSecret string

	// WebhookTimeout is the timeout for webhook requests
	WebhookTimeout time.Duration

	// CloudWatchLogGroup is the CloudWatch Log Group name for storing incident data (optional)
	CloudWatchLogGroup string

	// S3Bucket is the S3 bucket for storing incident data (optional)
	S3Bucket string

	// S3Prefix is the prefix for S3 keys (optional)
	S3Prefix string

	// AWSRegion is the AWS region for SSM and S3
	AWSRegion string

	// AWSAccountID is the AWS account ID (required for DevOps Agent)
	AWSAccountID string

	// ClusterName is the EKS cluster name (required for DevOps Agent)
	ClusterName string

	// LogSinceMinutes is the number of minutes of recent logs to collect (default: 15)
	LogSinceMinutes int

	// ProcessedTTL is the duration to prevent reprocessing the same failure
	ProcessedTTL time.Duration

	// FailureGracePeriod is the duration to wait before treating a timeout-eligible state as a failure.
	// Applies to transient states such as ContainerCreating and Unschedulable, which may resolve
	// on their own (e.g., image pull in progress, cluster autoscaler adding nodes).
	// If the state persists beyond this period, it is promoted to a failure
	// (e.g., ContainerCreatingTimeout, UnschedulableTimeout).
	// Zero disables timeout-based detection entirely.
	FailureGracePeriod time.Duration

	// FailureRecheckInterval is the interval between rechecks for pods in a timeout-eligible state.
	// During the grace period, the operator requeues the pod at this interval to check
	// whether the transient state has resolved or the grace period has elapsed.
	FailureRecheckInterval time.Duration
}

// DefaultConfig returns a Config with default values
func DefaultConfig() *Config {
	return &Config{
		WatchNamespaces:        []string{},
		ExcludeNamespaces:      []string{"kube-system", "kube-public", "kube-node-lease"},
		EnableSSMCollection:    false,
		WebhookURL:             "",
		WebhookTimeout:         30 * time.Second,
		S3Bucket:               "",
		S3Prefix:               "",
		AWSRegion:              "us-east-1",
		AWSAccountID:           "",
		ClusterName:            "",
		LogSinceMinutes:        15,
		ProcessedTTL:           1 * time.Hour,
		FailureGracePeriod:     3 * time.Minute,
		FailureRecheckInterval: 1 * time.Minute,
	}
}

// LoadFromEnv loads configuration from environment variables
func LoadFromEnv() *Config {
	cfg := DefaultConfig()

	if v := os.Getenv("WATCH_NAMESPACES"); v != "" {
		cfg.WatchNamespaces = splitAndTrim(v, ",")
	}

	if v := os.Getenv("EXCLUDE_NAMESPACES"); v != "" {
		cfg.ExcludeNamespaces = splitAndTrim(v, ",")
	}

	if v := os.Getenv("ENABLE_SSM_COLLECTION"); v == "true" {
		cfg.EnableSSMCollection = true
	}

	// Support both DEVOPS_AGENT_WEBHOOK_URL and WEBHOOK_URL for backward compatibility
	if v := os.Getenv("DEVOPS_AGENT_WEBHOOK_URL"); v != "" {
		cfg.WebhookURL = v
	} else if v := os.Getenv("WEBHOOK_URL"); v != "" {
		cfg.WebhookURL = v
	}

	if v := os.Getenv("DEVOPS_AGENT_WEBHOOK_SECRET"); v != "" {
		cfg.WebhookSecret = v
	}

	if v := os.Getenv("WEBHOOK_TIMEOUT"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			cfg.WebhookTimeout = d
		}
	}

	if v := os.Getenv("CLOUDWATCH_LOG_GROUP"); v != "" {
		cfg.CloudWatchLogGroup = v
	}

	if v := os.Getenv("S3_BUCKET"); v != "" {
		cfg.S3Bucket = v
	}

	if v := os.Getenv("S3_PREFIX"); v != "" {
		cfg.S3Prefix = v
	}

	if v := os.Getenv("AWS_REGION"); v != "" {
		cfg.AWSRegion = v
	}

	if v := os.Getenv("AWS_ACCOUNT_ID"); v != "" {
		cfg.AWSAccountID = v
	}

	if v := os.Getenv("EKS_CLUSTER_NAME"); v != "" {
		cfg.ClusterName = v
	}

	if v := os.Getenv("LOG_SINCE_MINUTES"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			cfg.LogSinceMinutes = n
		}
	}

	if v := os.Getenv("PROCESSED_TTL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			cfg.ProcessedTTL = d
		}
	}

	if v := os.Getenv("FAILURE_GRACE_PERIOD"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			cfg.FailureGracePeriod = d
		}
	}

	if v := os.Getenv("FAILURE_RECHECK_INTERVAL"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			cfg.FailureRecheckInterval = d
		}
	}

	return cfg
}

// Validate checks that all required configuration values are set.
func (c *Config) Validate() error {
	if c.WebhookURL == "" {
		return fmt.Errorf("DEVOPS_AGENT_WEBHOOK_URL (or WEBHOOK_URL) is required")
	}
	if c.WebhookSecret == "" {
		return fmt.Errorf("DEVOPS_AGENT_WEBHOOK_SECRET is required")
	}
	return nil
}

// IsNamespaceWatched returns true if the namespace should be watched
func (c *Config) IsNamespaceWatched(namespace string) bool {
	// Check exclusions first
	for _, ns := range c.ExcludeNamespaces {
		if ns == namespace {
			return false
		}
	}

	// If no specific namespaces are configured, watch all (except excluded)
	if len(c.WatchNamespaces) == 0 {
		return true
	}

	// Check if namespace is in watch list
	for _, ns := range c.WatchNamespaces {
		if ns == namespace {
			return true
		}
	}

	return false
}

// splitAndTrim splits a string by separator and trims whitespace
func splitAndTrim(s, sep string) []string {
	parts := strings.Split(s, sep)
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		if trimmed := strings.TrimSpace(p); trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}
