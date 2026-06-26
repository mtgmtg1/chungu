// [Flow: Step 1 (source_type/URL 수신) -> Step 2 (audio/video 태그 선택) -> Step 3 (컨트롤 제공)]
import { Volume2, Film } from 'lucide-react'

export default function MediaPlayer({ sourceType, url, filename }) {
  const isAudio = sourceType === 'audio'
  const isVideo = sourceType === 'video'
  if (!isAudio && !isVideo) return null

  return (
    <div className="flex flex-col h-full border-r border-outline-variant bg-surface-container-low">
      <div className="p-4 flex items-center justify-between border-b border-outline-variant bg-white flex-shrink-0">
        <h3 className="font-bold text-sm text-on-surface flex items-center gap-2">
          {isAudio ? <Volume2 size={16} /> : <Film size={16} />}
          원본 {isAudio ? '오디오' : '비디오'}
        </h3>
        <span className="text-[10px] text-outline font-mono bg-surface px-1.5 py-0.5 rounded border border-outline-variant truncate max-w-[200px]">
          {filename}
        </span>
      </div>
      <div className="flex-1 min-h-0 flex items-center justify-center p-4">
        {isAudio ? (
          <audio controls src={url} className="w-full max-w-md">
            브라우저가 오디오 재생을 지원하지 않습니다.
          </audio>
        ) : (
          <video controls src={url} className="max-w-full max-h-full rounded border border-outline-variant shadow-sm bg-black">
            브라우저가 비디오 재생을 지원하지 않습니다.
          </video>
        )}
      </div>
    </div>
  )
}
