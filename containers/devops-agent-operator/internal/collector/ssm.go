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
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

const (
	// SSM command timeout in seconds
	ssmCommandTimeout = 60
	// Max attempts to poll for command completion
	ssmMaxPollAttempts = 15
	// Poll interval between attempts
	ssmPollInterval = 2 * time.Second
	// Default time range for log collection in minutes
	defaultSinceMinutes = 15
)

// SSMCollector collects node logs via AWS Systems Manager
type SSMCollector struct {
	reader       client.Reader
	ssmClient    *ssm.Client
	region       string
	sinceMinutes int
	logger       logr.Logger
}

// NewSSMCollector creates a new SSMCollector
// Uses client.Reader (APIReader) to avoid cache and watch requirements for Node resources
func NewSSMCollector(reader client.Reader, region string, logger logr.Logger) (*SSMCollector, error) {
	// Load AWS config
	cfg, err := config.LoadDefaultConfig(context.Background(),
		config.WithRegion(region),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	ssmClient := ssm.NewFromConfig(cfg)

	return &SSMCollector{
		reader:       reader,
		ssmClient:    ssmClient,
		region:       region,
		sinceMinutes: defaultSinceMinutes,
		logger:       logger,
	}, nil
}

// WithSinceMinutes sets the time range for log collection
func (c *SSMCollector) WithSinceMinutes(minutes int) *SSMCollector {
	c.sinceMinutes = minutes
	return c
}

// CollectNodeLogs collects system logs from the node where the pod is running.
// podUID and containerIDs are used to filter df output for the specific pod's mounts.
func (c *SSMCollector) CollectNodeLogs(ctx context.Context, nodeName string, podUID string, containerIDs []string) (*NodeLogs, error) {
	if nodeName == "" {
		return nil, fmt.Errorf("node name is empty")
	}

	// Get node to extract instance ID (using APIReader to avoid watch requirement)
	var node corev1.Node
	if err := c.reader.Get(ctx, client.ObjectKey{Name: nodeName}, &node); err != nil {
		return nil, fmt.Errorf("failed to get node %s: %w", nodeName, err)
	}

	// Extract instance ID from provider ID
	instanceID := extractInstanceID(node.Spec.ProviderID)
	if instanceID == "" {
		return nil, fmt.Errorf("could not extract instance ID from node %s (providerID: %s)", nodeName, node.Spec.ProviderID)
	}

	c.logger.Info("Collecting node logs via SSM",
		"node", nodeName,
		"instanceID", instanceID,
	)

	// Collect logs using SSM
	nodeLogs, err := c.executeSSMCommands(ctx, instanceID, podUID, containerIDs)
	if err != nil {
		return nil, fmt.Errorf("failed to execute SSM commands: %w", err)
	}

	return nodeLogs, nil
}

// extractInstanceID extracts EC2 instance ID from the provider ID
// Format: aws:///region/instance-id or aws:///<zone>/instance-id
func extractInstanceID(providerID string) string {
	if providerID == "" {
		return ""
	}

	if !strings.HasPrefix(providerID, "aws://") {
		return ""
	}

	// Parse: aws:///us-east-1a/i-0b1b663f529ea6d9a -> i-0b1b663f529ea6d9a
	parts := strings.Split(providerID, "/")
	if len(parts) < 2 {
		return ""
	}

	// Last part is the instance ID
	instanceID := parts[len(parts)-1]
	if strings.HasPrefix(instanceID, "i-") {
		return instanceID
	}

	return ""
}

// ssmCommand defines a single SSM command to execute
type ssmCommand struct {
	name string
	cmd  string
}

// ssmResult holds the result of a single SSM command execution
type ssmResult struct {
	name   string
	output string
	err    error
}

// executeSSMCommands runs SSM commands on the instance in parallel and collects logs
func (c *SSMCollector) executeSSMCommands(ctx context.Context, instanceID string, podUID string, containerIDs []string) (*NodeLogs, error) {
	nodeLogs := &NodeLogs{}

	since := fmt.Sprintf("%d min ago", c.sinceMinutes)

	// Define commands for each log type
	commands := []ssmCommand{
		{
			name: "kubelet",
			cmd:  fmt.Sprintf("journalctl -u kubelet --since '%s' --no-pager 2>/dev/null || echo 'Kubelet logs not available'", since),
		},
		{
			name: "containerd",
			cmd:  fmt.Sprintf("journalctl -u containerd --since '%s' --no-pager 2>/dev/null || echo 'Containerd logs not available'", since),
		},
		{
			name: "ipamd",
			cmd: "POD_LOG=$(ls -t /var/log/pods/kube-system_aws-node-*/aws-node/0.log 2>/dev/null | head -1) && " +
				"if [ -n \"$POD_LOG\" ]; then tail -500 \"$POD_LOG\" 2>/dev/null; " +
				"else echo 'No IPAMD logs found'; fi",
		},
		{
			name: "ipamdIntrospection",
			cmd: "echo '=== ENIs ===' && " +
				"curl -s --max-time 3 http://localhost:61679/v1/enis 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== Pods ===' && " +
				"curl -s --max-time 3 http://localhost:61679/v1/pods 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== Environment Settings ===' && " +
				"curl -s --max-time 3 http://localhost:61679/v1/ipamd-env-settings 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== ENI Configs ===' && " +
				"curl -s --max-time 3 http://localhost:61679/v1/eni-configs 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== Metrics ===' && " +
				"curl -s --max-time 3 http://localhost:61678/metrics 2>/dev/null || echo 'Not available'",
		},
		{
			name: "dmesg",
			cmd:  fmt.Sprintf("dmesg -T --since '%d minutes ago' 2>/dev/null || dmesg -T | tail -500 2>/dev/null || echo 'Dmesg not available'", c.sinceMinutes),
		},
		{
			name: "networking",
			cmd: "echo '=== IP Routes ===' && " +
				"ip route show 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== IP Rules ===' && " +
				"ip rule show 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== Conntrack Count ===' && " +
				"conntrack -C 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== Conntrack Stats ===' && " +
				"conntrack -S 2>/dev/null || echo 'Not available'; " +
				"echo '' && echo '=== Netfilter Settings ===' && " +
				"sysctl net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_tcp_timeout_established 2>/dev/null || echo 'Not available'",
		},
		{
			name: "diskUsage",
			cmd:  c.buildDiskCommand("df -h", podUID, containerIDs),
		},
		{
			name: "inodeUsage",
			cmd:  c.buildDiskCommand("df --inodes", podUID, containerIDs),
		},
		{
			name: "memUsage",
			cmd:  "free -h 2>/dev/null || echo 'Memory usage not available'",
		},
	}

	// Execute all commands in parallel
	resultCh := make(chan ssmResult, len(commands))

	for _, cmd := range commands {
		go func(cmd ssmCommand) {
			output, err := c.sendSSMCommand(ctx, instanceID, []string{cmd.cmd})
			resultCh <- ssmResult{
				name:   cmd.name,
				output: output,
				err:    err,
			}
		}(cmd)
	}

	// Collect results
	var errors []string
	for range commands {
		result := <-resultCh

		if result.err != nil {
			c.logger.Error(result.err, "Failed to collect log", "logType", result.name)
			errors = append(errors, fmt.Sprintf("%s: %v", result.name, result.err))
			continue
		}

		// Assign output to the appropriate field
		switch result.name {
		case "kubelet":
			nodeLogs.Kubelet = strings.TrimSpace(result.output)
		case "containerd":
			nodeLogs.Containerd = strings.TrimSpace(result.output)
		case "ipamd":
			nodeLogs.IPAMD = strings.TrimSpace(result.output)
		case "ipamdIntrospection":
			nodeLogs.IPAMDIntrospection = strings.TrimSpace(result.output)
		case "dmesg":
			nodeLogs.Dmesg = strings.TrimSpace(result.output)
		case "networking":
			nodeLogs.Networking = strings.TrimSpace(result.output)
		case "diskUsage":
			nodeLogs.DiskUsage = strings.TrimSpace(result.output)
		case "inodeUsage":
			nodeLogs.InodeUsage = strings.TrimSpace(result.output)
		case "memUsage":
			nodeLogs.MemUsage = strings.TrimSpace(result.output)
		}
	}

	// Log errors but don't fail if some logs were collected
	if len(errors) > 0 {
		c.logger.Info("Some SSM commands failed", "errors", errors)
	}

	return nodeLogs, nil
}

// buildDiskCommand builds a df command with optional container-level filtering.
// baseCmd is either "df -h" or "df --inodes".
func (c *SSMCollector) buildDiskCommand(baseCmd string, podUID string, containerIDs []string) string {
	grepPattern := buildContainerGrepPattern(podUID, containerIDs)
	if grepPattern == "" {
		return fmt.Sprintf("%s -x overlay -x tmpfs -x shm 2>/dev/null || echo 'Disk usage not available'", baseCmd)
	}
	return fmt.Sprintf(
		"echo '=== Node ===' && %s -x overlay -x tmpfs -x shm 2>/dev/null && echo '' && echo '=== Pod Container Mounts ===' && (%s | head -1 && %s | grep -E '%s') 2>/dev/null || echo 'No container mounts found'",
		baseCmd, baseCmd, baseCmd, grepPattern,
	)
}

// buildContainerGrepPattern builds a grep -E pattern from podUID and containerIDs.
// Returns empty string if no identifiers are available.
func buildContainerGrepPattern(podUID string, containerIDs []string) string {
	var parts []string
	for _, id := range containerIDs {
		if id != "" {
			parts = append(parts, id)
		}
	}
	if podUID != "" {
		parts = append(parts, podUID)
	}
	if len(parts) == 0 {
		return ""
	}
	return strings.Join(parts, "|")
}

// sendSSMCommand sends a command via SSM and waits for the result
func (c *SSMCollector) sendSSMCommand(ctx context.Context, instanceID string, commands []string) (string, error) {
	// Send command
	sendInput := &ssm.SendCommandInput{
		InstanceIds:  []string{instanceID},
		DocumentName: aws.String("AWS-RunShellScript"),
		Parameters: map[string][]string{
			"commands": commands,
		},
		TimeoutSeconds: aws.Int32(ssmCommandTimeout),
	}

	sendOutput, err := c.ssmClient.SendCommand(ctx, sendInput)
	if err != nil {
		return "", fmt.Errorf("failed to send SSM command: %w", err)
	}

	commandID := *sendOutput.Command.CommandId
	c.logger.Info("SSM command sent",
		"commandID", commandID,
		"instanceID", instanceID,
	)

	// Wait for command completion
	for attempt := 0; attempt < ssmMaxPollAttempts; attempt++ {
		time.Sleep(ssmPollInterval)

		getInput := &ssm.GetCommandInvocationInput{
			CommandId:  aws.String(commandID),
			InstanceId: aws.String(instanceID),
		}

		getOutput, err := c.ssmClient.GetCommandInvocation(ctx, getInput)
		if err != nil {
			// Command might not be ready yet
			if strings.Contains(err.Error(), "InvocationDoesNotExist") {
				continue
			}
			return "", fmt.Errorf("failed to get command invocation: %w", err)
		}

		status := string(getOutput.Status)
		c.logger.Info("SSM command status",
			"commandID", commandID,
			"status", status,
			"attempt", attempt+1,
		)

		switch status {
		case "Success":
			return aws.ToString(getOutput.StandardOutputContent), nil
		case "Failed", "TimedOut", "Cancelled":
			stderr := aws.ToString(getOutput.StandardErrorContent)
			return "", fmt.Errorf("SSM command %s: %s", status, stderr)
		}
		// Continue polling for Pending, InProgress statuses
	}

	return "", fmt.Errorf("SSM command timed out after %d attempts", ssmMaxPollAttempts)
}
