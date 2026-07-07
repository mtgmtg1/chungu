// [Flow: Step 1 (환경변수 로드) -> Step 2 (Express 앱 생성) -> Step 3 (미들웨어 등록)
//       -> Step 4 (/api/ai/chat 라우트 등록) -> Step 5 (HTTP 서버 시작)]
// Node.js AI 백엔드 진입점. 기존 Python FastAPI와 병렬로 운영되며,
// 프론트엔드 Vercel AI SDK useChat이 POST /api/ai/chat으로 연결한다.
import 'dotenv/config';
import cors from 'cors';
import express from 'express';
import { Readable } from 'node:stream';
import { chatHandler } from './chat/route.js';
import { authMiddleware } from './lib/auth.js';

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors({
  origin: process.env.CORS_ORIGIN || true,
  credentials: true,
}));
app.use(express.json({ limit: '10mb' }));
app.use(authMiddleware);

// [Flow: Step 1 (POST /api/ai/chat 요청 수신) -> Step 2 (chatHandler 실행)
//       -> Step 3 (UIMessage 스트림 반환)]
app.post('/api/ai/chat', async (req, res) => {
  try {
    const aiStreamResponse = await chatHandler(req, res);
    if (aiStreamResponse) {
      // createUIMessageStreamResponse가 Web API Response를 반환하면 body를 Node.js stream으로 변환해 Express res에 pipe
      const webResponse = aiStreamResponse as unknown as Response;
      res.status(webResponse.status);
      const contentType = webResponse.headers.get('content-type');
      if (contentType) res.setHeader('Content-Type', contentType);
      if (webResponse.body) {
        const nodeStream = Readable.fromWeb(webResponse.body as any);
        nodeStream.pipe(res);
      } else {
        res.end();
      }
    }
  } catch (error) {
    console.error('[chat] error:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    if (!res.headersSent) {
      res.status(500).json({ error: message });
    }
  }
});

// [Flow: Step 1 (GET /health 요청) -> Step 2 (상태 반환)]
app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.listen(PORT, () => {
  console.log(`[proof-ai-backend] listening on port ${PORT}`);
});
