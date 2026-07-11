// [Flow: Step 1 (Supabase 세션 토큰 획득) -> Step 2 (TUS Upload 인스턴스 생성) -> Step 3 (청크 업로드 진행) -> Step 4 (완료 시 resolve)]
import * as tus from 'tus-js-client'
import { supabase } from './supabase.js'

/**
 * 단일 파일을 Supabase Storage의 pdfs 버킷에 TUS 프로토콜로 업로드한다.
 * 각 청크는 6MB로 Cloudflare Tunnel의 100MB 제한을 회피한다.
 *
 * @param {File} file - 업로드할 파일 객체
 * @param {string} storagePath - Storage 내 저장 경로 (예: "jobId/filename.pdf")
 * @param {function} onProgress - 진행률 콜백 (percentage: number) => void
 * @returns {Promise<void>} 업로드 완료 시 resolve
 */
export function uploadFileTUS(file, storagePath, onProgress) {
  return new Promise(async (resolve, reject) => {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session?.access_token) {
      reject(new Error('인증 세션이 없습니다'))
      return
    }

    const endpoint = `${window.location.origin}/supabase/storage/v1/upload/resumable`

    // [Flow: fingerprint에 storagePath(job_id 포함)를 추가 -> 동일 파일이어도 job마다 고유 fingerprint -> 이전 job 업로드로 resume되는 것 방지]
    const fingerprint = ['tus-br', file.name, file.type, file.size, file.lastModified, endpoint, storagePath].join('-')
    console.log('[TUS] 업로드 시작', {
      name: file.name,
      size: file.size,
      type: file.type,
      lastModified: file.lastModified,
      storagePath,
      fingerprint,
    })
    const upload = new tus.Upload(file, {
      endpoint,
      retryDelays: [0, 3000, 5000, 10000, 20000],
      headers: {
        authorization: `Bearer ${session.access_token}`,
        'x-upsert': 'true',
      },
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      // fingerprint에 storagePath를 포함해 job마다 고유 키 생성.
      // 기본 fingerprint는 file.name/size/lastModified/endpoint만 사용하므로
      // 같은 파일을 재업로드하면 이전 job의 TUS upload URL로 resume되어
      // 기존 작업 공간에 덮어쓰는 문제가 발생한다.
      fingerprint: () => Promise.resolve(fingerprint),
      metadata: {
        bucketName: 'pdfs',
        objectName: storagePath,
        contentType: file.type || 'application/octet-stream',
        cacheControl: '3600',
      },
      chunkSize: 6 * 1024 * 1024,
      // [Flow: 개발 모드에서 Supabase가 외부 URL(proof.teamcat.app)을 Location 헤더로 반환하면 -> 로컬 origin(/supabase)으로 재작성]
      onUploadUrlAvailable() {
        if (import.meta.env.DEV && upload.url) {
          try {
            const originalUrl = new URL(upload.url)
            const localPath = `${originalUrl.pathname}${originalUrl.search}`
            const rewrittenUrl = `${window.location.origin}/supabase${localPath.replace(/^\/supabase/, '')}`
            upload.url = rewrittenUrl
            console.log('[TUS dev] upload URL rewritten to local:', rewrittenUrl)
          } catch (err) {
            console.warn('[TUS dev] upload URL rewrite failed:', err.message)
          }
        }
      },
      onError(error) {
        console.error('[TUS] 업로드 오류:', file.name, storagePath, error)
        reject(error)
      },
      onProgress(bytesUploaded, bytesTotal) {
        const percentage = ((bytesUploaded / bytesTotal) * 100).toFixed(2)
        if (onProgress) onProgress(parseFloat(percentage))
      },
      onSuccess() {
        console.log('[TUS] 업로드 완료:', file.name, storagePath)
        resolve()
      },
    })

    // [Flow: 이전 TUS 업로드 resume을 비활성화 -> fingerprint 버그/Storage 캐싱으로 잘못된 파일이 업로드되는 문제 방지]
    // 대용량 파일 재업로드 시 네트워크가 끊기면 처음부터 다시 시작되지만, 파일이 바뀌는 버그를 막는 것이 우선이다.
    console.log('[TUS] 새 업로드 시작 (resume 비활성화):', file.name, storagePath)
    upload.start()
  })
}

/**
 * 여러 파일을 순차적으로 TUS 업로드한다.
 *
 * @param {Array<{file: File, storagePath: string}>} items - 업로드 항목 목록
 * @param {function} onFileProgress - (fileIndex: number, percentage: number) => void
 * @param {function} onFileComplete - (fileIndex: number) => void
 * @returns {Promise<void>} 모든 파일 업로드 완료 시 resolve
 */
export async function uploadFilesTUS(items, onFileProgress, onFileComplete) {
  for (let i = 0; i < items.length; i++) {
    const { file, storagePath } = items[i]
    await uploadFileTUS(file, storagePath, (pct) => {
      if (onFileProgress) onFileProgress(i, pct)
    })
    if (onFileComplete) onFileComplete(i)
  }
}
