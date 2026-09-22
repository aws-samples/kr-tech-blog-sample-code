FROM golang:1.27.1@sha256:f44f6e88636cfb311f9ebace870ded69d943f227bb3cb27d32ffd84ea18c43ea AS builder
WORKDIR /src
ARG GOPROXY=https://proxy.golang.org,direct
ARG ACK_CONTROL_SDK_VERSION
ARG ACK_CONTROLLER_VERSION
ENV GOPROXY=$GOPROXY
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod test -n "$ACK_CONTROL_SDK_VERSION" && go get github.com/aws/aws-sdk-go-v2/service/bedrockagentcorecontrol@v${ACK_CONTROL_SDK_VERSION} && go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build test -n "$ACK_CONTROLLER_VERSION" && go get github.com/aws/aws-sdk-go-v2/service/bedrockagentcorecontrol@v${ACK_CONTROL_SDK_VERSION} && gofmt -w apis/v1alpha1/http_runtime.go pkg/resource/gateway_target/http_runtime*.go && go test -v ./pkg/resource/agent_runtime_endpoint ./pkg/resource/gateway_target ./pkg/resource/gateway && CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w -X github.com/aws-controllers-k8s/bedrockagentcorecontrol-controller/pkg/version.GitVersion=v${ACK_CONTROLLER_VERSION}" -o /controller ./cmd/controller
FROM public.ecr.aws/aws-controllers-k8s/bedrockagentcorecontrol-controller:1.15.1@sha256:d9510065c5306cdf216a73093cedef7b6cb2f5667cf7e0cd6212a85a99bf4c1b
ARG ACK_CONTROLLER_VERSION
LABEL org.opencontainers.image.version=$ACK_CONTROLLER_VERSION
COPY --from=builder /controller /bin/controller
