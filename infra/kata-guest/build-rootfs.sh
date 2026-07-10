#!/bin/bash
# PROOF 에이전트 게스트 rootfs 빌드 스크립트
#
# [Flow: Step 1 (Docker 이미지 빌드) -> Step 2 (rootfs 추출) -> Step 3 (ext4 이미지 생성)
#  -> Step 4 (Kata 설정에 이미지 등록) -> Step 5 (검증)]
#
# 사용법: sudo bash build-rootfs.sh
# 출력: /opt/kata/share/kata-containers/proof-agent.img (3GB ext4)
#
# 이 스크립트는 Docker 를 사용하여 게스트 rootfs 를 빌드한 후 ext4 이미지로 변환한다.
# Kata VM 은 이 ext4 이미지를 rootfs 로 마운트하여 부팅한다.

set -euo pipefail

# --- 상수 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="proof-agent-rootfs"
ROOTFS_DIR="/tmp/proof-agent-rootfs"
OUTPUT_IMG="/opt/kata/share/kata-containers/proof-agent.img"
IMG_SIZE="3G"

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ========================================
# Step 1: Docker 이미지 빌드
# ========================================
build_docker_image() {
    info "Step 1: Docker 이미지 빌드 (${IMAGE_NAME})"

    [[ "$(id -u)" -eq 0 ]] || error "root 권한이 필요합니다: sudo bash build-rootfs.sh"

    if ! command -v docker &>/dev/null; then
        error "Docker 가 설치되어 있지 않습니다."
    fi

    cd "${SCRIPT_DIR}"
    docker build -t "${IMAGE_NAME}" -f Dockerfile.rootfs .
    info "  Docker 이미지 빌드 완료: ${IMAGE_NAME}"
}

# ========================================
# Step 2: rootfs 추출
# ========================================
extract_rootfs() {
    info "Step 2: rootfs 추출"

    # 기존 추출 디렉토리 정리
    rm -rf "${ROOTFS_DIR}"
    mkdir -p "${ROOTFS_DIR}"

    # Docker 컨테이너에서 파일시스템 추출
    local container_id
    container_id=$(docker create "${IMAGE_NAME}")
    docker export "${container_id}" | tar -x -C "${ROOTFS_DIR}"
    docker rm "${container_id}" >/dev/null

    info "  rootfs 추출 완료: ${ROOTFS_DIR} ($(du -sh "${ROOTFS_DIR}" | cut -f1))"
}

# ========================================
# Step 3: ext4 이미지 생성
# ========================================
create_ext4_image() {
    info "Step 3: ext4 이미지 생성 (${IMG_SIZE})"

    # 출력 디렉토리 확인
    mkdir -p "$(dirname "${OUTPUT_IMG}")"

    # 기존 이미지 백업 (있는 경우)
    if [[ -f "${OUTPUT_IMG}" ]]; then
        local backup="${OUTPUT_IMG}.bak"
        cp "${OUTPUT_IMG}" "${backup}"
        info "  기존 이미지 백업: ${backup}"
    fi

    # ext4 이미지 생성 (rootfs 디렉토리를 이미지로 복사)
    # mkfs.ext4 -d 옵션은 디렉토리 내용을 ext4 이미지로 직접 복사
    mkfs.ext4 -d "${ROOTFS_DIR}" "${OUTPUT_IMG}" "${IMG_SIZE}"
    info "  ext4 이미지 생성 완료: ${OUTPUT_IMG} ($(ls -lh "${OUTPUT_IMG}" | awk '{print $5}'))"
}

# ========================================
# Step 4: Kata 설정에 이미지 등록
# ========================================
register_image() {
    info "Step 4: Kata 설정에 이미지 등록"

    local configs=(
        "/etc/kata-containers/configuration-clh.toml"
        "/etc/kata-containers/configuration-clh-dense.toml"
    )

    for config in "${configs[@]}"; do
        if [[ -f "${config}" ]]; then
            # image 라인이 있으면 수정, 없으면 추가
            if grep -q "^image\s*=" "${config}"; then
                sed -i "s|^image\s*=.*|image = \"${OUTPUT_IMG}\"|" "${config}"
            else
                # [hypervisor.cloud-hypervisor] 섹션 아래에 추가
                sed -i "/\[hypervisor.cloud-hypervisor\]/a image = \"${OUTPUT_IMG}\"" "${config}"
            fi
            info "  ${config} 에 image 등록"
        fi
    done
}

# ========================================
# Step 5: 검증
# ========================================
verify_image() {
    info "Step 5: 검증"

    # 이미지 파일 확인
    [[ -f "${OUTPUT_IMG}" ]] || error "이미지 파일이 생성되지 않음: ${OUTPUT_IMG}"
    info "  이미지 크기: $(ls -lh "${OUTPUT_IMG}" | awk '{print $5}')"

    # ext4 파일시스템 확인
    file "${OUTPUT_IMG}" | grep -q "ext4" || warn "이미지가 ext4 파일시스템이 아닐 수 있음"

    # 주요 파일 존재 확인
    local check_files=(
        "/opt/agent-runner/entrypoint.sh"
        "/opt/agent-runner/browserless-helper.py"
        "/usr/bin/python3"
        "/usr/bin/node"
        "/usr/bin/git"
        "/usr/bin/ffmpeg"
        "/usr/bin/tesseract"
        "/usr/bin/soffice"
        "/usr/bin/pandoc"
        "/usr/bin/pdftotext"
    )

    info "  주요 파일 확인:"
    for f in "${check_files[@]}"; do
        if [[ -e "${ROOTFS_DIR}${f}" ]]; then
            info "    OK: ${f}"
        else
            warn "    MISSING: ${f}"
        fi
    done

    # 정리
    info "  임시 rootfs 디렉토리 정리: ${ROOTFS_DIR}"
    rm -rf "${ROOTFS_DIR}"

    echo ""
    info "빌드 완료!"
    info "이미지: ${OUTPUT_IMG}"
    info "다음 단계: Kata VM 부팅 테스트"
    info "  sudo nerdctl run --runtime=io.containerd.kata-clh.v2 -it proof-agent-test"
}

# ========================================
# 메인 실행
# ========================================
main() {
    echo "=========================================="
    echo " PROOF 에이전트 게스트 rootfs 빌드"
    echo "=========================================="
    echo ""

    build_docker_image
    extract_rootfs
    create_ext4_image
    register_image
    verify_image
}

main "$@"
