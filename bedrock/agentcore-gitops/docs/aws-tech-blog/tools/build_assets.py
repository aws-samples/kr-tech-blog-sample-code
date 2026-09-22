from html import escape
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "docs/aws-tech-blog"
FIGURES = PACKAGE / "figures"
SNIPPETS = PACKAGE / "snippets"
FONT = "Apple SD Gothic Neo"
COLORS = {"ink": "#233044", "muted": "#53657A", "blue": "#2774AE", "green": "#197D63", "orange": "#C56B16", "purple": "#7551A6", "line": "#CCD5E0"}


class Diagram:
    def __init__(self, title, width, height):
        self.title = title
        self.width = width
        self.height = height
        self.model = ET.Element("mxGraphModel", {"dx": str(width), "dy": str(height), "grid": "1", "gridSize": "10", "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1", "pageWidth": str(width), "pageHeight": str(height), "background": "#FFFFFF", "math": "0", "shadow": "0"})
        self.root = ET.SubElement(self.model, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})
        self.counter = 0
        self.nodes = {}

    def cell(self, value, style, left, top, width, height, identifier=None):
        self.counter += 1
        identifier = identifier or f"cell-{self.counter}"
        element = ET.SubElement(self.root, "mxCell", {"id": identifier, "value": value, "style": style, "vertex": "1", "parent": "1"})
        ET.SubElement(element, "mxGeometry", {"x": str(left), "y": str(top), "width": str(width), "height": str(height), "as": "geometry"})
        self.nodes[identifier] = (left, top, width, height)
        return identifier

    def text(self, value, left, top, width, height, size=19, color=None, bold=False, align="left"):
        return self.cell(value, f"text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;align={align};verticalAlign=middle;spacing=0;fontFamily={FONT};fontSize={size};fontColor={color or COLORS['ink']};fontStyle={1 if bold else 0};", left, top, width, height)

    def frame(self, title, left, top, width, height, color, fill="#FFFFFF", dashed=False):
        identifier = self.cell("", f"rounded=0;html=1;fillColor={fill};strokeColor={color};strokeWidth=1.6;dashed={1 if dashed else 0};", left, top, width, height)
        self.text(title, left + 18, top + 10, width - 36, 32, 20, color, True)
        return identifier

    def node(self, identifier, title, detail, left, top, width, height, color="blue", icon=None):
        accent = COLORS[color]
        self.cell("", f"rounded=1;arcSize=10;html=1;fillColor=#FFFFFF;strokeColor={accent};strokeWidth=1.8;", left, top, width, height, identifier)
        text_left = left + 18
        text_width = width - 36
        if icon:
            self.cell("", f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{icon};fillColor={accent};strokeColor=none;gradientColor=none;aspect=fixed;", left + 16, top + 18, 42, 42)
            text_left = left + 72
            text_width = width - 86
        self.text(title, text_left, top + 13, text_width, 40, 21, accent, True)
        self.text(detail, left + 18, top + 57, width - 36, height - 64, 17, COLORS["muted"])
        return identifier

    def edge(self, source, target, color="blue", dashed=False, points=(), exit_point=(1, 0.5), entry_point=(0, 0.5)):
        self.counter += 1
        style = f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeWidth=2.2;strokeColor={COLORS[color]};dashed={1 if dashed else 0};exitX={exit_point[0]};exitY={exit_point[1]};entryX={entry_point[0]};entryY={entry_point[1]};exitDx=0;exitDy=0;entryDx=0;entryDy=0;jettySize=18;"
        element = ET.SubElement(self.root, "mxCell", {"id": f"edge-{self.counter}", "style": style, "edge": "1", "parent": "1", "source": source, "target": target})
        geometry = ET.SubElement(element, "mxGeometry", {"relative": "1", "as": "geometry"})
        if points:
            array = ET.SubElement(geometry, "Array", {"as": "points"})
            for horizontal, vertical in points:
                ET.SubElement(array, "mxPoint", {"x": str(horizontal), "y": str(vertical)})

    def label(self, text, left, top, width, color="blue"):
        return self.cell(escape(text), f"text;html=1;whiteSpace=wrap;align=center;verticalAlign=middle;fillColor=#FFFFFF;strokeColor=none;fontFamily={FONT};fontSize=15;fontColor={COLORS[color]};spacing=2;", left, top, width, 28)

    def export(self, path):
        for cell in self.root.findall("mxCell"):
            for attribute in ["id", "source", "target"]:
                value = cell.get(attribute)
                if value and value not in ["0", "1"]:
                    cell.set(attribute, f"{path.stem}-{value}")
        mxfile = ET.Element("mxfile", {"host": "Electron", "agent": "AWS Tech Blog asset generator", "version": "29.3.0", "type": "device"})
        page = ET.SubElement(mxfile, "diagram", {"id": path.stem, "name": self.title})
        page.append(self.model)
        ET.indent(mxfile, space="  ")
        ET.ElementTree(mxfile).write(path, encoding="utf-8", xml_declaration=True)


def architecture():
    diagram = Diagram("배포 아키텍처", 1760, 1100)
    diagram.text("기존 EKS GitOps로 AgentCore 배포하고 검증하기", 50, 27, 1490, 54, 34, bold=True)
    diagram.text("컨트롤러는 EKS에, 에이전트 실행은 AgentCore에 배치합니다.", 50, 82, 1210, 32, 20, COLORS["muted"])
    diagram.text("파랑  관리 및 배포     초록  요청 경로     주황  이미지     보라  관측", 50, 119, 1300, 28, 16, COLORS["muted"])
    diagram.frame("AWS 서비스 / 검증 리전 us-east-1 / Global 모델은 리전 간 라우팅 가능", 330, 160, 1380, 860, COLORS["ink"], "#FBFCFE")
    foundation = diagram.frame("VPC", 360, 215, 950, 545, COLORS["blue"], "#F4F8FC")
    diagram.frame("Amazon EKS / private subnets / 2 AZ / ARM64 worker nodes × 2", 390, 275, 890, 370, COLORS["blue"], "#FFFFFF")
    diagram.text("AWS managed services", 1365, 218, 300, 30, 19, COLORS["muted"], True)
    diagram.node("git", "Git 저장소", "Helm 차트 / values<br>main / 읽기 전용 키", 50, 335, 225, 110)
    diagram.node("cdk", "AWS CDK", "VPC / EKS / ECR / IAM<br>최초 기반 인프라 구축", 50, 515, 225, 110, "orange")
    diagram.node("admin", "관리자", "브라우저 / kubectl / k9s", 50, 665, 225, 100, "blue")
    diagram.node("argo", "Argo CD", "Git 변경 Pull<br>Helm 렌더링 / 자동 Sync", 420, 340, 220, 110, "blue")
    diagram.node("cr", "Kubernetes 선언", "AgentRuntime<br>Gateway / GatewayTarget", 705, 340, 240, 125, "blue")
    diagram.node("ack", "ACK Controller*", "CR 변경 → AWS API<br>실제 상태를 status에 기록", 1010, 340, 235, 110, "blue")
    diagram.node("analysis", "Argo Rollouts", "PostSync AnalysisRun<br>검증 Job → Gateway 실제 호출", 505, 515, 305, 105, "green")
    diagram.node("lbc", "ALB Controller", "관리용 Ingress / ALB 구성", 985, 520, 260, 100, "blue")
    diagram.text("EKS Pod Identity<br>IAM 실행 역할 분리", 420, 665, 215, 62, 18, COLORS["muted"])
    diagram.node("alb", "관리용 ALB", "Public subnets<br>HTTPS / 허용 IP 제한", 985, 655, 260, 98, "blue")
    diagram.node("ecr", "Amazon ECR", "Immutable image digest<br>AgentCore가 이미지 사용", 1365, 275, 305, 125, "orange", "ecr")
    diagram.node("logs", "CloudWatch Logs", "Runtime 실행 및 오류 로그", 1365, 535, 305, 100, "purple", "cloudwatch")
    diagram.text("실제 에이전트 호출 경로", 390, 807, 830, 35, 22, COLORS["green"], True)
    diagram.node("client", "애플리케이션", "IAM SigV4로 요청 서명", 50, 860, 225, 110, "green")
    diagram.node("gateway", "AgentCore Gateway", "HTTP Runtime target<br>/agent/invocations", 395, 860, 310, 115, "green")
    diagram.node("runtime", "AgentCore Runtime", "DEFAULT → 새 버전<br>ARM64 / Strands Agent", 845, 860, 350, 115, "green")
    diagram.node("model", "Amazon Bedrock", "Claude Sonnet 5<br>Global inference profile", 1365, 860, 305, 115, "purple", "bedrock")
    diagram.edge("git", "argo")
    diagram.edge("argo", "cr")
    diagram.edge("cr", "ack")
    diagram.edge("argo", "analysis", "green", True, [(465, 492), (655, 492)], (0.3, 1), (0.5, 0))
    diagram.edge("analysis", "gateway", "green", True, [(657, 780), (550, 780)], (0.5, 1), (0.5, 0))
    diagram.edge("lbc", "alb", "blue", True, (), (0.5, 1), (0.5, 0))
    diagram.edge("admin", "alb", "blue", False, [(303, 715), (303, 782), (1115, 782)], (1, 0.5), (0.5, 1))
    diagram.edge("alb", "argo", "blue", False, [(960, 700), (960, 484), (530, 484)], (0, 0.5), (0.5, 1))
    diagram.edge("cdk", foundation, "blue", True, [(305, 570), (305, 248), (360, 248)], (1, 0.5), (0, 0.06))
    diagram.edge("ack", "runtime", "blue", True, [(1270, 395), (1325, 395), (1325, 816), (1020, 816)], (1, 0.5), (0.5, 0))
    diagram.edge("ecr", "runtime", "orange", True, [(1688, 338), (1688, 785), (1218, 785), (1218, 838), (1160, 838)], (1, 0.5), (0.9, 0))
    diagram.edge("runtime", "logs", "purple", True, [(1230, 928), (1300, 928), (1300, 680), (1517, 680)], (1, 0.6), (0.5, 1))
    diagram.edge("client", "gateway", "green")
    diagram.edge("gateway", "runtime", "green")
    diagram.edge("runtime", "model", "green")
    diagram.label("Pull", 294, 353, 95)
    diagram.label("PostSync", 506, 477, 108, "green")
    diagram.label("HTTPS / 관리 전용", 715, 765, 180)
    diagram.label("CDK 기반 리소스 및 IAM / 컨트롤러 설치는 Helm", 630, 235, 520)
    diagram.label("UpdateAgentRuntime", 1040, 797, 235)
    diagram.label("이미지", 1515, 769, 80, "orange")
    diagram.label("로그", 1450, 660, 65, "purple")
    diagram.label("SigV4", 292, 878, 92, "green")
    diagram.label("DEFAULT", 717, 878, 115, "green")
    diagram.label("모델 호출", 1210, 878, 130, "green")
    diagram.text("* ACK 1.15.1 확장 패치 사용. Runtime과 Gateway/Target을 관리합니다. NAT, VPC endpoint, 관리용 EKS API 경로는 생략했습니다.", 50, 1043, 1650, 28, 16, COLORS["muted"])
    return diagram


def pipeline():
    diagram = Diagram("배포 파이프라인", 1760, 1110)
    diagram.text("이미지 빌드부터 Gateway 호출 검증까지", 50, 28, 1570, 53, 34, bold=True)
    diagram.text("Runtime 재배포와 배포 후 분석 / 네이티브 blueGreen/canary는 구현하지 않았습니다.", 50, 82, 1600, 33, 20, COLORS["muted"])
    diagram.frame("1  개발자 / 빌드 환경: 검증에서는 로컬 스크립트 사용, CI로 확장 가능", 50, 145, 1660, 245, COLORS["orange"], "#FFF9F1")
    steps = [
        ("test", "코드와 테스트", "Python / CDK / Helm 검증", 85),
        ("build", "ARM64 이미지 빌드", "non-root + 고정 의존성", 475),
        ("push", "ECR Push", "고유 태그 → digest 조회", 865),
        ("commit", "Git 변경 및 Push", "imageUri / release / build", 1255),
    ]
    for identifier, title, detail, left in steps:
        diagram.node(identifier, title, detail, left, 225, 335, 100, "orange")
    for source, target in [("test", "build"), ("build", "push"), ("push", "commit")]:
        diagram.edge(source, target, "orange")
    diagram.text("ECR에 이미지만 올려서는 배포되지 않습니다. Git의 imageUri digest 변경이 배포 입력입니다.", 88, 341, 1520, 28, 18, COLORS["orange"])
    diagram.frame("2  Argo CD + ACK: EKS 안에서 변경을 Pull하고 AWS 리소스에 반영", 50, 430, 1660, 258, COLORS["blue"], "#F4F8FC")
    for identifier, title, detail, left in [
        ("ready", "Runtime READY", "DEFAULT → 새 Runtime 버전", 85),
        ("update", "ACK → AWS API", "새 이미지로 Runtime 업데이트", 475),
        ("render", "Helm → CR 적용", "AgentRuntime / Gateway / Target", 865),
        ("pull", "Argo CD Pull", "Git main 변경 감지", 1255),
    ]:
        diagram.node(identifier, title, detail, left, 516, 335, 105, "blue")
    diagram.edge("commit", "pull", "blue", False, (), (0.5, 1), (0.5, 0))
    for source, target in [("pull", "render"), ("render", "update"), ("update", "ready")]:
        diagram.edge(source, target, "blue", False, (), (0, 0.5), (1, 0.5))
    diagram.text("기존 Gateway URL은 유지됩니다. DEFAULT 전환은 아래 검증보다 먼저 일어나므로 사전 승격 절차가 아닙니다.", 88, 640, 1560, 30, 18, COLORS["blue"])
    diagram.frame("3  Argo Rollouts AnalysisRun: 실제 Gateway 요청으로 배포 결과 판정", 50, 730, 1660, 268, COLORS["green"], "#F3FAF7")
    diagram.node("analysis", "PostSync AnalysisRun", "새 검증 Job 생성<br>전용 Pod Identity 사용", 85, 815, 335, 118, "green")
    diagram.node("call", "Gateway 실제 호출", "예상 digest / release / build<br>모델 응답 비교", 475, 815, 335, 118, "green")
    diagram.node("success", "Successful", "Argo 작업 Succeeded<br>Synced / Healthy", 1000, 785, 625, 92, "green")
    diagram.node("failure", "Failed", "실패를 표시하고 운영자가 판단<br>자동 Runtime rollback은 없음", 1000, 890, 625, 92, "orange")
    diagram.edge("ready", "analysis", "green", True, [(42, 568), (42, 785), (252, 785)], (0, 0.5), (0.5, 0))
    diagram.edge("analysis", "call", "green")
    diagram.edge("call", "success", "green", False, [(904, 874), (904, 831)], (1, 0.5), (0, 0.5))
    diagram.edge("call", "failure", "orange", False, [(904, 874), (904, 936)], (1, 0.5), (0, 0.5))
    diagram.label("검증 통과", 862, 803, 123, "green")
    diagram.label("검증 실패", 862, 942, 123, "orange")
    diagram.text("지속 트래픽 시험은 별도 실행: 배포 전 → 배포 중 → 배포 완료 후 90초 이상 같은 프로세스 유지", 50, 1030, 1660, 31, 20, COLORS["ink"], True)
    diagram.text("9월 18일 Git 변경 시험 106/106 / 9월 21일 local values 시험 180/180 / 낮은 부하의 짧은 JSON 요청에 한정", 50, 1068, 1660, 25, 17, COLORS["muted"])
    return diagram


def snippets():
    SNIPPETS.mkdir(parents=True, exist_ok=True)
    for source, name in [
        ("charts/agentcore-agent/Chart.yaml", "Chart.yaml"),
        ("charts/agentcore-agent/templates/runtime.yaml", "runtime.tpl.yaml"),
        ("charts/agentcore-agent/templates/gateway.yaml", "gateway.tpl.yaml"),
        ("charts/agentcore-agent/templates/analysis.yaml", "analysis.tpl.yaml"),
        ("charts/agentcore-agent/templates/endpoint.yaml", "endpoint.tpl.yaml"),
        ("config/ack-values.yaml", "ack-values.yaml"),
        ("config/argocd-values.yaml", "argocd-values.yaml"),
        ("gitops/application.yaml", "application.yaml"),
        ("gitops/project.yaml", "project.yaml"),
    ]:
        content = (ROOT / source).read_text()
        content = re.sub(r"(?<=github.com/)[^\s\"']+", "YOUR_GITHUB_ORG/YOUR_REPOSITORY.git", content)
        (SNIPPETS / name).write_text(content)
    digest = "a" * 64
    verifier = "b" * 64
    values = f'''runtime:
  name: eks_ack_devops
  imageUri: "123456789012.dkr.ecr.us-east-1.amazonaws.com/eks-ack-agentcore@sha256:{digest}"
  roleArn: "arn:aws:iam::123456789012:role/AgentCoreRuntimeExecutionRole"
  region: us-east-1
  modelId: global.anthropic.claude-sonnet-5
  release: v8
  buildRevision: gateway-v8
gateway:
  enabled: true
  name: eks-ack-devops-gateway
  roleArn: "arn:aws:iam::123456789012:role/AgentCoreGatewayExecutionRole"
  runtimeArn: "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/eks_ack_devops-0123456789"
  targetName: agent
analysis:
  enabled: true
  imageUri: "123456789012.dkr.ecr.us-east-1.amazonaws.com/eks-ack-agentcore@sha256:{verifier}"
endpoint:
  enabled: false
  runtimeId: eks_ack_devops-0123456789
  version: "2"
  name: live
'''
    (SNIPPETS / "dev-values.example.yaml").write_text(values)
    (SNIPPETS / "load-balancer-values.example.yaml").write_text('''clusterName: eks-ack-agentcore
region: us-east-1
vpcId: vpc-0123456789abcdef0
serviceAccount:
  name: aws-load-balancer-controller
''')
    (SNIPPETS / "rollouts-values.yaml").write_text('''dashboard:
  enabled: false
''')


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    architecture().export(FIGURES / "architecture.drawio")
    pipeline().export(FIGURES / "deployment-pipeline.drawio")
    snippets()
    for filename in FIGURES.glob("*.drawio"):
        root = ET.parse(filename).getroot()
        cells = root.findall(".//mxCell")
        ids = [cell.get("id") for cell in cells]
        assert len(ids) == len(set(ids)), filename
        for cell in cells:
            for attribute in ["source", "target"]:
                if cell.get(attribute):
                    assert cell.get(attribute) in ids
        print(f"Validated {filename.relative_to(ROOT)}: {len(cells)} native cells")


if __name__ == "__main__":
    main()
