# Kata Containers + Cloud Hypervisor 기반 에이전트 격리 실행 환경 구축 플랜

## 1. 목표

PROOF 결과 페이지의 문서/이미지/오디오/비디오 파일들을 격리된 Kata Containers microVM 내부의 실제 폴더로 마운트한다. 에이전트가 이 폴더를 하나의 리포지토리처럼 사용해 자유롭게 코드 작성, 파일 다운로드, 실행할 수 있도록 한다. 모든 실행은 VM 수준 격리로 호스트 커널과 분리된다.

### 핵심 설계 원칙

1. **시스템 파괴 작업 차단**: 에이전트가 호스트/게스트 시스템을 파괴하는 명령(`rm -rf /`, `dd if=/dev/zero of=/dev/sda`, `mkfs`, `mount`, `sysctl`, 커널 모듈 로드 등)을 실행할 수 없도록 다층 방어 (seccomp + capabilities drop + read-only rootfs + AppArmor)
2. **문서/미디어 처리 환경 사전 구성**: 인스턴스 생성 시 문서 변환, OCR, 오디오/비디오 처리, 이미지 처리에 필요한 모든 도구가 즉시 사용 가능해야 함 (LibreOffice, Pandoc, Tesseract, FFmpeg, ImageMagick, Whisper, Pillow, OpenCV 등)
3. **browserless 서버 재사용**: a1에 이미 구동 중인 browserless 서버(`http://192.168.1.50:20047`)를 모든 인스턴스가 공유하여 사용. 각 VM에 Chrome/Puppeteer를 띄우지 않아 RAM 절약
4. **리소스 효율성**: virtio-mem 동적 메모리, KSM 페이지 병합, snapshot 기반 빠른 시작, virtio-fs cache=auto, reclaim_guest_freed_memory 등으로 메모리/CPU 절약

### 기술 스택 요약

- **VMM**: Cloud Hypervisor (rust-vmm 기반, virtio-fs 지원, 가벼운 footprint)
- **컨테이너 런타임**: containerd + kata-clh RuntimeClass
- **오케스트레이션**: 단일 서버 베어메탈 (Xeon 6230 dual, 512GB RAM, 1.8TB NVMe)
- **에이전트 실행 단위**: 사용자 1회 에이전트 실행 = 1개 Kata microVM
- **웹 브라우징**: a1의 browserless 서버 공유 (`http://192.168.1.50:20047`)

---

## 2. 아키텍처

```text
┌──────────────────────────────────────────────────────────────┐
│  Frontend (React/Vite)                                       │
│  AgentChatModal -> POST /api/ai/chat                         │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────┐
│  Python FastAPI (기존)        │                               │
│  /api/ai/* 리버스 프록시      │                               │
│  /api/jobs/* /api/v1/*       │                               │
│  + 신규 /api/sandboxes/*     │                               │
└──────────────────────────────┼───────────────────────────────┘
                               │
         ┌─────────────────────┼──────────────────────┐
         │                     │                      │
┌────────▼─────────┐  ┌────────▼─────────┐  ┌────────▼──────────┐
│ Node.js AI       │  │ Sandbox Manager  │  │ Celery Worker     │
│ Backend (기존)   │  │ (신규 Python)    │  │ (기존 + 신규      │
│ streamText/tools │  │ containerd CLI   │  │  sandbox task)    │
│ -> FastAPI 호출  │  │ nerdctl/kubectl  │  │                   │
└──────────────────┘  └────────┬─────────┘  └───────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────┐
│  Host (베어메탈 Linux)        │                               │
│  containerd + kata-clh       │                               │
│  Cloud Hypervisor VMM        │                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Kata microVM (job_id 마다 1개)                      │   │
│  │  ├─ guest kernel (최소화된 Linux)                    │   │
│  │  ├─ kata-agent (ttRPC over vsock)                    │   │
│  │  ├─ /workspace <- virtio-fs <- /data/jobs/{job_id}   │   │
│  │  ├─ / (read-only rootfs, AppArmor + seccomp 적용)    │   │
│  │  ├─ agent-runtime (Python/Node.js + git, UID 1000)   │   │
│  │  ├─ 문서/오디오/이미지 처리 도구 사전 설치            │   │
│  │  └─ network (virtio-net, NAT/bridge)                 │   │
│  │     └─ browserless 접근: http://192.168.1.50:20047   │   │
│  └──────────────────────────────────────────────────────┘   │
│  /data/jobs/{job_id}/ (결과 파일 + .git repo)               │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  browserless 서버 (a1, 기존 구동 중)                  │   │
│  │  http://192.168.1.50:20047                           │   │
│  │  모든 Kata VM이 공유하여 사용 (Chrome 중복 실행 방지) │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. 하드웨어 검증 결과

| 항목 | 현재 서버 | Kata 요구사항 | 판정 |
|------|-----------|--------------|------|
| CPU | Xeon Gold 6230 x2 (40코어/80스레드) | x86_64 + VT-x + EPT | ✅ 지원 |
| VT-d | Yes | IOMMU (옵션) | ✅ |
| RAM | 512GB | VM당 2GB 기본, virtio-fs용 /dev/shm | ✅ 충분 |
| 디스크 | 1.8TB NVMe (→5TB) | 결과 파일 + 컨테이너 이미지 | ✅ |
| 베어메탈 | Yes | nested virtualization 불필요 | ✅ |
| KVM | `/dev/kvm` 필요 | 커널 KVM 모듈 | ✅ (Linux 호스트) |

**동시 실행 가능 VM 수 추정**: 512GB RAM에서 VM당 2GB 기본 할당 + KSM 페이지 병합(30-50% 절약) 시 약 150개 동시 실행 가능 (호스트 OS/서비스용 50GB, /dev/shm 128GB 예약). browserless 서버 공유로 VM당 ~500MB 절약, virtio-mem으로 idle VM 메모리 회수.

---

## 4. 기술 스택

| 영역 | 기술 | 버전 | 비고 |
|------|------|------|------|
| VMM | Cloud Hypervisor | v51.1 (Kata 3.31번들) | rust-vmm 기반 |
| 컨테이너 런타임 | Kata Containers | 3.31.0 | 최신 안정판 |
| 컨테이너 매니저 | containerd | 2.x | kata-clh RuntimeClass |
| CLI 도구 | nerdctl | 1.7+ | containerd 테스트용 |
| 호스트 OS | Ubuntu 24.04 LTS | | 베어메탈 설치 |
| 파일 공유 | virtio-fs | | Cloud Hypervisor 지원 |
| 게스트 커널 | Kata 커널 (최소화) | Kata 번들 | 부팅 시간 최적화 |
| 게스트 rootfs | 커스텀 ext4 이미지 | | Python/Node.js/git 포함 |
| 오케스트레이션 | Python Sandbox Manager | 신규 | containerd API 호출 |
| (옵션) K8s | Kubernetes + Agent Sandbox CRD | | 향후 확장 시 |

---

## 5. 구현 단계

### Phase 1: 호스트 환경 구성 (1차 마일스톤)

#### 5.1.1 베어메탈 Ubuntu 24.04 설치 및 KVM 확인

- [ ] Ubuntu 24.04 LTS 서버 설치 (또는 기존 호스트 확인)
- [ ] KVM 활성화: `sudo modprobe kvm_intel`, `ls -la /dev/kvm`
- [ ] nested virtualization 불필요 (베어메탈)
- [ ] VT-d/IOMMU는 BIOS에서 활성화 (옵션, VFIO용)

#### 5.1.2 containerd 설치

- [ ] containerd 2.x 설치: `apt install containerd`
- [ ] 기본 설정 생성: `containerd config default | tee /etc/containerd/config.toml`
- [ ] SystemdCgroup = true 설정

#### 5.1.3 Kata Containers 3.31 + Cloud Hypervisor 설치

- [ ] kata-static tarball 다운로드: `kata-static-3.31.0-amd64.tar.zst`
- [ ] `/opt/kata`에 압축 해제
- [ ] Cloud Hypervisor 바이너리 확인: `/opt/kata/bin/cloud-hypervisor`
- [ ] virtiofsd 바이너리 확인: `/opt/kata/libexec/virtiofsd`
- [ ] 게스트 커널 확인: `/opt/kata/share/kata-containers/vmlinux.container`
- [ ] 게스트 이미지 확인: `/opt/kata/share/kata-containers/kata-containers.img`

#### 5.1.4 Kata Cloud Hypervisor 설정

- [ ] `/etc/kata-containers/configuration-clh.toml` 작성
  - `default_vcpus = 1` (기본 1, 필요 시 hot-add로 확장)
  - `default_maxvcpus = 4` (최대 4 vCPU)
  - `default_memory = 2048` (기본 2GB, virtio-mem으로 동적 확장)
  - `default_maxmemory = 8192` (최대 8GB, virtio-mem hotplug 범위)
  - `shared_fs = "virtio-fs"`
  - `virtio_fs_daemon = "/opt/kata/libexec/virtiofsd"`
  - `virtio_fs_cache = "auto"` (cache=auto: 호스트 파일 변경 시 일관성 보장 + 성능 트레이드오프)
  - `virtio_fs_cache_size = 1024` (DAX 1GB 윈도우 — host buffer cache를 guest에 직접 매핑하여 guest page cache 중복 제거, 실제 물리 메모리 추가 사용 ≈ 0)
  - `enable_annotations = []` (보안: annotation 주입 차단, GHSA-rr59-xxvx-96qr 대응)
  - `disable_guest_seccomp = false` (게스트 seccomp 활성화, 호스트 seccomp 프로필을 게스트에 전달)
  - `reclaim_guest_freed_memory = true` (Cloud Hypervisor 전용, 게스트가 해제한 메모리를 호스트로 회수)
  - `enable_mem_prealloc = false` (메모리 사전 할당 비활성화, 밀도 향상)
  - `enable_hugepages = false` (hugepages 비활성화, 유연성 우선)
  - `hotplug_method = "virtio-mem"` (Cloud Hypervisor virtio-mem으로 동적 메모리 추가/회수)
- [ ] `kata-runtime check` 실행으로 하드웨어 호환성 검증

#### 5.1.5 containerd에 kata-clh RuntimeClass 등록

- [ ] containerd-shim-kata-clh-v2 래퍼 스크립트 생성:
  ```bash
  #!/bin/sh
  KATA_CONF_FILE=/opt/kata/share/defaults/kata-containers/configuration-clh.toml
  exec /opt/kata/bin/containerd-shim-kata-v2 "$@"
  ```
- [ ] `/etc/containerd/config.toml`에 runtime 등록:
  ```toml
  [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-clh]
    runtime_type = "io.containerd.kata-clh.v2"
  ```
- [ ] containerd 재시작: `systemctl restart containerd`

#### 5.1.6 /dev/shm 크기 조정, THP 비활성화 및 KSM 활성화

- [ ] virtio-fs DAX 윈도우 백엔드용 /dev/shm을 160GB로 확장 (150 VM × 1GB DAX 윈도우 + 여유):
  ```bash
  mount -o remount,size=160G /dev/shm
  ```
- [ ] `/etc/fstab`에 영구 설정 추가
- [ ] **Transparent Huge Pages (THP) 비활성화** — KSM은 4KB 단위 페이지에서만 작동하므로 THP(2MB)가 켜져 있으면 페이지 병합률이 급격히 저하됨:
  ```bash
  echo never > /sys/kernel/mm/transparent_hugepage/enabled
  echo never > /sys/kernel/mm/transparent_hugepage/defrag
  ```
- [ ] THP 영구 설정: `/sysctl.d/99-thp.conf` 또는 GRUB 커널 파라미터
  ```
  # /etc/systemd/system/disable-thp.service
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
  ```
  ```bash
  systemctl enable disable-thp.service
  ```
- [ ] KSM(Kernel Same-page Merging) 활성화로 동일 게스트 커널/라이브러리 페이지 병합 (THP 비활성화 후 4KB 페이지 단위로 촘촘하게 스캔):
  ```bash
  echo 1 > /sys/kernel/mm/ksm/run
  echo 1000 > /sys/kernel/mm/ksm/pages_to_scan
  ```
- [ ] KSM 영구 설정: `/etc/sysctl.d/99-ksm.conf`
  ```
  kernel.mm.ksm_run = 1
  kernel.mm.ksm_pages_to_scan = 1000
  ```

#### 5.1.7 기본 동작 검증

- [ ] nerdctl 설치
- [ ] 테스트: `nerdctl run --runtime=io.containerd.kata-clh.v2 -it busybox sh`
- [ ] VM 내부에서 `mount` 확인: `kataShared on / type virtiofs`
- [ ] hostPath 마운트 테스트: `--mount type=bind,source=/tmp/test,target=/workspace`

---

### Phase 2: 게스트 이미지 빌드 (에이전트 실행 환경)

#### 5.2.1 커스텀 rootfs 이미지 설계

에이전트가 문서/오디오/이미지/비디오 처리를 즉시 실행할 수 있는 환경. **인스턴스 생성 시 모든 도구가 사전 설치되어 있어야 함** (런타임 설치 불가):

**시스템 기반**:
- [ ] 베이스: Debian 12 slim (Kata 게스트 커널 호환성 최고)
- [ ] 비특권 사용자 `agent` 생성 (UID 1000, sudo 불가)
- [ ] git, curl, wget, jq

**문서 처리 도구**:
- [ ] **LibreOffice** (headless): DOCX/XLSX/PPTX/ODT/RTF/HWP → PDF 변환
  - `libreoffice-writer`, `libreoffice-calc`, `libreoffice-impress`
  - `libreoffice-l10n-ko`, `libreoffice-l10n-ja`, `libreoffice-l10n-zh-cn`
  - `libreoffice-help-ko`
- [ ] **Pandoc**: Markdown/HTML/DOCX/LaTeX/EPUB 상호 변환
- [ ] **Poppler-utils**: PDF → 텍스트/이미지 추출 (`pdftotext`, `pdftoppm`, `pdfinfo`)
- [ ] **Tesseract OCR**: 이미지/PDF OCR
  - `tesseract-ocr` + 언어팩: `kor`, `eng`, `jpn`, `chi-sim`, `chi-tra`
- [ ] **MarkItDown** (Python): PDF/DOCX/PPTX/XLSX → Markdown
- [ ] **pdf2image**, **PyMuPDF** (Python): PDF 페이지 조작

**오디오/비디오 처리 도구**:
- [ ] **FFmpeg**: 오디오/비디오 변환, 추출, 편집
- [ ] **faster-whisper** (Python): 오디오 → 텍스트 변환 (CPU 모델, `small` 사전 다운로드)
- [ ] **pydub** (Python): 오디오 조작
- [ ] **librosa** (Python): 오디오 분석

**이미지 처리 도구**:
- [ ] **ImageMagick**: 이미지 변환/리사이즈/합성 (`magick`)
- [ ] **Ghostscript**: PDF/PS 처리
- [ ] **Pillow** (Python): 이미지 조작
- [ ] **OpenCV** (Python): 이미지 분석/처리
- [ ] **@napi-rs/canvas** (Node.js): 서버사이드 이미지 렌더링

**폰트 (한글/중문/일문 렌더링 필수)**:
- [ ] `fonts-noto-cjk` (한/중/일)
- [ ] `fonts-nanum` (한글)
- [ ] `fonts-unfonts-core` (한글)
- [ ] `fonts-noto-color-emoji` (이모지)
- [ ] `fonts-liberation` (영문)

**개발 환경**:
- [ ] Python 3.11 + pip + venv
- [ ] Node.js 20 + npm
- [ ] gcc, make, build-essential (네이티브 모듈 컴파일용)
- [ ] unzip, unrar-free, p7zip (압축 해제)

**로케일**:
- [ ] `ko_KR.UTF-8`, `ja_JP.UTF-8`, `zh_CN.UTF-8` locale 생성

**제외 항목 (리소스 절약)**:
- ❌ Chrome/Chromium (browserless 서버로 대체)
- ❌ Puppeteer/Playwright 브라우저 바이너리
- ❌ GPU/CUDA 라이브러리
- ❌ X11/Wayland 디스플레이 서버
- ❌ LaTeX (필요 시 별도 이미지 레이어)

#### 5.2.2 이미지 빌드 스크립트

- [ ] `infra/kata-guest/build-rootfs.sh` 작성
  - debootstrap 기반 ext4 이미지 생성 (Docker 기반 빌드 후 export)
  - 크기: 3GB (도구 + 여유 공간)
  - 출력: `/opt/kata/share/kata-containers/proof-agent.img`
  - Whisper `small` 모델 사전 다운로드 (런타임 다운로드 방지)
  - Tesseract traineddata 사전 다운로드
- [ ] 빌드 후 Kata 설정에 `image = "/opt/kata/share/kata-containers/proof-agent.img"` 등록
- [ ] 이미지 버전 태깅 (예: `proof-agent-v1.img`)

#### 5.2.3 에이전트 런타임 스크립트

- [ ] `/opt/agent-runner/entrypoint.sh` (rootfs 내부)
  - `/workspace` 디렉토리 확인
  - 필요 시 `git init /workspace` + `.gitignore` 설정
  - vsock 기반으로 호스트에서 명령 수신 대기
  - 환경 변수 주입: `BROWSERLESS_URL=http://192.168.1.50:20047`
  - 종료 시 결과 파일 동기화

#### 5.2.4 browserless 연동 스크립트

- [ ] `/opt/agent-runner/browserless-helper.py` (rootfs 내부)
  - a1의 browserless 서버(`http://192.168.1.50:20047`)에 CDP WebSocket 연결
  - Puppeteer/Playwright 원격 브라우저 제어
  - 웹페이지 스크린샷, PDF 저장, 데이터 추출
  - VM 내부에 Chrome 설치 불필요 (RAM ~500MB 절약/VM)
- [ ] Python 예시:
  ```python
  # browserless 서버에 원격 연결 (로컬 Chrome 실행 없음)
  from pyppeteer import connect
  browser = await connect(browserWSEndpoint="ws://192.168.1.50:20047?token=...")
  page = await browser.newPage()
  await page.goto("https://example.com")
  await page.screenshot({"path": "/workspace/screenshot.png"})
  ```
- [ ] Node.js 예시:
  ```javascript
  const puppeteer = require("puppeteer-core");
  const browser = await puppeteer.connect({
    browserWSEndpoint: "ws://192.168.1.50:20047?token=..."
  });
  ```

---

### Phase 3: Sandbox Manager 구현 (신규 Python 모듈)

#### 5.3.1 모듈 구조

```
app/backend/core/sandbox/
├── __init__.py
├── manager.py       # Kata VM 생명주기 관리
├── workspace.py     # /data/jobs/{job_id} workspace 준비
├── communicator.py  # vsock/HTTP 기반 VM 내부 통신
└── collector.py     # 실행 결과/로그 수집
```

#### 5.3.2 SandboxManager 핵심 기능

- [ ] `create_sandbox(job_id, user_id, resource_limits) -> sandbox_id`
  - `/data/jobs/{job_id}` 디렉토리 준비
  - 결과 파일 다운로드 (Supabase Storage에서)
  - `git init` (리포지토리 초기화)
  - containerd API로 Kata VM 시작
  - `/data/jobs/{job_id}`를 virtio-fs로 `/workspace`에 마운트
  - 리소스 제한: CPU, memory, disk, 네트워크
- [ ] `execute_command(sandbox_id, command) -> result`
  - VM 내부에서 셸 명령 실행
  - vsock 기반 통신 또는 SSH
- [ ] `get_status(sandbox_id) -> status`
  - VM 실행 상태, 리소스 사용량
- [ ] `destroy_sandbox(sandbox_id)`
  - VM 종료
  - 결과 파일 Supabase Storage 업로드
  - workspace 정리 (옵션: 보존 기간 설정)

#### 5.3.3 workspace 준비 로직

- [ ] 결과 페이지의 파일들을 `/data/jobs/{job_id}/`에 다운로드
  - 원본 파일 (PDF, 이미지, 오디오, 비디오)
  - 추출 결과 (마크다운, JSON, Excel)
  - 주석 JSON
- [ ] 디렉토리 구조:
  ```
  /data/jobs/{job_id}/
  ├── .git/                    # Git 리포지토리
  ├── original/                # 원본 파일
  │   ├── document.pdf
  │   ├── image1.png
  │   └── audio.mp3
  ├── extracted/               # 추출 결과
  │   ├── output.md
  │   ├── output.json
  │   └── tables.xlsx
  ├── annotations/             # 주석 JSON
  │   └── annotations.json
  └── agent_output/            # 에이전트가 생성한 파일
  ```

#### 5.3.4 통신 방식

- [ ] **vsock 기반** (권장): Kata VM과 호스트 간 AF_VSOCK 통신
  - 호스트에서 vsock 포트로 명령 전송
  - VM 내부 agent-runner가 명령 수신 후 실행
- [ ] **HTTP 기반** (폴백): VM 내부에서 호스트 API로 결과 전송
  - VM 네트워크가 호스트에 접근 가능한 경우

---

### Phase 4: FastAPI 엔드포인트 추가

#### 5.4.1 신규 라우터: `/api/sandboxes`

- [ ] `app/backend/api/sandbox.py` 작성
- [ ] `main.py`에 라우터 등록

엔드포인트:

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/sandboxes` | 새 sandbox 생성 (job_id 기반) |
| GET | `/api/sandboxes/{id}` | sandbox 상태 조회 |
| POST | `/api/sandboxes/{id}/execute` | sandbox 내부에서 명령 실행 |
| POST | `/api/sandboxes/{id}/commit` | workspace 변경사항을 Git commit |
| GET | `/api/sandboxes/{id}/files` | workspace 파일 목록 |
| GET | `/api/sandboxes/{id}/files/{path}` | workspace 파일 다운로드 |
| DELETE | `/api/sandboxes/{id}` | sandbox 종료 및 정리 |

#### 5.4.2 인증 및 권한

- [ ] 기존 `get_current_user_or_api_key` 재사용
- [ ] sandbox 소유자 검증 (user_id 매칭)
- [ ] 리소스 사용량에 따른 포인트 차감 (기존 points_service 활용)

#### 5.4.3 DB 마이그레이션

- [ ] `app/backend/db/migrations/026_add_sandboxes.sql`:
  ```sql
  CREATE TABLE IF NOT EXISTS sandboxes (
      id VARCHAR(32) PRIMARY KEY,
      job_id VARCHAR(32) REFERENCES jobs(id) ON DELETE SET NULL,
      user_id UUID REFERENCES users(id) ON DELETE SET NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'creating',
      vm_id VARCHAR(64),
      workspace_path TEXT NOT NULL,
      resource_limits JSONB NOT NULL DEFAULT '{}',
      result JSONB NOT NULL DEFAULT '{}',
      error TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
      expires_at TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS ix_sandboxes_job_id ON sandboxes(job_id);
  CREATE INDEX IF NOT EXISTS ix_sandboxes_user_id ON sandboxes(user_id);
  ```

---

### Phase 5: AI 에이전트 도구 확장

#### 5.5.1 Node.js AI 백엔드에 sandbox 도구 추가

- [ ] `app/ai-backend/src/tools/sandbox.ts` 신규 작성
- [ ] `app/ai-backend/src/chat/route.ts`에 sandbox 도구 등록

새 도구:

| 도구 | 설명 |
|------|------|
| `create_workspace` | 현재 job의 결과 파일로 sandbox workspace 생성 |
| `list_files` | workspace 내 파일 목록 조회 |
| `read_file` | workspace 내 파일 읽기 |
| `write_file` | workspace에 파일 쓰기 |
| `execute_command` | sandbox 내부에서 셸 명령 실행 (블랙리스트 필터링 적용) |
| `download_file` | URL에서 파일을 workspace로 다운로드 |
| `git_commit` | workspace 변경사항을 Git commit |
| `git_diff` | Git diff 조회 |
| `browse_web` | a1의 browserless 서버로 웹페이지 스크린샷/PDF/데이터 추출 |
| `convert_document` | LibreOffice/Pandoc로 문서 변환 (sandbox 내부) |
| `transcribe_audio` | Whisper로 오디오 → 텍스트 변환 (sandbox 내부) |
| `process_image` | ImageMagick/Pillow로 이미지 처리 (sandbox 내부) |
| `get_workspace_status` | sandbox 상태 및 리소스 사용량 |

#### 5.5.2 system prompt 확장

- [ ] `buildSystemPrompt()`에 sandbox 도구 사용 규칙 추가
- [ ] "결과 파일을 직접 처리해야 할 때 sandbox 도구를 사용" 가이드

#### 5.5.3 proof-api.ts 확장

- [ ] sandbox API 호출 메서드 추가
- [ ] `createSandbox()`, `executeInSandbox()`, `listFiles()` 등

---

### Phase 6: 네트워크 및 보안 정책

#### 5.6.1 시스템 파괴 작업 차단 (다층 방어)

에이전트가 호스트/게스트 시스템을 파괴하는 것을 5계층으로 차단한다:

**Layer 1: Read-only rootfs**
- [ ] 게스트 rootfs를 read-only로 마운트 (`/` 읽기 전용)
- [ ] 쓰기 가능 영역: `/workspace`, `/tmp`, `/home/agent` 만 (tmpfs 또는 virtio-blk overlay)
- [ ] 시스템 바이너리(`/bin`, `/usr`, `/sbin`) 변경 불가

**Layer 2: Capabilities drop (Linux capabilities)**
- [ ] 컨테이너 실행 시 모든 위험 capabilities 제거:
  ```
  --cap-drop ALL
  --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FSETID --cap-add FOWNER
  --cap-add SETGID --cap-add SETUID --cap-add NET_BIND_SERVICE
  ```
- [ ] 제거되는 위험 capabilities:
  - `CAP_SYS_ADMIN` (mount, pivot_root, remount)
  - `CAP_SYS_RAWIO` (커널 메모리 접근, `/dev/mem`, `/dev/kmem`)
  - `CAP_SYS_MODULE` (커널 모듈 로드)
  - `CAP_SYS_PTRACE` (프로세스 추적)
  - `CAP_SYS_BOOT` (재부팅)
  - `CAP_MAC_ADMIN` (MAC 설정 변경)
  - `CAP_LINUX_IMMUTABLE` (파일 immutability)
  - `CAP_BLOCK_SUSPEND` (시스템 서스펜드 차단)
  - `CAP_WAKE_ALARM`
  - `CAP_MKNOD` (디바이스 노드 생성)
  - `CAP_AUDIT_WRITE`, `CAP_AUDIT_CONTROL`

**Layer 3: Seccomp 프로필 (시스콜 차단)**
- [ ] `disable_guest_seccomp = false` 설정 (Kata 게스트에 seccomp 전달)
- [ ] 커스텀 seccomp JSON 프로필 작성: `infra/kata-host/seccomp-proof-agent.json`
- [ ] 차단할 시스콜 (시스템 파괴 관련):
  - `mount`, `umount2` (파일시스템 마운트)
  - `init_module`, `finit_module`, `delete_module` (커널 모듈)
  - `pivot_root`, `chroot` (루트 변경)
  - `reboot`, `kexec_load`, `kexec_file_load` (재부팅)
  - `swapon`, `swapoff` (스왑 조작)
  - `mkfs*` 계열 (블록 디바이스 포맷 — 바이너리 자체도 실행 권한 제거)
  - `iopl`, `ioperm` (I/O 포트 접근)
  - `kcmp` (프로세스 메모리 비교)
  - `perf_event_open` (성능 카운터 악용 방지)
  - `bpf` (eBPF 프로그램 로드)
  - `personality` (프로세스 실행 도메인 변경)
  - `vmsplice` (메모리 스플라이스)
  - `clone` with `CLONE_NEWUSER` (사용자 네임스페이스 생성 제한)
- [ ] 허용할 시스콜: 표준 파일/네트워크/프로세스 조작 (read, write, open, close, socket, connect, execve, fork, etc.)

**Layer 4: AppArmor 프로필**
- [ ] `/etc/apparmor.d/proof-agent` 작성:
  ```
  #include <tunables/global>
  profile proof-agent flags=(attach_disconnected) {
    #include <abstractions/base>
    #include <abstractions/python>
    #include <abstractions/nodejs>

    # /workspace read-write
    /workspace/** rw,
    /workspace/ rw,

    # /tmp, /home/agent read-write
    /tmp/** rw,
    /home/agent/** rw,

    # 시스템 바이너리 실행 허용 (read-only)
    /usr/bin/** rix,
    /usr/local/bin/** rix,
    /bin/** rix,
    /usr/lib/** r,

    # 위험 경로 접근 차단
    deny /dev/sda* rw,
    deny /dev/nvme* rw,
    deny /dev/mem rw,
    deny /dev/kmem rw,
    deny /proc/kcore r,
    deny /proc/sys/kernel/** w,
    deny /proc/sysrq-trigger w,
    deny /sys/firmware/** w,
    deny /sys/kernel/** w,

    # 네트워크 허용 (browserless, 아웃바운드)
    network inet stream,
    network inet6 stream,
  }
  ```
- [ ] AppArmor 적용 확인: `aa-status | grep proof-agent`

**Layer 5: Agent Policy (Kata OPA, 심화)**
- [ ] Kata 게스트 rootfs 빌드 시 `AGENT_POLICY=yes` 옵션 사용
- [ ] `/etc/kata-opa/default-policy.rego` 커스텀 정책 작성:
  - kata-agent ttRPC API 호출 검증
  - `CreateContainer` 요청 시 컨테이너 이미지/명령 화이트리스트 검사
  - `ExecProcess` 요청 시 명령어 블랙리스트 검사 (옵션)
- [ ] Agent Policy는 호스트가 신뢰할 수 없는 환경에서 추가 보안 계층 제공

**명령어 블랙리스트 (Sandbox Manager 레벨)**
- [ ] Sandbox Manager의 `execute_command()`에서 명령어 사전 필터링:
  ```python
  BLOCKED_PATTERNS = [
      r"\brm\s+-rf\s+/(?!workspace)",  # /workspace 외 rm -rf /
      r"\bdd\s+.*of=/dev/",            # dd to block device
      r"\bmkfs\b",                      # filesystem format
      r"\bmount\s+",                    # mount (AppArmor/seccomp도 차단)
      r"\bumount\b",
      r"\bsysctl\s+",                   # kernel parameter
      r"\binsmod\b", r"\brmmod\b",      # kernel module
      r"\breboot\b", r"\bshutdown\b", r"\bhalt\b",
      r"\b:(){.*};:",                   # fork bomb
      r"\bcurl\s+.*\|\s*sh",            # pipe to shell
      r"\bwget\s+.*\|\s*sh",
  ]
  ```
- [ ] 명령 실행 전 패턴 매칭으로 차단 + 로그 기록

#### 5.6.2 네트워크 격리

- [ ] Kata VM 네트워크를 NAT 모드로 설정
- [ ] 아웃바운드 인터넷 허용 (파일 다운로드용)
- [ ] 호스트 내부 서비스 접근 제한:
  - FastAPI (28181): 허용 (결과 업로드용)
  - browserless (20047): 허용 (웹 브라우징)
  - Redis/Postgres/Supabase: 차단
- [ ] iptables/nftables 규칙으로 도메인 화이트리스트 적용 (옵션)
- [ ] browserless 토큰 인증 (API key 필요)

#### 5.6.3 파일시스템 보안

- [ ] `/workspace`만 read-write, 나머지 read-only (rootfs 자체가 read-only)
- [ ] 호스트 파일시스템 접근 차단 (virtio-fs shared dir를 `/workspace`로만 제한)
- [ ] `enable_annotations = []`로 annotation 주입 차단 (GHSA-rr59-xxvx-96qr)
- [ ] `privileged_without_host_devices = true` 설정
- [ ] `/proc`, `/sys` 일부 접근 차단 (AppArmor로 처리)

#### 5.6.4 리소스 제한 (동적 할당)

- [ ] CPU: VM당 1 vCPU (기본), hot-add로 최대 4 vCPU
- [ ] Memory: VM당 2GB (기본), virtio-mem으로 최대 8GB 동적 확장
- [ ] Disk: workspace 10GB 제한 (quota)
- [ ] 실행 시간: 30분 타임아웃 (설정 가능)
- [ ] 동시 sandbox 수: 사용자당 3개, 전체 150개 (2GB 기본 메모리 기준)
- [ ] idle VM 메모리 회수: `reclaim_guest_freed_memory = true`

#### 5.6.5 보안 체크리스트

- [ ] Kata 최신 패치 유지 (virtio-fs 탈출 취약점 대응)
- [ ] 에이전트 컨테이너 비특권 실행 (UID 1000, sudo 불가)
- [ ] seccomp 프로필 적용 (시스템 파괴 시스콜 차단)
- [ ] AppArmor 프로필 적용 (위험 경로 접근 차단)
- [ ] capabilities 전면 drop (필수 최소만 허용)
- [ ] read-only rootfs (시스템 바이너리 변경 차단)
- [ ] Agent Policy (genpolicy) 적용 (심화 보안, 옵션)
- [ ] 정기적 보안 권고 모니터링 (GHSA)
- [ ] browserless 토큰 인증 (무단 브라우저 사용 차단)

---

### Phase 7: 프론트엔드 통합

#### 5.7.1 결과 페이지에 sandbox 진입점 추가

- [ ] `JobResultPage.jsx`에 "에이전트로 실행" 버튼 추가
- [ ] sandbox 상태 표시 (생성 중/실행 중/종료)
- [ ] workspace 파일 브라우저 (간단한 트리 뷰)

#### 5.7.2 AgentChatModal에 sandbox 컨텍스트 전달

- [ ] 채팅 요청 시 `sandboxId`를 context에 포함
- [ ] 에이전트가 sandbox 도구를 사용할 수 있도록 context 전달

#### 5.7.3 i18n 키 추가

- [ ] ko/en/ja `page.json`에 sandbox 관련 키 추가

---

### Phase 8: 모니터링 및 운영

#### 5.8.1 로깅

- [ ] Kata VM 로그: `journalctl -t kata-runtime`
- [ ] containerd 로그: `journalctl -u containerd`
- [ ] sandbox 실행 로그: DB + 파일
- [ ] 에이전트 명령 로그: workspace 내 `.agent_log/`

#### 5.8.2 메트릭

- [ ] VM 수, CPU/Memory 사용량, 실행 시간
- [ ] `/api/sandboxes/stats` 엔드포인트 (관리자용)

#### 5.8.3 자동 정리

- [ ] 만료된 sandbox 자동 종료 (Celery beat)
- [ ] workspace 보존 기간: 7일 (기본)
- [ ] 디스크 사용량 임계치 알림

---

## 6. 파일 변경 계획

### 6.1 신규 파일

| 파일 | 설명 |
|------|------|
| `infra/kata-guest/build-rootfs.sh` | 게스트 rootfs 이미지 빌드 스크립트 |
| `infra/kata-guest/entrypoint.sh` | VM 내부 에이전트 런타임 진입점 |
| `infra/kata-guest/Dockerfile.rootfs` | rootfs 빌드용 Dockerfile |
| `infra/kata-guest/browserless-helper.py` | browserless 원격 연결 헬퍼 (Python) |
| `infra/kata-guest/browserless-helper.js` | browserless 원격 연결 헬퍼 (Node.js) |
| `infra/kata-host/install-kata.sh` | 호스트 Kata 설치 스크립트 |
| `infra/kata-host/configuration-clh.toml` | Kata Cloud Hypervisor 설정 |
| `infra/kata-host/containerd-config.toml` | containerd kata-clh 등록 설정 |
| `infra/kata-host/seccomp-proof-agent.json` | 커스텀 seccomp 프로필 (시스템 파괴 시스콜 차단) |
| `infra/kata-host/apparmor-proof-agent` | AppArmor 프로필 (위험 경로 접근 차단) |
| `infra/kata-host/kata-opa-policy.rego` | Kata Agent Policy (OPA, 심화 보안) |
| `app/backend/core/sandbox/__init__.py` | sandbox 모듈 |
| `app/backend/core/sandbox/manager.py` | Kata VM 생명주기 관리 |
| `app/backend/core/sandbox/workspace.py` | workspace 준비 로직 |
| `app/backend/core/sandbox/communicator.py` | VM 통신 |
| `app/backend/core/sandbox/collector.py` | 결과 수집 |
| `app/backend/core/sandbox/security.py` | 명령어 블랙리스트 필터링 |
| `app/backend/api/sandbox.py` | sandbox REST API 라우터 |
| `app/backend/db/migrations/026_add_sandboxes.sql` | sandboxes 테이블 마이그레이션 |
| `app/ai-backend/src/tools/sandbox.ts` | sandbox 도구 (Node.js) |
| `app/ai-backend/src/tools/browserless.ts` | browserless 원격 브라우저 도구 (Node.js) |
| `app/frontend/src/components/SandboxBrowser.jsx` | workspace 파일 브라우저 UI |

### 6.2 수정 파일

| 파일 | 변경 내용 |
|------|----------|
| `app/backend/main.py` | sandbox 라우터 등록 |
| `app/backend/config.py` | sandbox 관련 설정 추가 (KATA_BIN, WORKSPACE_DIR 등) |
| `app/backend/db/models.py` | Sandbox 모델 추가 |
| `app/backend/workers/tasks.py` | sandbox 생성/정리 Celery task 추가 |
| `app/ai-backend/src/chat/route.ts` | sandbox 도구 등록 |
| `app/ai-backend/src/lib/proof-api.ts` | sandbox API 호출 메서드 추가 |
| `app/frontend/src/pages/JobResultPage.jsx` | "에이전트로 실행" 버튼 추가 |
| `app/frontend/src/components/AgentChatModal.jsx` | sandboxId context 전달 |
| `app/frontend/src/i18n/locales/*/page.json` | sandbox i18n 키 추가 |
| `app/docker-compose.yml` | sandbox manager 서비스 추가 (옵션) |
| `app/.env.example` | sandbox 관련 환경변수 추가 |

---

## 7. 검증 계획

### 7.1 Phase 1 검증 (호스트 환경)

- [ ] `kata-runtime check` 통과
- [ ] `nerdctl run --runtime=io.containerd.kata-clh.v2 busybox` 성공
- [ ] VM 내부에서 `mount` 확인: virtio-fs 마운트
- [ ] hostPath bind mount 테스트: 호스트 파일이 VM에 보이는지
- [ ] DAX 활성화 확인: VM 내부에서 `mount | grep virtiofs` 시 `dax` 옵션 확인
- [ ] DAX 성능 확인: 동일 파일 반복 읽기 시 guest page cache 증가 없이 빠른 응답

### 7.2 Phase 2 검증 (게스트 이미지)

- [ ] 커스텀 rootfs로 VM 부팅 성공
- [ ] VM 내부에서 Python/Node.js/git 실행 확인
- [ ] 비특권 사용자로 실행 확인 (UID 1000, sudo 불가)
- [ ] 문서 처리 도구 확인:
  - `libreoffice --headless --convert-to pdf` 실행
  - `pandoc --version` 확인
  - `pdftotext test.pdf -` 실행
  - `tesseract --list-langs`에 kor/eng/jpn/chi-sim 포함
- [ ] 오디오/비디오 처리 도구 확인:
  - `ffmpeg -version` 확인
  - `faster-whisper` Python import 확인
- [ ] 이미지 처리 도구 확인:
  - `magick --version` 확인
  - `python3 -c "from PIL import Image"` 확인
  - `python3 -c "import cv2"` 확인
- [ ] 폰트 렌더링: 한글/중문/일문 PDF 변환 결과 확인
- [ ] browserless 연결: VM 내부에서 `http://192.168.1.50:20047` 접근 확인

### 7.3 Phase 3-4 검증 (Sandbox Manager + API)

- [ ] POST `/api/sandboxes`로 sandbox 생성
- [ ] 결과 파일이 `/workspace`에 마운트되는지 확인
- [ ] POST `/api/sandboxes/{id}/execute`로 명령 실행
- [ ] Git commit/diff 동작 확인
- [ ] DELETE `/api/sandboxes/{id}`로 정리
- [ ] 명령어 블랙리스트: `rm -rf /` 등 차단 확인

### 7.4 Phase 5 검증 (AI 에이전트 통합)

- [ ] 채팅에서 "이 PDF에서 표를 추출해서 Excel로 만들어" → sandbox 도구 호출
- [ ] 에이전트가 workspace에서 파일 읽기/쓰기/실행
- [ ] "이 웹사이트 스크린샷 찍어" → browse_web 도구 → browserless 서버 연동
- [ ] "이 오디오 텍스트로 변환해" → transcribe_audio 도구 → Whisper 실행
- [ ] 결과 파일이 Supabase Storage에 업로드되는지

### 7.5 Phase 6 검증 (보안 - 시스템 파괴 차단)

- [ ] **read-only rootfs**: `touch /bin/test` → Permission denied
- [ ] **capabilities drop**: `mount -t tmpfs none /tmp` → EPERM
- [ ] **seccomp**: `mount`, `init_module`, `reboot` 시스콜 → EPERM
- [ ] **AppArmor**: `dd if=/dev/zero of=/dev/sda` → Permission denied
- [ ] **AppArmor**: `cat /proc/kcore` → Permission denied
- [ ] **명령어 블랙리스트**: `rm -rf /`, `mkfs.ext4 /dev/sda`, `:(){ :|:& };:` → 차단
- [ ] **비특권 사용자**: `sudo` 실행 불가, root 전환 불가
- [ ] **네트워크 격리**: Redis/Postgres 접근 차단, browserless/FastAPI 접근 허용
- [ ] **리소스 제한**: CPU/memory/disk 초과 시 동작
- [ ] **browserless 토큰**: 잘못된 토큰으로 접근 시 거부

---

## 8. 리스크 및 대응

### 8.1 virtio-fs 캐싱 이슈

**리스크**: 호스트 파일 변경이 VM에 즉시 반영되지 않을 수 있음 (이슈 #13137)

**대응**:
- bind mount는 컨테이너 시작 전 설정
- 파일 변경이 필요한 경우 VM 내부에서만 수행
- 호스트→VM 방향 동기화는 sandbox 생성 시에만 수행

### 8.2 virtio-fs 보안 취약점

**리스크**: GHSA-2gv2-cffp-j227 (게스트 root → 호스트 root 탈출)

**대응**:
- Kata 최신 패치 유지
- 에이전트 비특권 실행 (root 차단)
- `enable_annotations = []`로 공격 벡터 차단
- 정기 보안 권고 모니터링

### 8.3 /dev/shm 부족

**리스크**: virtio-fs가 /dev/shm을 메모리 백엔드로 사용, 다수 VM 시 부족

**대응**:
- /dev/shm을 160GB로 설정 (150 VM × 1GB DAX 윈도우 + 여유)
- DAX 윈도우는 가상 메모리 매핑 영역이며 실제 물리 메모리는 host buffer cache에서 사용 (추가 물리 메모리 ≈ 0)
- 동시 VM 수 제한 (150개, 2GB 기본 메모리 기준)
- 고밀도 모드에서는 DAX 윈도우를 256MB로 축소 (300 VM × 256MB = 75GB)
- 모니터링 및 알림

### 8.4 게스트 이미지 관리

**리스크**: 커스텀 rootfs 업데이트/배포 복잡, 문서/미디어 도구가 많아 이미지 크기 증가

**대응**:
- 빌드 스크립트 자동화
- 버전 태깅
- 롤백 가능하도록 이전 이미지 보존
- 이미지 크기 최적화: 불필요한 패키지 제거, apt 캐시 정리
- Whisper 모델, Tesseract traineddata는 이미지에 포함 (런타임 다운로드 방지)

### 8.5 단일 서버 의존성

**리스크**: 호스트 장애 시 모든 sandbox 손실

**대응**:
- workspace를 Supabase Storage에 주기적 백업
- 향후 다중 노드 확장 시 Kubernetes + Agent Sandbox CRD 도입

### 8.6 browserless 서버 단일 장애점

**리스크**: a1의 browserless 서버가 다운되면 모든 VM의 웹 브라우징 기능 중단

**대응**:
- browserless 서버 헬스체크 모니터링
- browserless 장애 시 에이전트에 명확한 에러 메시지 전달
- 향후 browserless 클러스터 구성 (옵션)

### 8.7 시스템 파괴 명령 우회 시도

**리스크**: 에이전트가 seccomp/AppArmor 우회를 시도할 수 있음 (예: 인코딩된 명령, alias, symlink)

**대응**:
- 다층 방어 (read-only rootfs + seccomp + AppArmor + capabilities drop)
- Sandbox Manager 레벨 명령어 블랙리스트 (정규식 패턴 매칭)
- 실행 로그 모니터링 및 이상 탐지
- 비특권 사용자(UID 1000)로 실행, sudo 불가

---

## 9. 리소스 절약 최적화 전략

### 9.1 메모리 절약

| 전략 | 절약 효과 | 설명 |
|------|----------|------|
| browserless 서버 공유 | ~500MB/VM | 각 VM에 Chrome/Puppeteer 미설치, a1의 browserless 공유 |
| virtio-mem 동적 메모리 | ~2-6GB/VM | 기본 2GB, 필요 시에만 확장, idle 시 회수 |
| reclaim_guest_freed_memory | 가변 | 게스트가 해제한 메모리를 호스트로 회수 |
| KSM 페이지 병합 | ~30-50% | 동일 게스트 커널/라이브러리 페이지 병합 |
| virtio-fs DAX (cache_size=1024) | guest page cache 중복 제거 | host buffer cache를 guest에 직접 매핑, 300 VM이 동일 rootfs 파일을 공유 → 물리 메모리 추가 사용 ≈ 0 |
| enable_mem_prealloc = false | 밀도 향상 | 메모리 사전 할당 비활성화 |
| default_memory = 2048 (기본) | 2GB/VM | 4GB → 2GB로 기본 할당 축소 |

**메모리 사용량 추정 (512GB 호스트)**:
- 호스트 OS + PROOF 서비스: ~50GB
- /dev/shm (DAX 윈도우 백엔드): 160GB (150 VM × 1GB DAX, 가상 매핑 영역 — 실제 물리 메모리는 host buffer cache 사용)
- VM 150개 × 2GB = 300GB (KSM 적용 시 ~150-200GB)
- DAX로 guest page cache 중복 제거: ~50-100GB 절약 (동일 rootfs 파일 공유)
- 여유: ~84-134GB

### 9.2 CPU 절약

| 전략 | 효과 | 설명 |
|------|------|------|
| default_vcpus = 1 | 50% 절약 | 기본 1 vCPU, 필요 시 hot-add |
| CPU pinning (옵션) | 캐시 지역성 | vCPU를 물리 코어에 고정 |
| idle VM 일시정지 (옵션) | CPU 회수 | 장시간 idle 시 VM pause/resume |

### 9.3 디스크 절약

| 전략 | 효과 | 설명 |
|------|------|------|
| read-only rootfs 공유 | ~3GB/VM | 모든 VM이 동일 rootfs 이미지 공유 (COW) |
| workspace quota | 10GB 제한 | 사용자당 디스크 사용량 제한 |
| 자동 정리 | 가변 | 만료된 sandbox workspace 자동 삭제 (7일) |
| 게스트 이미지 압축 | ~60% | ext4 이미지를 zstd 압축 저장 |

### 9.4 부팅 시간 절약

| 전략 | 효과 | 설명 |
|------|------|------|
| Cloud Hypervisor | ~125ms | QEMU보다 빠른 부팅 |
| 최소화된 게스트 커널 | ~50ms 절약 | 불필요한 드라이버 제거 |
| Snapshot restore (향후) | ~100ms 절약 | VM snapshot에서 restore |
| 사전 설치된 도구 | 런타임 설치 제거 | apt/pip install 시간 절약 |

### 9.5 네트워크 절약

| 전략 | 효과 | 설명 |
|------|------|------|
| browserless 공유 | 대역폭 절약 | 중복 웹 브라우징 트래픽 방지 |
| 파일 캐싱 | 대역폭 절약 | 동일 파일 다운로드 시 캐시 재사용 |

---

## 10. 향후 확장 로드맵

### 10.1 Kubernetes + Agent Sandbox CRD

Google이 KubeCon NA 2025에서 발표한 [Kubernetes Agent Sandbox](https://github.com/kubernetes-sigs/agent-sandbox)는 Kata Containers를 기본 런타임으로 지원한다. 단일 서버에서 안정화 후 다중 노드 확장 시:

- [ ] K3s/K8s 클러스터 구성
- [ ] kata-clh RuntimeClass 배포 (kata-deploy)
- [ ] Agent Sandbox Operator 설치
- [ ] Sandbox CRD로 선언적 관리
- [ ] 기존 Sandbox Manager를 CRD 컨트롤러로 마이그레이션

### 10.2 GPU 패스스루

Cloud Hypervisor는 VFIO를 통한 GPU 패스스루를 지원한다. 향후 에이전트가 GPU 연산(이미지 처리, ML 추론)이 필요한 경우:

- [ ] VFIO 활성화
- [ ] GPU를 VM에 패스스루
- [ ] CUDA/TensorRT 접근

### 10.3 Snapshot 기반 빠른 시작

Kata + Cloud Hypervisor는 VM snapshot을 지원한다. 빈번한 sandbox 생성 시:

- [ ] 기본 에이전트 이미지의 snapshot 생성
- [ ] snapshot에서 restore로 부팅 시간 단축 (150ms → 수십 ms)

### 10.4 동시 VM 300+ 확장 (고밀도 모드)

기본 설정(VM당 2GB)으로는 512GB 호스트에서 약 150개 VM이 한계다. 300개 이상을 동시 실행하려면 VM당 메모리를 ~1GB 이하로 낮추고 메모리 회수 기법을 적극 활용해야 한다.

#### 메모리 병목 분석

Kata VM당 호스트 메모리 사용량 (실측 기준):

| 구성 요소 | idle VM | busy VM | 비고 |
|-----------|---------|---------|------|
| VMM 프로세스 (QEMU/CLH) | ~2.2GB | ~3.8GB | default_memory=2048 기준 |
| virtiofsd 프로세스 | ~2MB | ~1.8GB | virtio-fs 캐시 사용 시 |
| containerd-shim | ~30MB | ~30MB | 고정 |
| **합계** | **~2.25GB** | **~5.6GB** | |

**병목**: `default_memory = 2048`이 VM당 2GB를 고정 할당. 300개 × 2GB = 600GB > 512GB.

#### 300+ VM 달성 전략 (5가지)

**전략 1: Dragonball runtime-rs + inline-virtio-fs (가장 효과적)**

Dragonball은 Kata의 Rust 런타임에 내장된 VMM으로, 외부 virtiofsd 프로세스가 필요 없다:

- `shared_fs = "inline-virtio-fs"` — virtiofsd가 shim 프로세스 내부에서 실행
- 외부 virtiofsd 프로세스 제거 → VM당 ~2MB-1.8GB 절약
- /dev/shm 백엔드 불필요 (인라인 처리)
- Zero IPC overhead (shim-VMM 간 통신 없음)
- 단점: CPU hotplug 미지원, 메모리 hotplug 미지원 (고정 할당)

```toml
# configuration-dragonball.toml
[hypervisor.dragonball]
default_vcpus = 1
default_maxvcpus = 2
default_memory = 1024          # 1GB 기본
shared_fs = "inline-virtio-fs"
virtio_fs_cache = "none"       # 캐시 비활성화로 메모리 절약
```

**전략 2: default_memory 축소 + virtio-mem 동적 확장**

- `default_memory = 512` (512MB 기본, 에이전트 대기 상태)
- `default_maxmemory = 4096` (최대 4GB)
- `hotplug_method = "virtio-mem"` (Cloud Hypervisor)
- `reclaim_guest_freed_memory = true`
- 에이전트가 실제 작업 시에만 virtio-mem으로 메모리 확장
- idle VM은 512MB만 점유

```toml
# configuration-clh.toml (고밀도 모드)
default_memory = 512
default_maxmemory = 4096
hotplug_method = "virtio-mem"
reclaim_guest_freed_memory = true
enable_mem_prealloc = false
```

**전략 3: EROFS snapshotter + shared_fs = "none" (rootfs 블록 전달)**

EROFS snapshotter는 컨테이너 이미지를 블록 디바이스로 게스트에 직접 전달:

- `shared_fs = "none"` — virtio-fs/virtiofsd 완전 제거
- rootfs를 virtio-blk 블록 디바이스로 전달 (메모리 백엔드 불필요)
- /dev/shm 사용량 제로
- containerd 2.1+ 필요 (EROFS snapshotter)
- 단점: /workspace 공유를 위해 별도 virtio-blk 디바이스 필요

```toml
# configuration-clh.toml (EROFS 모드)
shared_fs = "none"
# rootfs는 EROFS 블록 디바이스로 전달
# /workspace는 virtio-blk로 별도 전달
```

**전략 4: KSM 극대화 + zRAM 압축 스왑**

동일 게스트 커널/라이브러리 페이지를 병합하고, cold page를 압축:

- KSM 극대화 (THP 비활성화 후 4KB 페이지 단위로 촘촘하게 병합):
  ```bash
  # THP 비활성화 (KSM은 4KB 페이지에서만 작동, THP 2MB 켜져 있으면 병합률 급감)
  echo never > /sys/kernel/mm/transparent_hugepage/enabled
  echo never > /sys/kernel/mm/transparent_hugepage/defrag

  # KSM 극대화
  echo 1 > /sys/kernel/mm/ksm/run
  echo 5000 > /sys/kernel/mm/ksm/pages_to_scan    # 기본 1000 → 5000
  echo 90 > /sys/kernel/mm/ksm/max_page_sharing   # 페이지당 최대 병합 수
  ```
- zRAM 압축 스왑 (NVMe 기반 스왑 대신 RAM 압축):
  ```bash
  # zRAM 블록 디바이스 생성 (128GB)
  modprobe zram num_devices=1
  echo 128G > /sys/block/zram0/disksize
  echo zstd > /sys/block/zram0/comp_algorithm
  mkswap /dev/zram0
  swapon -p 100 /dev/zram0
  ```
- 메모리 오버커밋 허용:
  ```bash
  echo 1 > /proc/sys/vm/overcommit_memory
  echo 50 > /proc/sys/vm/swappiness
  ```
- 효과: KSM 40% 절약 + zRAM 3:1 압축 = 실질 메모리 2-3배 확장

**전략 5: browserless 공유 + Chrome 미설치 (이미 적용)**

- 각 VM에 Chrome/Puppeteer 미설치: ~500MB/VM 절약
- a1의 browserless 서버(`http://192.168.1.50:20047`) 공유

#### 300+ VM 메모리 계산 (권장 조합)

**권장 조합: 전략 2 (default_memory=512MB) + 전략 4 (KSM+zRAM) + 전략 5 (browserless)**

| 항목 | 용량 | 비고 |
|------|------|------|
| 호스트 OS + PROOF 서비스 | 50GB | 고정 |
| /dev/shm (DAX 윈도우 백엔드) | 75GB | 300 VM × 256MB DAX 윈도우 (가상 매핑, 실제 물리 메모리 ≈ 0) |
| zRAM 압축 스왑 | 128GB (실제 0GB 사용) | cold page 압축, 디스크 아님 |
| VM 300개 × 512MB 기본 | 150GB | virtio-mem으로 동적 확장 |
| KSM 페이지 병합 (40%) | -60GB | 동일 게스트 커널/라이브러리 |
| virtiofsd 오버헤드 (300개) | ~0.6GB | idle 시 ~2MB/프로세스 |
| **실제 사용량** | **~173GB** | |
| virtio-mem 확장 풀 | ~340GB | 작업 중인 VM만 확장 |
| **여유** | **~339GB** | 동시 작업 VM 약 85개까지 4GB 확장 가능 |

**시나리오**:
- 300개 VM 동시 실행 (대기 상태): 512MB × 300 = 150GB → KSM 적용 ~90GB
- 동시 작업 VM (예: 85개): 4GB 확장 = 340GB 추가
- 총: 50 + 32 + 90 + 340 = 512GB (근사치, zRAM으로 여유 확보)

#### 고밀도 모드 설정 파일

`/etc/kata-containers/configuration-clh-dense.toml` (별도 RuntimeClass):

```toml
[hypervisor.cloud-hypervisor]
default_vcpus = 1
default_maxvcpus = 2
default_memory = 512              # 512MB 기본 (대기 상태)
default_maxmemory = 4096          # 최대 4GB (virtio-mem 확장)
shared_fs = "virtio-fs"
virtio_fs_daemon = "/opt/kata/libexec/virtiofsd"
virtio_fs_cache = "auto"           # 메타데이터 캐시 + 파일 열려 있는 동안 데이터 캐시
virtio_fs_cache_size = 256         # DAX 256MB 윈도우 (300 VM × 256MB = 75GB /dev/shm)
hotplug_method = "virtio-mem"
reclaim_guest_freed_memory = true
enable_mem_prealloc = false
enable_hugepages = false
enable_annotations = []
disable_guest_seccomp = false

[runtime]
sandbox_cgroup_only = true       # cgroup 단순화
```

#### 고밀도 모드 RuntimeClass 등록

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.kata-clh-dense]
  runtime_type = "io.containerd.kata-clh-dense.v2"
```

```bash
# /usr/local/bin/containerd-shim-kata-clh-dense-v2
#!/bin/sh
KATA_CONF_FILE=/etc/kata-containers/configuration-clh-dense.toml
exec /opt/kata/bin/containerd-shim-kata-v2 "$@"
```

#### 고밀도 모드 검증

- [ ] 300개 VM 동시 부팅 테스트 (512MB 기본)
- [ ] KSM 병합률 확인: `grep -E "pages_sharing|pages_shared" /sys/kernel/mm/ksm/mm_ksm`
- [ ] zRAM 압축률 확인: `zramctl`
- [ ] virtio-mem 동적 확장 테스트: 작업 시작 시 512MB → 4GB
- [ ] reclaim_guest_freed_memory: 작업 종료 후 메모리 회수 확인
- [ ] 동시 작업 VM 수 측정 (4GB 확장 기준)
- [ ] browserless 공유로 인한 메모리 절약 확인

#### 고밀도 모드 트레이드오프

| 항목 | 기본 모드 | 고밀도 모드 | 영향 |
|------|----------|------------|------|
| 동시 VM 수 | 150개 | 300+개 | 2배 이상 |
| VM당 기본 메모리 | 2GB | 512MB | 대기 시 메모리 절약 |
| 작업 시 최대 메모리 | 8GB | 4GB | 대용량 처리 시 제약 |
| virtio-fs DAX 윈도우 | 1GB/VM | 256MB/VM | 고밀도 모드는 DAX 윈도우 축소, 여전히 중복 제거 효과 |
| 부팅 시간 | ~200ms | ~150ms | 메모리 적게 할당 → 빠름 |
| 동시 작업 VM | ~85개 | ~85개 | virtio-mem 확장 풀 제약 |
| KSM CPU 오버헤드 | 낮음 | 중간 | pages_to_scan 증가 |

**권장**: 기본 모드(150 VM, 2GB)와 고밀도 모드(300 VM, 512MB)를 RuntimeClass로 분리하여 워크로드에 따라 선택. 문서 처리 등 가벼운 작업은 고밀도, 대용량 이미지/비디오 처리는 기본 모드.

---

## 11. 참고 자료

- [Kata Containers + Cloud Hypervisor 블로그](https://katacontainers.io/blog/kata-containers-with-cloud-hypervisor/)
- [Kata Containers 3.31 릴리스](https://github.com/kata-containers/kata-containers/releases/tag/3.31.0)
- [Kata containerd 통합 가이드](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/containerd-kata.md)
- [Kata virtio-fs 사용 가이드](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-virtio-fs-with-kata.md)
- [virtio-fs DAX 지원 (LWN.net)](https://lwn.net/Articles/813807/)
- [kata-dev: virtiofs cache와 DAX 질문/답변](https://lists.katacontainers.io/archives/list/kata-dev@lists.katacontainers.io/message/TFTCH26TUZ5QJONATATPGGC3DGUBIS45/)
- [Cloud Hypervisor virtio-fs 문서](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/fs.md)
- [Kata Cloud Hypervisor 설정 템플릿](https://github.com/kata-containers/kata-containers/blob/main/src/runtime-rs/config/configuration-cloud-hypervisor.toml.in)
- [Kata 보안 위협 모델](https://github.com/kata-containers/kata-containers/blob/main/docs/threat-model/threat-model.md)
- [Kata Agent Policy 가이드](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-the-kata-agent-policy.md)
- [Kata seccomp (runtime-rs) 가이드](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-seccomp-with-runtime-rs.md)
- [Kata virtio-mem 가이드](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-virtio-mem-with-kata.md)
- [Kata EROFS snapshotter 가이드](https://github.com/kata-containers/kata-containers/blob/main/docs/how-to/how-to-use-erofs-snapshotter-with-kata.md)
- [Cloud Hypervisor 메모리 관리 기법](https://www.cloudhypervisor.org/blog/memory-management-techniques/)
- [Cloud Hypervisor 메모리 설정 문서](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/memory.md)
- [Cloud Hypervisor hotplug 문서](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/hotplug.md)
- [Kata reclaim_guest_freed_memory PR](https://github.com/kata-containers/kata-containers/pull/11185)
- [Kata configuration-cloud-hypervisor.toml 템플릿](https://github.com/kata-containers/kata-containers/blob/main/src/runtime-rs/config/configuration-cloud-hypervisor.toml.in)
- [Browserless 문서 (CDP WebSocket 연결)](https://docs.browserless.io/baas/quick-start)
- [Browserless REST API 참조](https://docs.browserless.io/open-api)
- [Browserless 오픈소스 Docker 배포](https://docs.browserless.io/enterprise/open-source)
- [Docker seccomp 프로필 문서](https://docs.docker.com/engine/security/seccomp/)
- [Kubernetes seccomp 튜토리얼](https://kubernetes.io/docs/tutorials/security/seccomp/)
- [Kubernetes Agent Sandbox (Google)](https://github.com/kubernetes-sigs/agent-sandbox)
- [Kata Containers Agent Sandbox 통합](https://katacontainers.io/blog/kata-containers-agent-sandbox-integration/)
- [GHSA-2gv2-cffp-j227 (virtio-fs 탈출)](https://github.com/kata-containers/kata-containers/security/advisories/GHSA-2gv2-cffp-j227)
- [GHSA-rr59-xxvx-96qr (virtiofsd 인자 주입)](https://github.com/kata-containers/kata-containers/security/advisories/GHSA-rr59-xxvx-96qr)
- [Intel Xeon Gold 6230 스펙](https://www.intel.com/content/www/us/en/products/sku/192437/intel-xeon-gold-6230-processor-27-5m-cache-2-10-ghz/specifications.html)
- [PROOF 프로젝트 AGENTS.md](./AGENTS.md)

---

## 12. 실행 순서 요약

```
Phase 1 (호스트 구성)
  ├─ Ubuntu 24.04 + KVM 확인
  ├─ containerd 2.x 설치
  ├─ Kata 3.31 + Cloud Hypervisor 설치
  ├─ configuration-clh.toml 설정 (virtio-mem, DAX 1GB, cache=auto, reclaim_guest_freed_memory)
  ├─ containerd RuntimeClass 등록
  ├─ /dev/shm 160GB 확장 + THP 비활성화 + KSM 활성화
  └─ nerdctl로 기본 동작 검증

Phase 2 (게스트 이미지)
  ├─ 커스텀 rootfs 빌드 스크립트 작성
  ├─ 문서 처리: LibreOffice, Pandoc, Poppler, Tesseract, MarkItDown
  ├─ 오디오/비디오: FFmpeg, faster-whisper, pydub, librosa
  ├─ 이미지: ImageMagick, Ghostscript, Pillow, OpenCV
  ├─ 폰트: Noto CJK, Nanum, Unfonts, Liberation
  ├─ 비특권 사용자 agent 생성 (UID 1000, sudo 불가)
  ├─ browserless 연동 스크립트 (http://192.168.1.50:20047)
  └─ Kata 설정에 커스텀 이미지 등록

Phase 3 (Sandbox Manager)
  ├─ core/sandbox/ 모듈 구현
  ├─ VM 생명주기 관리
  ├─ workspace 준비 (결과 파일 다운로드 + git init)
  ├─ vsock 통신 구현
  └─ 명령어 블랙리스트 필터링 (security.py)

Phase 4 (FastAPI API)
  ├─ /api/sandboxes/* 라우터
  ├─ DB 마이그레이션 (sandboxes 테이블)
  └─ 인증/권한/포인트 연동

Phase 5 (AI 에이전트 도구)
  ├─ tools/sandbox.ts 작성
  ├─ tools/browserless.ts 작성 (a1 browserless 서버 연동)
  ├─ route.ts에 도구 등록
  ├─ proof-api.ts에 sandbox API 추가
  └─ system prompt 확장

Phase 6 (보안 - 시스템 파괴 차단)
  ├─ Layer 1: read-only rootfs
  ├─ Layer 2: capabilities drop (위험 caps 전면 제거)
  ├─ Layer 3: seccomp 프로필 (mount, mkfs, init_module 등 차단)
  ├─ Layer 4: AppArmor 프로필 (/dev/sda, /proc/kcore 등 차단)
  ├─ Layer 5: Agent Policy (OPA, 심화)
  ├─ 네트워크 격리 (NAT + 방화벽)
  ├─ browserless 토큰 인증
  └─ 리소스 제한 (1 vCPU / 2GB 기본 / 30분 타임아웃)

Phase 7 (프론트엔드)
  ├─ 결과 페이지 "에이전트로 실행" 버튼
  ├─ sandbox 상태 표시
  ├─ workspace 파일 브라우저
  └─ i18n 키 추가

Phase 8 (운영)
  ├─ 로깅/메트릭
  ├─ 자동 정리 (만료/타임아웃)
  ├─ KSM/virtio-mem 메모리 회수 모니터링
  └─ 디스크 모니터링
```
