// [Flow: Step 1 (요청에서 Authorization 또는 X-Api-Key 헤더 추출) -> Step 2 (형식 기본 검증)
//       -> Step 3 (FastAPI 호출용 헤더 객체 반환)]
// Node.js AI 백엔드의 인증 미들웨어. 실제 사용자/권한 검증은 Python FastAPI에 위임하고,
// 여기서는 헤더를 추출해 downstream API 호출에 전달한다.
import type { Request, Response, NextFunction } from 'express';

export interface AuthHeaders {
  Authorization?: string;
  'X-Api-Key'?: string;
}

/**
 * [Flow: Step 1 (req.headers에서 Authorization/X-Api-Key 읽기) -> Step 2 (JWT Bearer 형식 확인)
 *       -> Step 3 (ctx.authHeaders에 저장) -> Step 4 (next() 호출)]
 *
 * Express 미들웨어. 요청의 인증 헤더를 RequestContext에 담아 후속 핸들러에서 사용하도록 한다.
 *
 * @param req Express 요청
 * @param res Express 응답
 * @param next 다음 미들웨어
 */
export function authMiddleware(req: Request, res: Response, next: NextFunction) {
  const authHeaders: AuthHeaders = {};

  const authorization = req.headers.authorization;
  if (authorization && authorization.startsWith('Bearer ')) {
    authHeaders.Authorization = authorization;
  }

  const apiKey = req.headers['x-api-key'];
  if (apiKey && typeof apiKey === 'string') {
    authHeaders['X-Api-Key'] = apiKey;
  }

  // [debug] 인증 헤더 전달 상태 로깅
  console.log(`[auth] ${req.method} ${req.path} | authorization=${authorization ? 'YES(' + authorization.slice(0, 20) + '...)' : 'NO'} | x-api-key=${apiKey ? 'YES' : 'NO'} | authHeaders keys=${Object.keys(authHeaders).join(',') || 'empty'}`);

  (req as any).authHeaders = authHeaders;
  next();
}

/**
 * [Flow: Step 1 (req에서 authHeaders 추출) -> Step 2 (값 반환)]
 *
 * @param req Express 요청
 * @returns FastAPI 호출용 인증 헤더
 */
export function getAuthHeaders(req: Request): AuthHeaders {
  return ((req as any).authHeaders as AuthHeaders) || {};
}
