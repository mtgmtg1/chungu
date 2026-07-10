# PROOF 에이전트 Kata Agent Policy (OPA/Rego)
#
# [Flow: Step 1 (kata-agent ttRPC 요청 수신) -> Step 2 (OPA 정책 평가) -> Step 3 (허용/거부 결정)]
#
# 이 파일은 Kata 게스트 내부의 kata-agent 가 ttRPC API 호출을 검증할 때 사용하는 OPA 정책이다.
# 호스트가 신뢰할 수 없는 환경에서 추가 보안 계층을 제공한다.
#
# 적용 방법:
#   1. 게스트 rootfs 빌드 시 AGENT_POLICY=yes 옵션 사용
#   2. 이 파일을 /etc/kata-opa/default-policy.rego 에 배치
#   3. Kata 설정에 agent_policy 경로 지정
#
# 정책 평가 대상:
#   - CreateContainer: 컨테이너 이미지/명령 화이트리스트 검사
#   - ExecProcess: 명령어 블랙리스트 검사
#   - StartContainer: 컨테이너 시작 검증

package kata

# 기본 규칙: 명시적으로 거부되지 않으면 허용
default allow = true

# ========================================
# CreateContainer 요청 검증
# ========================================

# 컨테이너 생성 시 이미지와 명령을 검증한다.
allow {
  input.method == "CreateContainer"
  not deny_create_container
}

# 거부 조건: 화이트리스트에 없는 이미지
deny_create_container {
  input.method == "CreateContainer"
  not allowed_image
}

# 거부 조건: 위험 명령어 포함
deny_create_container {
  input.method == "CreateContainer"
  contains_dangerous_command(input.params.command)
}

# 허용된 컨테이너 이미지 (화이트리스트)
# proof-agent 이미지만 허용, 다른 이미지는 차단
allowed_image {
  input.params.image == "proof-agent:latest"
}

allowed_image {
  input.params.image == "proof-agent-rootfs:latest"
}

# 빈 이미지 (rootfs 직접 마운트 시)
allowed_image {
  input.params.image == ""
}

# ========================================
# ExecProcess 요청 검증
# ========================================

# 프로세스 실행 시 명령어를 검증한다.
allow {
  input.method == "ExecProcess"
  not deny_exec_process
}

# 거부 조건: 위험 명령어 포함
deny_exec_process {
  input.method == "ExecProcess"
  contains_dangerous_command(input.params.command)
}

# ========================================
# StartContainer 요청 검증
# ========================================

# 컨테이너 시작은 항상 허용 (이미 CreateContainer 에서 검증됨)
allow {
  input.method == "StartContainer"
}

# ========================================
# 위험 명령어 감지 (블랙리스트)
# ========================================

# 위험 명령어 패턴 목록
dangerous_commands := [
  "rm -rf /",
  "rm -rf /*",
  "dd if=.*of=/dev/",
  "mkfs",
  "mount -t",
  "umount",
  "sysctl -w",
  "insmod",
  "rmmod",
  "modprobe",
  "reboot",
  "shutdown",
  "halt",
  "poweroff",
  "init 0",
  "init 6",
  ":(){ :|:& };:",
  "curl .*| sh",
  "curl .*| bash",
  "wget .*| sh",
  "wget .*| bash",
  "chmod .*777 /",
  "iptables -F",
  "iptables -X",
  "nft flush ruleset",
]

# 명령어가 위험 패턴을 포함하는지 검사
contains_dangerous_command(cmd) {
  pattern := dangerous_commands[_]
  regex.match(pattern, cmd)
}

# 빈 명령어는 허용
contains_dangerous_command("") {
  false
}

# ========================================
# 네임스페이스 생성 제한
# ========================================

# CLONE_NEWUSER 를 사용하는 clone 시스콜은 거부
allow {
  input.method == "ExecProcess"
  not contains_clone_newuser(input.params.command)
}

contains_clone_newuser(cmd) {
  regex.match(".*--user.*", cmd)
}

contains_clone_newuser(cmd) {
  regex.match(".*unshare.*--user.*", cmd)
}

contains_clone_newuser(cmd) {
  regex.match(".*CLONE_NEWUSER.*", cmd)
}
