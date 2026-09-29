apiVersion: apps/v1
kind: Deployment
metadata:
  name: sample-app
  namespace: default
  labels:
    app: sample-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sample-app
  template:
    metadata:
      labels:
        app: sample-app
        app.kubernetes.io/name: sample-app
      annotations:
        app.kubernetes.io/source-repository: "https://github.com/<YOUR_GITHUB_ORG>/<YOUR_REPO>"
        app.kubernetes.io/source-commit: "__COMMIT_SHA__"
        github.com/repository: "<YOUR_GITHUB_ORG>/<YOUR_REPO>"
        github.com/commit: "__COMMIT_SHA__"
    spec:
      containers:
        - name: app
          image: "__IMAGE__"
          resources:
            requests:
              cpu: 10m
              memory: 32Mi
            limits:
              cpu: 100m
              memory: 64Mi
