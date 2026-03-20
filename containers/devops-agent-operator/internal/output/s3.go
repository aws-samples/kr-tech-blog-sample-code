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
	"encoding/json"
	"fmt"
	"path"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/cawcaw253/devops-agent-operator/internal/collector"
	"github.com/go-logr/logr"
)

// S3Client handles uploading collected data to S3
type S3Client struct {
	client *s3.Client
	bucket string
	prefix string
	region string
	logger logr.Logger
}

// S3ClientConfig holds the configuration for creating an S3Client
type S3ClientConfig struct {
	Bucket string
	Prefix string
	Region string
}

// S3UploadResult contains the result of an S3 upload operation
type S3UploadResult struct {
	Bucket    string            `json:"bucket"`
	Keys      map[string]string `json:"keys"`    // file type -> S3 key
	URLs      map[string]string `json:"urls"`    // file type -> S3 URL
	BaseKey   string            `json:"baseKey"` // base path for all files
	Timestamp time.Time         `json:"timestamp"`
}

// NewS3Client creates a new S3 client
func NewS3Client(cfg S3ClientConfig, logger logr.Logger) (*S3Client, error) {
	awsCfg, err := config.LoadDefaultConfig(context.Background(),
		config.WithRegion(cfg.Region),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	return &S3Client{
		client: s3.NewFromConfig(awsCfg),
		bucket: cfg.Bucket,
		prefix: cfg.Prefix,
		region: cfg.Region,
		logger: logger,
	}, nil
}

// Upload uploads all collected data to S3
func (c *S3Client) Upload(ctx context.Context, data *collector.CollectedData) (*S3UploadResult, error) {
	if data == nil {
		return nil, fmt.Errorf("no data to upload")
	}

	// Generate base key path
	baseKey := c.generateBaseKey(data)

	result := &S3UploadResult{
		Bucket:    c.bucket,
		Keys:      make(map[string]string),
		URLs:      make(map[string]string),
		BaseKey:   baseKey,
		Timestamp: time.Now(),
	}

	c.logger.Info("Starting S3 upload",
		"bucket", c.bucket,
		"baseKey", baseKey,
	)

	// Upload all data as a single JSON file (for easy retrieval)
	if err := c.uploadJSON(ctx, baseKey, "collected-data.json", data, result); err != nil {
		c.logger.Error(err, "Failed to upload collected-data.json")
	}

	// Upload individual files for easier browsing
	if data.Pod != nil {
		// Pod manifest
		if data.Pod.Manifest != "" {
			if err := c.uploadText(ctx, baseKey, "pod-manifest.yaml", data.Pod.Manifest, result); err != nil {
				c.logger.Error(err, "Failed to upload pod-manifest.yaml")
			}
		}

		// Pod describe
		if data.Pod.Describe != "" {
			if err := c.uploadText(ctx, baseKey, "pod-describe.yaml", data.Pod.Describe, result); err != nil {
				c.logger.Error(err, "Failed to upload pod-describe.yaml")
			}
		}

		// Container logs (current)
		for containerName, logs := range data.Pod.Logs {
			if logs != "" {
				filename := fmt.Sprintf("logs/%s.log", containerName)
				if err := c.uploadText(ctx, baseKey, filename, logs, result); err != nil {
					c.logger.Error(err, "Failed to upload container logs", "container", containerName)
				}
			}
		}

		// Container logs (previous)
		for containerName, logs := range data.Pod.PreviousLogs {
			if logs != "" {
				filename := fmt.Sprintf("logs/%s-previous.log", containerName)
				if err := c.uploadText(ctx, baseKey, filename, logs, result); err != nil {
					c.logger.Error(err, "Failed to upload previous container logs", "container", containerName)
				}
			}
		}
	}

	// Node logs
	if data.NodeLogs != nil {
		if err := c.uploadNodeLogs(ctx, baseKey, data.NodeLogs, result); err != nil {
			c.logger.Error(err, "Failed to upload node logs")
		}
	}

	// Failure info
	if data.Failure != nil {
		if err := c.uploadJSON(ctx, baseKey, "failure-info.json", data.Failure, result); err != nil {
			c.logger.Error(err, "Failed to upload failure-info.json")
		}
	}

	c.logger.Info("S3 upload completed",
		"bucket", c.bucket,
		"baseKey", baseKey,
		"filesUploaded", len(result.Keys),
	)

	return result, nil
}

// uploadNodeLogs uploads all node logs to S3
func (c *S3Client) uploadNodeLogs(ctx context.Context, baseKey string, nodeLogs *collector.NodeLogs, result *S3UploadResult) error {
	nodeLogsPath := "node-logs"

	if nodeLogs.Kubelet != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "kubelet.log"), nodeLogs.Kubelet, result); err != nil {
			return err
		}
	}

	if nodeLogs.Containerd != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "containerd.log"), nodeLogs.Containerd, result); err != nil {
			return err
		}
	}

	if nodeLogs.IPAMD != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "ipamd.log"), nodeLogs.IPAMD, result); err != nil {
			return err
		}
	}

	if nodeLogs.IPAMDIntrospection != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "ipamd-introspection.log"), nodeLogs.IPAMDIntrospection, result); err != nil {
			return err
		}
	}

	if nodeLogs.Dmesg != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "dmesg.log"), nodeLogs.Dmesg, result); err != nil {
			return err
		}
	}

	if nodeLogs.Networking != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "networking.txt"), nodeLogs.Networking, result); err != nil {
			return err
		}
	}

	if nodeLogs.DiskUsage != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "disk-usage.txt"), nodeLogs.DiskUsage, result); err != nil {
			return err
		}
	}

	if nodeLogs.InodeUsage != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "inode-usage.txt"), nodeLogs.InodeUsage, result); err != nil {
			return err
		}
	}

	if nodeLogs.MemUsage != "" {
		if err := c.uploadText(ctx, baseKey, path.Join(nodeLogsPath, "mem-usage.txt"), nodeLogs.MemUsage, result); err != nil {
			return err
		}
	}

	return nil
}

// uploadJSON uploads a JSON object to S3
func (c *S3Client) uploadJSON(ctx context.Context, baseKey, filename string, data interface{}, result *S3UploadResult) error {
	jsonData, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	key := path.Join(baseKey, filename)
	contentType := "application/json"

	return c.putObject(ctx, key, jsonData, contentType, result, filename)
}

// uploadText uploads a text file to S3
func (c *S3Client) uploadText(ctx context.Context, baseKey, filename, content string, result *S3UploadResult) error {
	key := path.Join(baseKey, filename)
	contentType := "text/plain"

	if path.Ext(filename) == ".yaml" || path.Ext(filename) == ".yml" {
		contentType = "application/x-yaml"
	}

	return c.putObject(ctx, key, []byte(content), contentType, result, filename)
}

// putObject uploads data to S3
func (c *S3Client) putObject(ctx context.Context, key string, data []byte, contentType string, result *S3UploadResult, filename string) error {
	input := &s3.PutObjectInput{
		Bucket:      aws.String(c.bucket),
		Key:         aws.String(key),
		Body:        bytes.NewReader(data),
		ContentType: aws.String(contentType),
	}

	_, err := c.client.PutObject(ctx, input)
	if err != nil {
		return fmt.Errorf("failed to upload %s: %w", key, err)
	}

	// Record the uploaded file
	result.Keys[filename] = key
	result.URLs[filename] = c.generateS3URL(key)

	c.logger.Info("Uploaded file to S3",
		"key", key,
		"size", len(data),
	)

	return nil
}

// generateBaseKey creates a unique base path for the upload using incident ID
func (c *S3Client) generateBaseKey(data *collector.CollectedData) string {
	// Generate incident ID if not already set
	incidentID := data.GenerateIncidentID()

	if c.prefix != "" {
		return path.Join(c.prefix, incidentID)
	}

	return path.Join("devops-agent-operator", incidentID)
}

// generateS3URL creates an S3 URL for a key
func (c *S3Client) generateS3URL(key string) string {
	return fmt.Sprintf("s3://%s/%s", c.bucket, key)
}

// GetCollectedDataURL returns the S3 URL to the incident directory (incidents/<incident-id>)
func (r *S3UploadResult) GetCollectedDataURL() string {
	if r.BaseKey != "" {
		return fmt.Sprintf("s3://%s/%s", r.Bucket, r.BaseKey)
	}
	return ""
}

// GetHTTPURL returns an HTTPS URL for the collected data
func (r *S3UploadResult) GetHTTPURL(region string) string {
	if key, ok := r.Keys["collected-data.json"]; ok {
		return fmt.Sprintf("https://%s.s3.%s.amazonaws.com/%s", r.Bucket, region, key)
	}
	return ""
}
