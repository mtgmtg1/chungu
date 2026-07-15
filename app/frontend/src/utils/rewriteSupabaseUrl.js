// [Flow: Step 1 (Supabase Storage URL 수신) -> Step 2 (내부/외부 public URL 패턴 감지) -> Step 3 (감지되면 /supabase 상대 경로로 재작성)]

/** 브라우저에서 직접 접근할 수 없는 Supabase Storage URL 패턴 목록. */
const INTERNAL_SUPABASE_PATTERNS = [
  /^http:\/\/192\.168\.1\.50:28000/,
  /^https:\/\/proof\.teamcat\.app\/supabase/,
];

/**
 * Supabase Storage URL을 브라우저가 현재 origin을 통해 접근할 수 있는 경로로 재작성한다.
 * 개발 환경에서는 내부 IP URL을 /supabase 프록시 경로로 변환하고,
 * 프로덕션에서도 동일 origin의 /supabase 경로를 사용하면 백엔드 프록시를 탄다.
 *
 * @param {string|null|undefined} url - 재작성할 URL
 * @returns {string|null|undefined} 재작성된 URL
 */
export function rewriteSupabaseUrl(url) {
  if (!url || typeof url !== "string") return url;
  for (const pattern of INTERNAL_SUPABASE_PATTERNS) {
    if (pattern.test(url)) {
      return url.replace(pattern, "/supabase");
    }
  }
  return url;
}

/**
 * previewJob 응답 객체 내부의 Supabase Storage URL 필드들을 재작성한다.
 *
 * @param {Object} data - previewJob 응답 객체
 * @returns {Object} URL이 재작성된 응답 객체
 */
export function rewritePreviewUrls(data) {
  if (!data || typeof data !== "object") return data;
  const result = { ...data };

  if (typeof result.source_url === "string") {
    result.source_url = rewriteSupabaseUrl(result.source_url);
  }

  if (Array.isArray(result.image_urls)) {
    result.image_urls = result.image_urls.map(rewriteSupabaseUrl);
  }

  if (Array.isArray(result.source_files)) {
    result.source_files = result.source_files.map((file) => {
      if (!file || typeof file !== "object") return file;
      return {
        ...file,
        url: rewriteSupabaseUrl(file.url),
        preview_url: rewriteSupabaseUrl(file.preview_url),
        annotations_json_url: rewriteSupabaseUrl(file.annotations_json_url),
        user_annotations_json_url: rewriteSupabaseUrl(file.user_annotations_json_url),
      };
    });
  }

  return result;
}
