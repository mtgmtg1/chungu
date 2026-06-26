# Chungu · PDF → CSV/MD 변환 앱

대규모 PDF(표·정형/비정형 서식 포함)를 업로드하면 백그라운드에서 OCR·LLM으로 파싱해 **CSV/MD로 변환**하고, 완료 시 **다운로드 링크 이메일**을 보내는 웹앱입니다. 코드를 모르는 사용자가 이메일만 입력하면 됩니다.

## 주요 기능

- **이메일만 입력**하는 단순 업로드 (로그인 불필요)
- **Vision**(이미지 직접 분석) / **Hybrid**(Tesseract+LLM) 두 파이프라인 선택
- **사용자 정의 컬럼/추가 지시** 지원 (범용 표 추출)
- 페이지 단위 **진행률 표시** + 완료 **이메일 알림**(만료형 다운로드 링크)
- **관리자 페이지**: LLM 모델/엔드포인트·SMTP·작업 제한 변경, 작업 모니터링
- **OpenAI 호환 API** 사용 (로컬 vLLM·외부 API 모두 지원)

## 아키텍처

```
브라우저 ──업로드──▶ FastAPI(api) ──큐잉──▶ Redis ──▶ Celery(worker)
                         │                              │ 1.PDF→이미지(pdftoppm)
                         │                              │ 2.Vision/Hybrid OCR(LLM)
   진행률 폴링 ◀─────────┘                              │ 3.표 병합 → CSV/MD
                                                        │ 4.다운로드 토큰 + 이메일
   PostgreSQL: Job·AdminUser·AppSetting                 ▼
                                              결과 저장(/data) + SMTP 발송
```

## 디렉터리

```
app/
  backend/      FastAPI + Celery + core 파이프라인
    core/       ocr_client·pipeline_vision·pipeline_hybrid·merge·converter·prompts
    api/        jobs.py(사용자) · admin.py(관리자)
    auth/       security(bcrypt·JWT) · crypto(민감값 암호화)
    db/         models · session
    workers/    tasks.py(run_job)
  frontend/     React + Vite + Tailwind (사용자 업로드 + 관리자 대시보드)
  Dockerfile.backend   poppler·tesseract·imagemagick 포함
  docker-compose.yml   api · worker · redis · postgres
```

## 배포 (a1 서버)

a1: `192.168.1.50` (HamoniKR 8.0, Docker 설치됨). 앱은 `~/chungu-app`에 배포됩니다.

### 최초 배포 / 재배포

```bash
# 1) 로컬에서 소스 동기화
rsync -az --delete \
  --exclude '__pycache__' --exclude 'node_modules' \
  --exclude 'frontend/dist' --exclude '.env' --exclude 'data' \
  app/ a1:~/chungu-app/

# 2) (최초 1회) .env 생성 - SECRET_KEY·DB 비번 자동 생성
ssh a1 'cd ~/chungu-app && \
  SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))"); \
  PGPW=$(python3 -c "import secrets;print(secrets.token_urlsafe(16))"); \
  sed -e "s|changeme_generate_a_long_random_secret|$SECRET|" \
      -e "s|changeme_postgres|$PGPW|g" .env.example > .env'

# 3) 빌드 + 기동
ssh a1 'cd ~/chungu-app && docker compose up -d --build'

# 4) 헬스체크
ssh a1 'curl -s http://localhost:28181/api/health'   # {"status":"ok"}
```

### 접속

- 사용자 UI: `http://192.168.1.50:28181/`
- 관리자: `http://192.168.1.50:28181/admin`
- 외부 노출: Cloudflare Tunnel을 `28181`로 연결 (별도 설정)

## 초기 관리자 계정

- 이메일: `mtgmtg@naver.com`
- 초기 비밀번호: `JDg629714!@` (로그인 후 **반드시 변경** 권장, bcrypt 해시 저장)

## 기본 LLM 설정 (관리자 페이지에서 변경 가능)

- 엔드포인트: `http://192.168.1.69:18080/v1` (프록시 → :18000/:18001 분산)
- 모델: `cyankiwi/Qwen3.6-27B-AWQ-INT4`
- API Key: 없음

## SMTP (이메일 발송)

자체 메일 서버 정보를 **관리자 페이지 → SMTP 설정**에서 입력하세요. 미설정 시 변환은 정상 동작하되 완료 이메일만 생략됩니다(작업 화면의 다운로드 링크로 받기 가능). 비밀번호는 `SECRET_KEY`로 암호화 저장됩니다.

## 운영 명령

```bash
ssh a1 'cd ~/chungu-app && docker compose ps'                  # 상태
ssh a1 'cd ~/chungu-app && docker compose logs api --tail 50'  # API 로그
ssh a1 'cd ~/chungu-app && docker compose logs worker -f'      # 워커 로그
ssh a1 'cd ~/chungu-app && docker compose restart api worker'  # 재시작
ssh a1 'cd ~/chungu-app && docker compose down'                # 중지
```

## 환경변수 (.env)

| 키 | 설명 |
| :--- | :--- |
| `APP_PORT` | 서비스 포트 (기본 28181) |
| `PUBLIC_BASE_URL` | 이메일 다운로드 링크 베이스 URL |
| `SECRET_KEY` | 세션 서명 + 민감설정 암호화 키 (필수 변경) |
| `ADMIN_EMAIL` / `ADMIN_INITIAL_PASSWORD` | 최초 관리자 시드 |
| `DEFAULT_LLM_ENDPOINT` / `DEFAULT_LLM_MODEL` | 기본 LLM |
| `MAX_FILE_MB` / `MAX_PAGES` / `DOWNLOAD_EXPIRE_DAYS` | 작업 제한 |

## 참고

- 기존 `ocr_run.py`(vision)·`ocr_hybrid.py`(hybrid)·`merge_csv.py`의 로직을 일반화해 재사용했습니다.
- 거래내역서 전용 후처리(예: 541행 추출)는 이 범용 앱에 포함되지 않습니다.
