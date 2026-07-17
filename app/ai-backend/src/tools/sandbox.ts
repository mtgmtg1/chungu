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
      'Create a new agent code-running sandbox / 코드 실행 공간 (Kata VM). This tool must be called first before executing Python/scripts inside the sandbox. ' +
      'The sandbox is an isolated Linux environment with Python/Node.js/git/LibreOffice/FFmpeg/ImageMagick/Tesseract pre-installed. ' +
      "The job's result files are mounted in /workspace. " +
      'Important: user-visible filenames (e.g., "report.pdf") are placed in /workspace/original/ with their original filenames. ' +
      'Reading /workspace/_file_mapping.json shows the mapping of user filenames to sandbox internal paths. ' +
      'Always use /workspace/original/{filename} when the user mentions a filename.',
    inputSchema: z.object({
      resourceLimits: z
        .object({
          cpu: z.number().min(1).max(4).default(1).describe('CPU core count'),
          memoryMb: z.number().min(512).max(8192).default(2048).describe('Memory (MB)'),
        })
        .optional()
        .describe('Resource limits'),
      denseMode: z
        .boolean()
        .default(false)
        .describe('Dense mode (512MB default memory, supports 300+ VMs running simultaneously)'),
    }),
    execute: async ({ resourceLimits, denseMode }) => {
      if (!jobId) {
        return { error: 'jobId is missing in context' };
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
      'Execute a shell command inside the sandbox / 코드 실행 공간. Can run Python scripts, Node.js scripts, git commands, ' +
      'LibreOffice conversion, FFmpeg processing, ImageMagick image conversion, etc. ' +
      'Commands run as an unprivileged user (agent, UID 1000) with /workspace as the working directory. ' +
      'Dangerous commands (rm -rf /, dd of=/dev/, mount, reboot, etc.) are blocked by security policy. ' +
      'Filename guide: user-visible filenames are in /workspace/original/ with their original names. ' +
      'Example: if the user says "report.pdf", it refers to /workspace/original/report.pdf. ' +
      '/workspace/input.pdf is the same file, but using the original filename is recommended. ' +
      'If this command creates or modifies files, call collect_sandbox_results next so the user can see them in the file panel. ' +
      'Files must be saved under /workspace/agent_output/, /workspace/extracted/, or /workspace/annotations/ to be collected.',
    inputSchema: z.object({
      command: z.string().describe('Shell command to execute (e.g., "python3 /workspace/script.py")'),
      timeout: z
        .number()
        .min(1)
        .max(1800)
        .optional()
        .describe('Command timeout in seconds (default 300)'),
    }),
    execute: async ({ command, timeout }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created. Call create_sandbox first.' };
      }

      const body: Record<string, unknown> = { command };
      if (timeout) body.timeout = timeout;

      return proofApi.request<{
        exit_code: number;
        stdout: string;
        stderr: string;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/execute`, 'POST', body, authHeaders).then(
        // [Flow: 출력 크기 제한 — stdout/stderr 를 2000자로 잘라서 토큰 소비 절약]
        (result: { exit_code: number; stdout: string; stderr: string; error?: string }) => ({
          ...result,
          stdout: _truncate(result.stdout, 2000),
          stderr: _truncate(result.stderr, 1000),
        }),
      );
    },
  });

  // ========================================
  // 도구 3: 파일 읽기
  // ========================================
  const readSandboxFile = tool({
    description:
      'Read the contents of a file from the sandbox workspace / 코드 실행 공간. ' +
      'Use to check code generated by the agent, conversion results, logs, etc. ' +
      'User-visible filenames are placed in /workspace/original/ with their original names. ' +
      'Example: if the user asks for "report.pdf", read /workspace/original/report.pdf.',
    inputSchema: z.object({
      path: z
        .string()
        .describe('Path of the file to read (e.g., "/workspace/original/report.pdf" or "/workspace/agent_output/result.csv")'),
    }),
    execute: async ({ path }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
      }

      const params = new URLSearchParams({ path });
      return proofApi.request<{
        content: string;
        size: number;
        error?: string;
      }>(`/api/sandboxes/${activeSandboxId}/files/read?${params}`, 'GET', undefined, authHeaders).then(
        // [Flow: 출력 크기 제한 — 파일 내용을 4000자로 잘라서 토큰 소비 절약]
        (result: { content: string; size: number; error?: string }) => ({
          ...result,
          content: _truncate(result.content, 4000),
        }),
      );
    },
  });

  // ========================================
  // 도구 4: 파일 쓰기
  // ========================================
  const writeSandboxFile = tool({
    description:
      'Write a file to the sandbox workspace / 코드 실행 공간. ' +
      'Use when the agent creates Python/Node.js scripts, config files, data files, etc. ' +
      'After writing, the result is automatically collected so the user can see the new file in the file panel. ' +
      'Files must be under /workspace/agent_output/, /workspace/extracted/, or /workspace/annotations/ to be collected.',
    inputSchema: z.object({
      path: z
        .string()
        .describe('File path (e.g., "/workspace/agent_output/script.py")'),
      content: z.string().describe('File content'),
    }),
    execute: async ({ path, content }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
      }

      const writeResult = await proofApi.request<{
        status: string;
        path: string;
        error?: string;
      }>(
        `/api/sandboxes/${activeSandboxId}/files/write`,
        'POST',
        { path, content },
        authHeaders,
      );

      if (writeResult.error) {
        return writeResult;
      }

      // [Flow: 파일 쓰기 후 자동으로 collect 호출 — 사용자가 파일패널에서 새 파일을 볼 수 있게 함]
      let collectResult;
      try {
        collectResult = await proofApi.collectSandboxResults(activeSandboxId, authHeaders);
      } catch (e) {
        collectResult = { error: String(e) };
      }

      return {
        ...writeResult,
        collect_status: collectResult.error ? 'error' : 'ok',
        collect_result: collectResult,
      };
    },
  });

  // ========================================
  // 도구 5: 파일 목록 조회
  // ========================================
  const listSandboxFiles = tool({
    description:
      'List files in the sandbox workspace / 코드 실행 공간. ' +
      'Use to check files generated by the agent or existing result files. ' +
      'Original files uploaded by the user are in /workspace/original/ with their original filenames. ' +
      'Reading /workspace/_file_mapping.json shows the user filename ↔ path mapping.',
    inputSchema: z.object({
      path: z
        .string()
        .default('/workspace/original')
        .describe('Directory path to list (default: /workspace/original — where the user\'s original files are located)'),
    }),
    execute: async ({ path }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'git commit changes in the sandbox workspace / 코드 실행 공간. ' +
      'Call after the agent creates/modifies files to leave a change history.',
    inputSchema: z.object({
      message: z
        .string()
        .default('Agent changes')
        .describe('Commit message'),
    }),
    execute: async ({ message }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Retrieve the git diff of the sandbox workspace / 코드 실행 공간. ' +
      'Use to check changes made by the agent.',
    inputSchema: z.object({
      cached: z
        .boolean()
        .default(false)
        .describe('Whether to show only staged changes'),
    }),
    execute: async ({ cached }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Collect result files from the sandbox / 코드 실행 공간 and upload them to Supabase Storage. ' +
      'This makes newly created or modified files visible to the user in the file panel. ' +
      'Call after creating or modifying files, and before destroying the sandbox. ' +
      'Only files under /workspace/agent_output/, /workspace/extracted/, and /workspace/annotations/ are collected.',
    inputSchema: z.object({}),
    execute: async () => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Destroy and clean up the sandbox / 코드 실행 공간. Call after the agent\'s work is complete. ' +
      'IMPORTANT: Always call collect_sandbox_results first to save any new files so the user can see them in the file panel. ' +
      'If files were not collected, they will be lost when the sandbox is destroyed.',
    inputSchema: z.object({}),
    execute: async () => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Download a file from a URL and save it to the sandbox workspace / 코드 실행 공간. ' +
      'Use when the agent fetches external resources (images, documents, data files). ' +
      'Downloads using curl inside the sandbox. ' +
      'After downloading, the result is automatically collected so the user can see the new file in the file panel. ' +
      'Save files under /workspace/agent_output/, /workspace/extracted/, or /workspace/annotations/ to be collected.',
    inputSchema: z.object({
      url: z.string().url().describe('URL of the file to download'),
      outputPath: z
        .string()
        .describe('Path to save to (e.g., "/workspace/agent_output/data.csv")'),
    }),
    execute: async ({ url, outputPath }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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

      const downloadResult = {
        status: result.exit_code === 0 ? 'ok' : 'error',
        url,
        output_path: outputPath,
        size: parseInt(sizeResult.stdout?.trim() || '0', 10),
        exit_code: result.exit_code,
        stderr: result.stderr,
      };

      if (downloadResult.status !== 'ok') {
        return downloadResult;
      }

      // [Flow: 파일 다운로드 후 자동으로 collect 호출 — 사용자가 파일패널에서 새 파일을 볼 수 있게 함]
      let collectResult;
      try {
        collectResult = await proofApi.collectSandboxResults(activeSandboxId, authHeaders);
      } catch (e) {
        collectResult = { error: String(e) };
      }

      return {
        ...downloadResult,
        collect_status: collectResult.error ? 'error' : 'ok',
        collect_result: collectResult,
      };
    },
  });

  // ========================================
  // 도구 11: 문서 변환 (LibreOffice/Pandoc)
  // ========================================
  const convertDocument = tool({
    description:
      'Convert documents using LibreOffice or Pandoc inside the sandbox / 코드 실행 공간. ' +
      'Supported formats: DOCX/XLSX/PPTX/ODT/RTF → PDF (LibreOffice), ' +
      'mutual conversion of Markdown/HTML/DOCX/LaTeX/EPUB (Pandoc). ' +
      'Converted files are saved in the workspace. ' +
      'After conversion, call collect_sandbox_results so the user can see the output file in the file panel.',
    inputSchema: z.object({
      inputPath: z
        .string()
        .describe('Input file path (e.g., "/workspace/original/document.docx")'),
      outputFormat: z
        .string()
        .describe('Output format (e.g., "pdf", "md", "html", "docx", "xlsx")'),
      outputPath: z
        .string()
        .describe('Output file path (e.g., "/workspace/agent_output/converted.pdf")'),
      tool: z
        .enum(['libreoffice', 'pandoc', 'auto'])
        .default('auto')
        .describe('Tool to use (auto: automatically selected by format)'),
    }),
    execute: async ({ inputPath, outputFormat, outputPath, tool: toolChoice }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Convert audio files to text using faster-whisper inside the sandbox / 코드 실행 공간. ' +
      'The small model is pre-installed so no runtime download is needed. ' +
      'The converted text is saved in the workspace. ' +
      'After transcription, call collect_sandbox_results so the user can see the transcript file in the file panel.',
    inputSchema: z.object({
      audioPath: z
        .string()
        .describe('Audio file path (e.g., "/workspace/original/audio.mp3")'),
      outputPath: z
        .string()
        .describe('Output text file path (e.g., "/workspace/agent_output/transcript.txt")'),
      language: z
        .string()
        .optional()
        .describe('Language code (e.g., "ko", "en", "ja"). If omitted, auto-detected'),
    }),
    execute: async ({ audioPath, outputPath, language }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Process images using ImageMagick or Pillow inside the sandbox / 코드 실행 공간. ' +
      'Can perform resize, format conversion, crop, rotate, filter application, etc. ' +
      'The processed image is saved in the workspace. ' +
      'After processing, call collect_sandbox_results so the user can see the output image in the file panel.',
    inputSchema: z.object({
      inputPath: z
        .string()
        .describe('Input image path (e.g., "/workspace/original/image.png")'),
      outputPath: z
        .string()
        .describe('Output image path (e.g., "/workspace/agent_output/resized.jpg")'),
      operation: z
        .enum(['resize', 'convert', 'rotate', 'crop', 'grayscale', 'thumbnail'])
        .describe('Operation to perform'),
      params: z
        .record(z.string())
        .optional()
        .describe('Operation-specific parameters (resize: {width, height}, rotate: {degrees}, crop: {x, y, width, height})'),
    }),
    execute: async ({ inputPath, outputPath, operation, params }) => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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
      'Check the sandbox / 코드 실행 공간 status and resource usage. ' +
      'Use to verify that the sandbox is running normally and to check disk usage.',
    inputSchema: z.object({}),
    execute: async () => {
      if (!activeSandboxId) {
        return { error: 'Sandbox has not been created.' };
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

/**
 * [Flow: Step 1 (문자열과 최대 길이 수신) -> Step 2 (최대 길이 초과 시 잘라내고 생략 표시) -> Step 3 (반환)]
 *
 * _truncate — 문자열을 지정된 최대 길이로 자른다.
 * 도구 출력(stdout/stderr/file content)이 너무 길어 토큰을 과소비하는 것을 방지한다.
 *
 * @param str 원본 문자열
 * @param maxLen 최대 길이 (문자 수)
 * @returns 잘린 문자열 (원본보다 짧으면 "...[truncated]" 접미사 추가)
 */
function _truncate(str: string | undefined, maxLen: number): string {
  if (!str) return '';
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + '\n...[truncated]';
}
