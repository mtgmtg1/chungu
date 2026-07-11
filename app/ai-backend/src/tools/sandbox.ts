// [Flow: Step 1 (FastAPI /api/sandboxes 로 sandbox 생성) -> Step 2 (execute_command 도구로 셸 명령 실행)
//       -> Step 3 (read_file/write_file 도구로 파일 조작) -> Step 4 (git commit/diff 도구로 변경 관리)
//       -> Step 5 (collect_results 도구로 결과 수집) -> Step 6 (destroy 도구로 sandbox 종료)]
// Kata Containers 샌드박스 도구. AI 에이전트가 격리된 VM 내부에서
// 코드를 실행하고 파일을 조작할 수 있도록 한다.
import { tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';

interface SandboxContext {
  jobId?: string;
  job_id?: string;
  sandboxId?: string;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

/**
 * [Flow: Step 1 (context에서 job_id, authHeaders, sandboxId 추출) -> Step 2 (sandbox 도구들 정의)
 *       -> Step 3 (도구 객체 반환)]
 *
 * 활성 sandbox ID는 클로저로 관리하여 각 채팅 세션마다 독립적으로 유지된다.
 * 이전에는 모듈 레벨 전역 변수를 사용하여 다중 사용자 환경에서 경쟁 조건이 발생했으나,
 * 이제 createSandboxTools 호출 시 클로저로 캡처하여 세션별 격리를 보장한다.
 *
 * @param context 에이전트 컨텍스트 (jobId, sandboxId, authHeaders 포함)
 * @returns sandbox 조작 도구 맵
 */
export function createSandboxTools(context: SandboxContext) {
  const jobId = context.jobId || context.job_id;
  const authHeaders = context.authHeaders;
  // 활성 sandbox ID — 클로저로 관리하여 각 채팅 세션마다 독립 유지
  // context.sandboxId 가 있으면 초기값으로 사용 (프론트엔드가 기존 sandbox 를 재사용하는 경우)
  let activeSandboxId: string | null = (context.sandboxId as string) || null;

  // ========================================
  // 도구 1: sandbox 생성
  // ========================================
  const createSandbox = tool({
    description:
      '새 에이전트 샌드박스(Kata VM)를 생성한다. 이 도구는 sandbox 내부에서 코드를 실행하기 전에 반드시 먼저 호출해야 한다. ' +
      'sandbox 는 격리된 Linux 환경으로, Python/Node.js/git/LibreOffice/FFmpeg/ImageMagick/Tesseract 등이 사전 설치되어 있다. ' +
      'workspace (/workspace) 에 Job 의 결과 파일이 마운트된다.',
    inputSchema: z.object({
      resourceLimits: z
        .object({
          cpu: z.number().min(1).max(4).default(1).describe('CPU 코어 수'),
          memoryMb: z.number().min(512).max(8192).default(2048).describe('메모리 (MB)'),
        })
        .optional()
        .describe('리소스 제한'),
      denseMode: z
        .boolean()
        .default(false)
        .describe('고밀도 모드 (512MB 기본 메모리, 300+ VM 동시 실행 지원)'),
    }),
    execute: async ({ resourceLimits, denseMode }) => {
      if (!jobId) {
        return { error: 'jobId 가 context 에 없습니다' };
      }

      const body: Record<string, unknown> = {
        job_id: jobId,
        dense_mode: denseMode,
      };
      if (resourceLimits) {
        body.resource_limits = {
          cpu: resourceLimits.cpu,
          memory_mb: resourceLimits.memoryMb,
        };
      }

      const result = await proofApi.request<{
        sandbox_id: string;
        status: string;
        workspace: string;
        error?: string;
      }>('/api/sandboxes', 'POST', body, authHeaders);

      if (result.sandbox_id && result.status !== 'error') {
        activeSandboxId = result.sandbox_id;
      }

      return result;
    },
  });

  // ========================================
  // 도구 2: 셸 명령 실행
  // ========================================
  const executeInSandbox = tool({
    description:
      'sandbox 내부에서 셸 명령을 실행한다. Python 스크립트, Node.js 스크립트, git 명령, ' +
      'LibreOffice 변환, FFmpeg 처리, ImageMagick 이미지 변환 등을 수행할 수 있다. ' +
      '명령은 비특권 사용자(agent, UID 1000)로 실행되며, /workspace 가 작업 디렉토리다. ' +
      '위험 명령(rm -rf /, dd of=/dev/, mount, reboot 등)은 보안 정책에 의해 차단된다.',
    inputSchema: z.object({
      command: z.string().describe('실행할 셸 명령어 (예: "python3 /workspace/script.py")'),
      timeout: z
        .number()
        .min(1)
        .max(1800)
        .optional()
        .describe('명령 타임아웃 (초, 기본 300)'),
    }),
    execute: async ({ command, timeout }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다. 먼저 create_sandbox 를 호출하세요.' };
      }

      const body: Record<string, unknown> = { command };
      if (timeout) body.timeout = timeout;

      return proofApi.request<{
        exit_code: number;
        stdout: string;
        stderr: string;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/execute`, 'POST', body, authHeaders);
    },
  });

  // ========================================
  // 도구 3: 파일 읽기
  // ========================================
  const readSandboxFile = tool({
    description:
      'sandbox 의 workspace 에서 파일 내용을 읽는다. ' +
      '에이전트가 생성한 코드, 변환 결과, 로그 등을 확인할 때 사용한다.',
    inputSchema: z.object({
      path: z
        .string()
        .describe('읽을 파일 경로 (예: "/workspace/agent_output/result.csv")'),
    }),
    execute: async ({ path }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      const params = new URLSearchParams({ path });
      return proofApi.request<{
        content: string;
        size: number;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/files/read?${params}`, 'GET', undefined, authHeaders);
    },
  });

  // ========================================
  // 도구 4: 파일 쓰기
  // ========================================
  const writeSandboxFile = tool({
    description:
      'sandbox 의 workspace 에 파일을 쓴다. ' +
      '에이전트가 Python/Node.js 스크립트, 설정 파일, 데이터 파일 등을 생성할 때 사용한다.',
    inputSchema: z.object({
      path: z
        .string()
        .describe('파일 경로 (예: "/workspace/agent_output/script.py")'),
      content: z.string().describe('파일 내용'),
    }),
    execute: async ({ path, content }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      return proofApi.request<{
        status: string;
        path: string;
        error?: string;
      }>(
        `/api/sandboxes/${activeSandboxId}/files/write`,
        'POST',
        { path, content },
        authHeaders,
      );
    },
  });

  // ========================================
  // 도구 5: 파일 목록 조회
  // ========================================
  const listSandboxFiles = tool({
    description:
      'sandbox 의 workspace 내 파일 목록을 조회한다. ' +
      '에이전트가 생성한 파일이나 기존 결과 파일을 확인할 때 사용한다.',
    inputSchema: z.object({
      path: z
        .string()
        .default('/workspace')
        .describe('조회할 디렉토리 경로 (기본: /workspace)'),
    }),
    execute: async ({ path }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      const params = new URLSearchParams({ path });
      return proofApi.request<{
        files: Array<{ name: string; size: number; type: string }>;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/files?${params}`, 'GET', undefined, authHeaders);
    },
  });

  // ========================================
  // 도구 6: git commit
  // ========================================
  const commitSandboxChanges = tool({
    description:
      'sandbox workspace 의 변경사항을 git commit 한다. ' +
      '에이전트가 파일을 생성/수정한 후 호출하여 변경 이력을 남긴다.',
    inputSchema: z.object({
      message: z
        .string()
        .default('Agent changes')
        .describe('commit 메시지'),
    }),
    execute: async ({ message }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      return proofApi.request<{
        status: string;
        commit: string;
        error?: string;
      }>(
        `/api/sandboxes/${activeSandboxId}/commit`,
        'POST',
        { message },
        authHeaders,
      );
    },
  });

  // ========================================
  // 도구 7: git diff 조회
  // ========================================
  const getSandboxDiff = tool({
    description:
      'sandbox workspace 의 git diff 를 조회한다. ' +
      '에이전트가 변경한 내용을 확인할 때 사용한다.',
    inputSchema: z.object({
      cached: z
        .boolean()
        .default(false)
        .describe('staged 변경사항만 조회 여부'),
    }),
    execute: async ({ cached }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      const params = new URLSearchParams({ cached: String(cached) });
      return proofApi.request<{
        diff: string;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/diff?${params}`, 'GET', undefined, authHeaders);
    },
  });

  // ========================================
  // 도구 8: 결과 수집
  // ========================================
  const collectSandboxResults = tool({
    description:
      'sandbox 의 결과 파일을 수집하여 Supabase Storage 에 업로드한다. ' +
      'sandbox 종료 전에 호출하여 에이전트가 생성한 파일을 영구 저장한다. ' +
      'agent_output/, extracted/, annotations/ 디렉토리의 파일이 수집 대상이다.',
    inputSchema: z.object({}),
    execute: async () => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      return proofApi.request<{
        uploaded: number;
        failed: number;
        total_scanned: number;
        files: Array<{ path: string; storage_path: string; size: number }>;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/collect`, 'POST', undefined, authHeaders);
    },
  });

  // ========================================
  // 도구 9: sandbox 종료
  // ========================================
  const destroySandbox = tool({
    description:
      'sandbox 를 종료하고 정리한다. 에이전트 작업이 완료된 후 호출한다. ' +
      '종료 전에 collect_sandbox_results 를 호출하여 결과를 저장하는 것을 권장한다.',
    inputSchema: z.object({}),
    execute: async () => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      const result = await proofApi.request<{
        status: string;
        container: string;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}`, 'DELETE', undefined, authHeaders);

      activeSandboxId = null;
      return result;
    },
  });

  // ========================================
  // 도구 10: 파일 다운로드
  // ========================================
  const downloadFile = tool({
    description:
      'URL 에서 파일을 다운로드하여 workspace 에 저장한다. ' +
      '에이전트가 외부 리소스(이미지, 문서, 데이터 파일)를 가져올 때 사용한다. ' +
      'sandbox 내부에서 curl 을 사용하여 다운로드한다.',
    inputSchema: z.object({
      url: z.string().url().describe('다운로드할 파일 URL'),
      outputPath: z
        .string()
        .describe('저장할 경로 (예: "/workspace/agent_output/data.csv")'),
    }),
    execute: async ({ url, outputPath }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      // curl 로 다운로드 (보안 검사는 execute_in_sandbox 에서 수행됨)
      const cmd = `curl -sL -o "${outputPath}" "${url}"`;
      const result = await proofApi.executeInSandbox(activeSandboxId, cmd, 120, authHeaders);

      if (result.error) return result;

      // 파일 크기 확인
      const sizeResult = await proofApi.executeInSandbox(
        activeSandboxId,
        `stat -c %s "${outputPath}" 2>/dev/null || echo 0`,
        5,
        authHeaders,
      );

      return {
        status: result.exit_code === 0 ? 'ok' : 'error',
        url,
        output_path: outputPath,
        size: parseInt(sizeResult.stdout?.trim() || '0', 10),
        exit_code: result.exit_code,
        stderr: result.stderr,
      };
    },
  });

  // ========================================
  // 도구 11: 문서 변환 (LibreOffice/Pandoc)
  // ========================================
  const convertDocument = tool({
    description:
      'sandbox 내부에서 LibreOffice 또는 Pandoc 을 사용하여 문서를 변환한다. ' +
      '지원 형식: DOCX/XLSX/PPTX/ODT/RTF → PDF (LibreOffice), ' +
      'Markdown/HTML/DOCX/LaTeX/EPUB 상호 변환 (Pandoc). ' +
      '변환된 파일은 workspace 에 저장된다.',
    inputSchema: z.object({
      inputPath: z
        .string()
        .describe('입력 파일 경로 (예: "/workspace/original/document.docx")'),
      outputFormat: z
        .string()
        .describe('출력 형식 (예: "pdf", "md", "html", "docx", "xlsx")'),
      outputPath: z
        .string()
        .describe('출력 파일 경로 (예: "/workspace/agent_output/converted.pdf")'),
      tool: z
        .enum(['libreoffice', 'pandoc', 'auto'])
        .default('auto')
        .describe('사용할 도구 (auto: 형식에 따라 자동 선택)'),
    }),
    execute: async ({ inputPath, outputFormat, outputPath, tool: toolChoice }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      // 도구 자동 선택: PDF 출력은 LibreOffice, 마크다운/HTML은 Pandoc
      const useLibreOffice =
        toolChoice === 'libreoffice' ||
        (toolChoice === 'auto' && outputFormat === 'pdf');
      const usePandoc =
        toolChoice === 'pandoc' ||
        (toolChoice === 'auto' && ['md', 'html', 'docx', 'latex', 'epub'].includes(outputFormat));

      let cmd: string;
      if (useLibreOffice) {
        // LibreOffice headless 변환 (확장자 제거를 위해 shell 파라미터 확장 사용)
        const outputDir = outputPath.substring(0, outputPath.lastIndexOf('/'));
        const baseName = inputPath.split('/').pop() || inputPath;
        const baseNameNoExt = baseName.replace(/\.[^.]+$/, '');
        cmd = `mkdir -p "${outputDir}" && soffice --headless --convert-to ${outputFormat} --outdir "${outputDir}" "${inputPath}" && mv "${outputDir}/${baseNameNoExt}.${outputFormat}" "${outputPath}" 2>/dev/null || true`;
      } else if (usePandoc) {
        // Pandoc 변환
        const outputDir = outputPath.substring(0, outputPath.lastIndexOf('/'));
        cmd = `mkdir -p "${outputDir}" && pandoc "${inputPath}" -o "${outputPath}"`;
      } else {
        return { error: `지원하지 않는 변환: ${inputPath} → ${outputFormat}` };
      }

      const result = await proofApi.executeInSandbox(activeSandboxId, cmd, 300, authHeaders);

      return {
        status: result.exit_code === 0 ? 'ok' : 'error',
        input_path: inputPath,
        output_path: outputPath,
        output_format: outputFormat,
        tool_used: useLibreOffice ? 'libreoffice' : 'pandoc',
        exit_code: result.exit_code,
        stdout: result.stdout,
        stderr: result.stderr,
      };
    },
  });

  // ========================================
  // 도구 12: 오디오 텍스트 변환 (Whisper)
  // ========================================
  const transcribeAudio = tool({
    description:
      'sandbox 내부에서 faster-whisper 를 사용하여 오디오 파일을 텍스트로 변환한다. ' +
      'small 모델이 사전 설치되어 있어 런타임 다운로드가 필요 없다. ' +
      '변환된 텍스트는 workspace 에 저장된다.',
    inputSchema: z.object({
      audioPath: z
        .string()
        .describe('오디오 파일 경로 (예: "/workspace/original/audio.mp3")'),
      outputPath: z
        .string()
        .describe('출력 텍스트 파일 경로 (예: "/workspace/agent_output/transcript.txt")'),
      language: z
        .string()
        .optional()
        .describe('언어 코드 (예: "ko", "en", "ja"). 생략 시 자동 감지'),
    }),
    execute: async ({ audioPath, outputPath, language }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      const langArg = language ? `, language="${language}"` : '';
      const cmd = `python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('small', device='cpu', compute_type='int8'${langArg})
segments, info = model.transcribe('${audioPath}')
text = '\\n'.join([seg.text for seg in segments])
with open('${outputPath}', 'w') as f:
    f.write(text)
print(f'Duration: {info.duration:.1f}s')
print(f'Language: {info.language}')
print(f'Text length: {len(text)}')
" 2>&1`;

      const result = await proofApi.executeInSandbox(activeSandboxId, cmd, 600, authHeaders);

      return {
        status: result.exit_code === 0 ? 'ok' : 'error',
        audio_path: audioPath,
        output_path: outputPath,
        exit_code: result.exit_code,
        stdout: result.stdout,
        stderr: result.stderr,
      };
    },
  });

  // ========================================
  // 도구 13: 이미지 처리 (ImageMagick/Pillow)
  // ========================================
  const processImage = tool({
    description:
      'sandbox 내부에서 ImageMagick 또는 Pillow 를 사용하여 이미지를 처리한다. ' +
      '리사이즈, 포맷 변환, 크롭, 회전, 필터 적용 등을 수행할 수 있다. ' +
      '처리된 이미지는 workspace 에 저장된다.',
    inputSchema: z.object({
      inputPath: z
        .string()
        .describe('입력 이미지 경로 (예: "/workspace/original/image.png")'),
      outputPath: z
        .string()
        .describe('출력 이미지 경로 (예: "/workspace/agent_output/resized.jpg")'),
      operation: z
        .enum(['resize', 'convert', 'rotate', 'crop', 'grayscale', 'thumbnail'])
        .describe('수행할 작업'),
      params: z
        .record(z.string())
        .optional()
        .describe('작업별 파라미터 (resize: {width, height}, rotate: {degrees}, crop: {x, y, width, height})'),
    }),
    execute: async ({ inputPath, outputPath, operation, params }) => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      const outputDir = outputPath.substring(0, outputPath.lastIndexOf('/'));
      let cmd: string;

      switch (operation) {
        case 'resize': {
          const w = params?.width || 'auto';
          const h = params?.height || 'auto';
          cmd = `mkdir -p "${outputDir}" && magick "${inputPath}" -resize ${w}x${h} "${outputPath}"`;
          break;
        }
        case 'convert':
          cmd = `mkdir -p "${outputDir}" && magick "${inputPath}" "${outputPath}"`;
          break;
        case 'rotate': {
          const deg = params?.degrees || '90';
          cmd = `mkdir -p "${outputDir}" && magick "${inputPath}" -rotate ${deg} "${outputPath}"`;
          break;
        }
        case 'crop': {
          const x = params?.x || '0';
          const y = params?.y || '0';
          const w = params?.width || '100';
          const h = params?.height || '100';
          cmd = `mkdir -p "${outputDir}" && magick "${inputPath}" -crop ${w}x${h}+${x}+${y} "${outputPath}"`;
          break;
        }
        case 'grayscale':
          cmd = `mkdir -p "${outputDir}" && magick "${inputPath}" -colorspace Gray "${outputPath}"`;
          break;
        case 'thumbnail': {
          const w = params?.width || '200';
          const h = params?.height || '200';
          cmd = `mkdir -p "${outputDir}" && python3 -c "
from PIL import Image
img = Image.open('${inputPath}')
img.thumbnail((${w}, ${h}))
img.save('${outputPath}')
print(f'Thumbnail saved: {img.size}')
"`;
          break;
        }
        default:
          return { error: `지원하지 않는 작업: ${operation}` };
      }

      const result = await proofApi.executeInSandbox(activeSandboxId, cmd, 120, authHeaders);

      return {
        status: result.exit_code === 0 ? 'ok' : 'error',
        input_path: inputPath,
        output_path: outputPath,
        operation,
        exit_code: result.exit_code,
        stdout: result.stdout,
        stderr: result.stderr,
      };
    },
  });

  // ========================================
  // 도구 14: sandbox 상태 조회
  // ========================================
  const getWorkspaceStatus = tool({
    description:
      'sandbox 의 상태와 리소스 사용량을 조회한다. ' +
      'sandbox 가 정상적으로 실행 중인지, 디스크 사용량은 얼마인지 확인할 때 사용한다.',
    inputSchema: z.object({}),
    execute: async () => {
      if (!activeSandboxId) {
        return { error: 'sandbox 가 생성되지 않았습니다.' };
      }

      // sandbox 상태 조회
      const status = await proofApi.getSandboxStatus(activeSandboxId, authHeaders);

      // 디스크 사용량 조회
      const diskResult = await proofApi.executeInSandbox(
        activeSandboxId,
        'du -sh /workspace 2>/dev/null && df -h /workspace 2>/dev/null | tail -1',
        10,
        authHeaders,
      );

      // 파일 수 조회
      const fileCountResult = await proofApi.executeInSandbox(
        activeSandboxId,
        'find /workspace -type f 2>/dev/null | wc -l',
        10,
        authHeaders,
      );

      return {
        sandbox_id: activeSandboxId,
        status: (status as any).status || 'unknown',
        disk_usage: diskResult.stdout?.trim() || '',
        file_count: parseInt(fileCountResult.stdout?.trim() || '0', 10),
        ...status,
      };
    },
  });

  return {
    create_sandbox: createSandbox,
    execute_in_sandbox: executeInSandbox,
    read_sandbox_file: readSandboxFile,
    write_sandbox_file: writeSandboxFile,
    list_sandbox_files: listSandboxFiles,
    commit_sandbox_changes: commitSandboxChanges,
    get_sandbox_diff: getSandboxDiff,
    collect_sandbox_results: collectSandboxResults,
    destroy_sandbox: destroySandbox,
    download_file: downloadFile,
    convert_document: convertDocument,
    transcribe_audio: transcribeAudio,
    process_image: processImage,
    get_workspace_status: getWorkspaceStatus,
  };
}
