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

    const upload = new tus.Upload(file, {
      endpoint,
      retryDelays: [0, 3000, 5000, 10000, 20000],
      headers: {
        authorization: `Bearer ${session.access_token}`,
        'x-upsert': 'true',
      },
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      metadata: {
        bucketName: 'pdfs',
        objectName: storagePath,
        contentType: file.type || 'application/octet-stream',
        cacheControl: '3600',
      },
      chunkSize: 6 * 1024 * 1024,
      onError(error) {
        reject(error)
      },
      onProgress(bytesUploaded, bytesTotal) {
        const percentage = ((bytesUploaded / bytesTotal) * 100).toFixed(2)
        if (onProgress) onProgress(parseFloat(percentage))
      },
      onSuccess() {
        resolve()
      },
    })

    upload.findPreviousUploads().then((previousUploads) => {
      if (previousUploads.length) {
        upload.resumeFromPreviousUpload(previousUploads[0])
      }
      upload.start()
    })
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
