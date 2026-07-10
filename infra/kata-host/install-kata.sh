#!/bin/bash
# PROOF Kata Containers 호스트 설치 스크립트
#
# [Flow: Step 1 (사전 요구사항 확인) -> Step 2 (containerd 설치) -> Step 3 (Kata + Cloud Hypervisor 설치)
#  -> Step 4 (설정 파일 배포) -> Step 5 (RuntimeClass 등록) -> Step 6 (메모리 최적화: /dev/shm, THP, KSM, zRAM)
#  -> Step 7 (동작 검증)]
#
# 사용법: sudo bash install-kata.sh
# 대상: Ubuntu 24.04 LTS 베어메탈 (Xeon 6230 dual, 512GB RAM)
#
# 이 스크립트는 멱등성(idempotent)을 가진다 — 여러 번 실행해도 안전하다.

set -euo pipefail

# --- 상수 ---
KATA_VERSION="3.31.0"
KATA_ARCH="amd64"
KATA_INSTALL_DIR="/opt/kata"
KATA_TARBALL="kata-static-${KATA_VERSION}-${KATA_ARCH}.tar.zst"
KATA_URL="https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/${KATA_TARBALL}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ========================================
# Step 1: 사전 요구사항 확인
# ========================================
check_prerequisites() {
    info "Step 1: 사전 요구사항 확인"

    # root 권한 확인
    [[ "$(id -u)" -eq 0 ]] || error "이 스크립트는 root 권한이 필요합니다: sudo bash install-kata.sh"

    # Ubuntu 버전 확인
    if ! grep -q "Ubuntu 24.04" /etc/os-release 2>/dev/null; then
        warn "Ubuntu 24.04 가 아닐 수 있습니다. 계속 진행합니다..."
    fi

    # KVM 활성화 확인
    if [[ ! -e /dev/kvm ]]; then
        error "KVM 장치가 없습니다 (/dev/kvm). BIOS에서 VT-x/VT-d를 활성화하세요."
    fi
    info "  KVM 확인: /dev/kvm 존재"

    # KVM 모듈 로드
    modprobe kvm_intel 2>/dev/null || warn "kvm_intel 모듈 로드 실패 (이미 로드되어 있을 수 있음)"

    # CPU 가상화 지원 확인
    if ! grep -q "vmx\|ept" /proc/cpuinfo; then
        error "CPU가 VT-x/EPT를 지원하지 않습니다."
    fi
    info "  CPU 가상화 확인: VT-x + EPT 지원"

    # vhost_vsock 모듈 (Cloud Hypervisor 통신용)
    modprobe vhost_vsock 2>/dev/null || true
    modprobe vmw_vmci 2>/dev/null || true
}

# ========================================
# Step 2: containerd 설치
# ========================================
install_containerd() {
    info "Step 2: containerd 설치"

    if command -v containerd &>/dev/null; then
        info "  containerd 이미 설치됨: $(containerd --version)"
    else
        apt-get update -qq
        apt-get install -y -qq containerd
        info "  containerd 설치 완료"
    fi

    # 기본 설정 생성
    mkdir -p /etc/containerd
    if [[ ! -f /etc/containerd/config.toml ]]; then
        containerd config default | tee /etc/containerd/config.toml >/dev/null
    fi

    # SystemdCgroup 활성화
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    info "  SystemdCgroup = true 설정"
}

# ========================================
# Step 3: Kata Containers + Cloud Hypervisor 설치
# ========================================
install_kata() {
    info "Step 3: Kata Containers ${KATA_VERSION} + Cloud Hypervisor 설치"

    if [[ -x "${KATA_INSTALL_DIR}/bin/cloud-hypervisor" ]]; then
        info "  Kata 이미 설치됨: ${KATA_INSTALL_DIR}"
        return
    fi

    # 의존성 패키지
    apt-get install -y -qq zstd wget

    # tarball 다운로드
    local tmpdir
    tmpdir="$(mktemp -d)"
    info "  다운로드: ${KATA_URL}"
    wget -q -O "${tmpdir}/${KATA_TARBALL}" "${KATA_URL}"

    # tarball 내부 경로가 ./opt/kata/ 임 — 루트(/)에 추출하면 /opt/kata/ 에 위치
    info "  압축 해제: /opt/kata"
    tar --zstd -xf "${tmpdir}/${KATA_TARBALL}" -C /

    # 바이너리 확인
    [[ -x "${KATA_INSTALL_DIR}/bin/cloud-hypervisor" ]] || error "cloud-hypervisor 바이너리 없음"
    [[ -x "${KATA_INSTALL_DIR}/libexec/virtiofsd" ]]   || error "virtiofsd 바이너리 없음"
    [[ -f "${KATA_INSTALL_DIR}/share/kata-containers/vmlinux.container" ]] || error "게스트 커널 없음"
    [[ -f "${KATA_INSTALL_DIR}/share/kata-containers/kata-containers.img" ]] || error "게스트 이미지 없음"

    info "  Cloud Hypervisor: $(${KATA_INSTALL_DIR}/bin/cloud-hypervisor --version 2>&1 | head -1)"
    info "  virtiofsd: ${KATA_INSTALL_DIR}/libexec/virtiofsd"
    info "  게스트 커널: ${KATA_INSTALL_DIR}/share/kata-containers/vmlinux.container"

    # 정리
    rm -rf "${tmpdir}"
}

# ========================================
# Step 4: 설정 파일 배포
# ========================================
deploy_configs() {
    info "Step 4: Kata 설정 파일 배포"

    mkdir -p /etc/kata-containers

    # 기본 모드 설정 (150 VM, 2GB/VM, DAX 1GB)
    cp "${SCRIPT_DIR}/configuration-clh.toml" /etc/kata-containers/configuration-clh.toml
    info "  기본 모드: /etc/kata-containers/configuration-clh.toml"

    # 고밀도 모드 설정 (300+ VM, 512MB/VM, DAX 256MB)
    cp "${SCRIPT_DIR}/configuration-clh-dense.toml" /etc/kata-containers/configuration-clh-dense.toml
    info "  고밀도 모드: /etc/kata-containers/configuration-clh-dense.toml"

    # seccomp 프로필 (있는 경우)
    if [[ -f "${SCRIPT_DIR}/seccomp-proof-agent.json" ]]; then
        cp "${SCRIPT_DIR}/seccomp-proof-agent.json" /etc/kata-containers/seccomp-proof-agent.json
        info "  seccomp 프로필: /etc/kata-containers/seccomp-proof-agent.json"
    fi

    # AppArmor 프로필 (있는 경우)
    if [[ -f "${SCRIPT_DIR}/apparmor-proof-agent" ]]; then
        cp "${SCRIPT_DIR}/apparmor-proof-agent" /etc/apparmor.d/proof-agent
        apparmor_parser -r /etc/apparmor.d/proof-agent 2>/dev/null || warn "AppArmor 프로필 로드 실패 (apparmor 서비스 확인)"
        info "  AppArmor 프로필: /etc/apparmor.d/proof-agent"
    fi

    # Kata Agent Policy (OPA, 심화 보안)
    if [[ -f "${SCRIPT_DIR}/kata-opa-policy.rego" ]]; then
        mkdir -p /etc/kata-opa
        cp "${SCRIPT_DIR}/kata-opa-policy.rego" /etc/kata-opa/default-policy.rego
        info "  Agent Policy (OPA): /etc/kata-opa/default-policy.rego"
    fi
}

# ========================================
# Step 5: containerd RuntimeClass 등록
# ========================================
register_runtimeclass() {
    info "Step 5: containerd RuntimeClass 등록"

    # shim 래퍼 스크립트 생성 (기본 모드)
    cat > /usr/local/bin/containerd-shim-kata-clh-v2 << 'SHIM_EOF'
#!/bin/sh
# Kata Cloud Hypervisor shim (기본 모드)
KATA_CONF_FILE=/etc/kata-containers/configuration-clh.toml
exec /opt/kata/bin/containerd-shim-kata-v2 "$@"
SHIM_EOF
    chmod +x /usr/local/bin/containerd-shim-kata-clh-v2
    info "  shim (기본): /usr/local/bin/containerd-shim-kata-clh-v2"

    # shim 래퍼 스크립트 생성 (고밀도 모드)
    cat > /usr/local/bin/containerd-shim-kata-clh-dense-v2 << 'SHIM_EOF'
#!/bin/sh
# Kata Cloud Hypervisor shim (고밀도 모드 — 300+ VM)
KATA_CONF_FILE=/etc/kata-containers/configuration-clh-dense.toml
exec /opt/kata/bin/containerd-shim-kata-v2 "$@"
SHIM_EOF
    chmod +x /usr/local/bin/containerd-shim-kata-clh-dense-v2
    info "  shim (고밀도): /usr/local/bin/containerd-shim-kata-clh-dense-v2"

    # containerd config.toml 에 RuntimeClass 등록
    # 기존 [plugins..."io.containerd.cri.v1.runtime".containerd.runtimes] 섹션에 추가
    if ! grep -q "kata-clh" /etc/containerd/config.toml; then
        # containerd 2.x 설정 형식
        local runtime_section='
[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-clh]
  runtime_type = "io.containerd.kata-clh.v2"

[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-clh-dense]
  runtime_type = "io.containerd.kata-clh-dense.v2"
'
        echo "${runtime_section}" >> /etc/containerd/config.toml
        info "  RuntimeClass 등록: kata-clh, kata-clh-dense"
    else
        info "  RuntimeClass 이미 등록됨"
    fi

    # containerd 재시작
    systemctl restart containerd
    info "  containerd 재시작 완료"
}

# ========================================
# Step 6: 메모리 최적화 (/dev/shm, THP, KSM, zRAM)
# ========================================
optimize_memory() {
    info "Step 6: 메모리 최적화 (/dev/shm, THP 비활성화, KSM 활성화, zRAM)"

    # --- 6.1: /dev/shm 확장 (DAX 윈도우 백엔드) ---
    # 기본 모드: 150 VM × 1GB DAX = 150GB + 여유 = 160GB
    # 고밀도 모드: 300 VM × 256MB DAX = 75GB
    # 두 모드를 모두 수용하기 위해 160GB로 설정
    local shm_size="160G"
    if ! grep -q "tmpfs.*shm.*${shm_size}" /etc/fstab 2>/dev/null; then
        echo "tmpfs /dev/shm tmpfs defaults,size=${shm_size} 0 0" >> /etc/fstab
    fi
    mount -o remount,size="${shm_size}" /dev/shm
    info "  /dev/shm 크기: ${shm_size} (DAX 윈도우 백엔드)"

    # --- 6.2: THP (Transparent Huge Pages) 비활성화 ---
    # KSM은 4KB 단위 페이지에서만 작동하므로 THP(2MB)가 켜져 있으면 페이지 병합률이 급격히 저하됨
    # THP를 비활성화하여 KSM이 4KB 페이지를 촘촘하게 스캔하고 병합하도록 유도
    echo never > /sys/kernel/mm/transparent_hugepage/enabled
    echo never > /sys/kernel/mm/transparent_hugepage/defrag
    info "  THP 비활성화: never (KSM 4KB 페이지 병합 최적화)"

    # THP 비활성화 systemd 서비스 (재부팅 후에도 유지)
    cat > /etc/systemd/system/disable-thp.service << 'THP_EOF'
[Unit]
Description=Disable Transparent Huge Pages (THP) for KSM efficiency
After=sysinit.target local-fs.target
Before=kata-containers.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
THP_EOF
    systemctl enable disable-thp.service 2>/dev/null
    info "  THP 비활성화 서비스 등록: disable-thp.service"

    # --- 6.3: KSM (Kernel Same-page Merging) 활성화 ---
    # 동일 게스트 커널/라이브러리 페이지를 병합하여 메모리 절약 (30-50%)
    # THP 비활성화 후 4KB 페이지 단위로 촘촘하게 스캔
    echo 1 > /sys/kernel/mm/ksm/run
    echo 1000 > /sys/kernel/mm/ksm/pages_to_scan

    # KSM 영구 설정
    cat > /etc/sysctl.d/99-ksm.conf << 'KSM_EOF'
# KSM (Kernel Same-page Merging) — 동일 페이지 병합으로 메모리 절약
kernel.mm.ksm_run = 1
kernel.mm.ksm_pages_to_scan = 1000
KSM_EOF
    info "  KSM 활성화: pages_to_scan=1000"

    # --- 6.4: zRAM 압축 스왑 (옵션 — 고밀도 모드에서 권장) ---
    # zRAM 은 RAM 일부를 압축 블록 디바이스로 사용하여 cold page 를 압축 저장
    # zstd 압축으로 3:1 압축률, 디스크 I/O 없이 RAM 내 처리
    if ! lsmod | grep -q zram; then
        modprobe zram num_devices=1
        echo zstd > /sys/block/zram0/comp_algorithm 2>/dev/null || true
        echo 128G > /sys/block/zram0/disksize 2>/dev/null || true
        mkswap /dev/zram0 2>/dev/null || true
        swapon -p 100 /dev/zram0 2>/dev/null || warn "zRAM 설정 실패 (이미 설정되어 있을 수 있음)"
        info "  zRAM 압축 스왑: 128GB (zstd, 우선순위 100)"
    else
        info "  zRAM 이미 활성화됨"
    fi

    # zRAM 영구 설정 (systemd 서비스)
    cat > /etc/systemd/system/zram-setup.service << 'ZRAM_EOF'
[Unit]
Description=Setup zRAM compressed swap
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'modprobe zram num_devices=1 && echo zstd > /sys/block/zram0/comp_algorithm && echo 128G > /sys/block/zram0/disksize && mkswap /dev/zram0 && swapon -p 100 /dev/zram0'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
ZRAM_EOF
    systemctl enable zram-setup.service 2>/dev/null

    # --- 6.5: 메모리 오버커밋 허용 ---
    # zRAM + KSM 조합으로 안전하게 오버커밋
    echo 1 > /proc/sys/vm/overcommit_memory
    echo 50 > /proc/sys/vm/swappiness
    cat > /etc/sysctl.d/99-memory-overcommit.conf << 'OVERCOMMIT_EOF'
# 메모리 오버커밋 허용 (zRAM + KSM 으로 안전)
vm.overcommit_memory = 1
vm.swappiness = 50
OVERCOMMIT_EOF
    info "  메모리 오버커밋: overcommit_memory=1, swappiness=50"
}

# ========================================
# Step 7: 동작 검증
# ========================================
verify_installation() {
    info "Step 7: 동작 검증"

    # Kata 런타임 확인
    if [[ -x /opt/kata/bin/kata-runtime ]]; then
        /opt/kata/bin/kata-runtime check 2>&1 | head -20 || warn "kata-runtime check 경고"
    else
        info "  kata-runtime 바이너리 없음 (kata-static 에는 포함되지 않을 수 있음)"
    fi

    # containerd RuntimeClass 확인
    if command -v ctr &>/dev/null; then
        info "  containerd 런타임 목록:"
        ctr plugins list 2>/dev/null | grep -i kata || warn "kata 런타임이 containerd에 등록되지 않음"
    fi

    # nerdctl 설치 안내
    if ! command -v nerdctl &>/dev/null; then
        info "  nerdctl 설치 권장 (테스트용):"
        info "    wget https://github.com/containerd/nerdctl/releases/download/v1.7.5/nerdctl-1.7.5-linux-amd64.tar.gz"
        info "    sudo tar Cxzvvf /usr/local/bin nerdctl-1.7.5-linux-amd64.tar.gz"
    fi

    # 메모리 최적화 상태 확인
    info "  메모리 최적화 상태:"
    info "    THP: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
    info "    KSM: run=$(cat /sys/kernel/mm/ksm/run), pages_to_scan=$(cat /sys/kernel/mm/ksm/pages_to_scan)"
    info "    /dev/shm: $(df -h /dev/shm | tail -1 | awk '{print $2}')"
    if swapon --show 2>/dev/null | grep -q zram; then
        info "    zRAM: $(swapon --show | grep zram | awk '{print $3}')"
    fi

    echo ""
    info "설치 완료!"
    info "다음 단계:"
    info "  1. nerdctl 설치 후 테스트: sudo nerdctl run --runtime=io.containerd.kata-clh.v2 -it busybox sh"
    info "  2. 게스트 이미지 빌드: cd infra/kata-guest && sudo bash build-rootfs.sh"
    info "  3. DAX 확인: VM 내부에서 'mount | grep virtiofs' 시 dax 옵션 확인"
}

# ========================================
# 메인 실행
# ========================================
main() {
    echo "=========================================="
    echo " PROOF Kata Containers 호스트 설치"
    echo " Kata ${KATA_VERSION} + Cloud Hypervisor"
    echo "=========================================="
    echo ""

    check_prerequisites
    install_containerd
    install_kata
    deploy_configs
    register_runtimeclass
    optimize_memory
    verify_installation
}

main "$@"
