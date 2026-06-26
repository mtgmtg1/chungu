// [Flow: Step 1 (페이지 메타데이터 로드) -> Step 2 (현재 페이지 markdown/이미지/PDF 동기 로드) -> Step 3 (SimpleEditor로 페이지 편집) -> Step 4 (페이지 선택/저장/이동)]
import { useEffect, useRef, useState, useCallback } from 'react'
import { Virtuoso } from 'react-virtuoso'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { ChevronLeft, ChevronRight, Save, Loader2, Check, FileText, ImageIcon } from 'lucide-react'
import { api } from '../api.js'
import PdfViewer from './PdfViewer.jsx'
import MediaPlayer from './MediaPlayer.jsx'
import SimpleEditor from './SimpleEditor.jsx'

export default function PagedResultViewer({ jobId, pages, sourceUrl, sourceType, sidebarOpen = true }) {
  const [currentPage, setCurrentPage] = useState(pages[0]?.page_num || 1)
  const [pageMarkdown, setPageMarkdown] = useState('')
  const [loadingPage, setLoadingPage] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState('')
  const [error, setError] = useState('')
  const editorRef = useRef(null)

  const currentPageInfo = pages.find((p) => p.page_num === currentPage) || null
  const imageUrl = sourceType === 'images' ? currentPageInfo?.image_url : null

  const loadPage = useCallback(async (pageNum) => {
    setLoadingPage(true)
    setError('')
    try {
      const preview = await api.previewJob(jobId, pageNum, pageNum)
      setPageMarkdown(preview.markdown || '')
      setCurrentPage(preview.start_page || pageNum)
    } catch (e) {
      setError(e.message || '페이지를 불러오지 못했습니다')
    } finally {
      setLoadingPage(false)
    }
  }, [jobId])

  useEffect(() => {
    loadPage(currentPage)
  }, [currentPage, loadPage])

  const saveCurrentPage = async () => {
    if (!editorRef.current) return
    const updated = editorRef.current.getMarkdown()
    setSaving(true)
    setSaveMessage('')
    setError('')
    try {
      await api.saveResultPage(jobId, currentPage, updated)
      setSaveMessage('저장되었습니다')
      setTimeout(() => setSaveMessage(''), 2000)
    } catch (e) {
      setError(e.message || '저장에 실패했습니다')
    } finally {
      setSaving(false)
    }
  }

  const goToPage = (next) => {
    const nums = pages.map((p) => p.page_num)
    const min = Math.min(...nums)
    const max = Math.max(...nums)
    setCurrentPage(Math.min(Math.max(next, min), max))
  }

  const totalPages = pages.length

  const renderSourcePanel = () => {
    if (sourceType === 'pdf' && sourceUrl) {
      return <PdfViewer url={sourceUrl} page={currentPage} onPageChange={setCurrentPage} />
    }
    if (sourceType === 'images' && imageUrl) {
      return (
        <div className="flex-1 flex flex-col overflow-hidden bg-surface-container-low">
          <div className="h-12 border-b border-outline-variant bg-white flex items-center px-3 flex-shrink-0">
            <ImageIcon size={16} className="text-outline mr-2" />
            <span className="text-sm font-medium text-on-surface truncate">원본 이미지</span>
          </div>
          <div className="flex-1 overflow-auto custom-scrollbar p-4 flex items-center justify-center">
            <img
              src={imageUrl}
              alt={`페이지 ${currentPage}`}
              className="max-w-full max-h-full object-contain shadow-lg rounded border border-outline-variant bg-white"
            />
          </div>
        </div>
      )
    }
    if ((sourceType === 'audio' || sourceType === 'video') && sourceUrl) {
      return <MediaPlayer sourceType={sourceType} url={sourceUrl} filename="" />
    }
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm p-4">
        원본 파일을 표시할 수 없습니다
      </div>
    )
  }

  const hasSourcePanel = sourceType === 'pdf' || sourceType === 'images' || sourceType === 'audio' || sourceType === 'video'

  return (
    <div className="flex-1 flex overflow-hidden">
      <PanelGroup direction="horizontal">
        {sidebarOpen && (
          <>
            <Panel defaultSize={20} minSize={15} maxSize={35} className="border-r border-outline-variant bg-surface flex flex-col">
              <div className="p-3 border-b border-outline-variant bg-surface-container-low">
                <p className="text-xs font-bold text-on-surface-variant uppercase tracking-wider">페이지 목록</p>
                <p className="text-xs text-outline mt-1">총 {totalPages}페이지</p>
              </div>
              <div className="flex-1 overflow-hidden">
                <Virtuoso
                  data={pages}
                  itemContent={(idx, page) => (
                    <button
                      onClick={() => setCurrentPage(page.page_num)}
                      className={`w-full text-left px-3 py-2 border-b border-outline-variant/50 text-sm transition-colors ${
                        currentPage === page.page_num ? 'bg-primary-container/10 text-primary font-bold' : 'text-on-surface hover:bg-surface-container-high'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <FileText size={14} className="text-outline flex-shrink-0" />
                        <span className="truncate">{page.page_num}페이지</span>
                      </div>
                      <p className="text-xs text-outline truncate mt-0.5 pl-5">{page.preview}</p>
                    </button>
                  )}
                />
              </div>
            </Panel>
            <PanelResizeHandle className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors" />
          </>
        )}

        <Panel className="flex-1 flex flex-col overflow-hidden">
          <div className="h-12 border-b border-outline-variant bg-white flex items-center justify-between px-4 flex-shrink-0">
            <div className="flex items-center gap-2">
              <button
                onClick={() => goToPage(currentPage - 1)}
                className="p-1.5 rounded hover:bg-surface-container-high"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-sm font-medium text-on-surface">
                {currentPage} / {totalPages}
              </span>
              <button
                onClick={() => goToPage(currentPage + 1)}
                className="p-1.5 rounded hover:bg-surface-container-high"
              >
                <ChevronRight size={18} />
              </button>
            </div>
            <div className="flex items-center gap-2">
              {saveMessage && (
                <span className="text-xs text-green-600 flex items-center gap-1">
                  <Check size={12} />
                  {saveMessage}
                </span>
              )}
              <button
                onClick={saveCurrentPage}
                disabled={saving}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-sm font-bold hover:opacity-90 disabled:opacity-50"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                저장
              </button>
            </div>
          </div>

          {error && (
            <div className="bg-red-50 text-red-700 px-4 py-2 text-sm flex items-center gap-2 border-b border-red-200 flex-shrink-0">
              {error}
            </div>
          )}

          {hasSourcePanel ? (
            <PanelGroup direction="horizontal" className="flex-1 overflow-hidden">
              <Panel defaultSize={45} minSize={25} maxSize={70} className="overflow-hidden">
                {renderSourcePanel()}
              </Panel>
              <PanelResizeHandle className="w-1 bg-outline-variant/50 hover:bg-primary/30 transition-colors" />
              <Panel defaultSize={55} minSize={30} maxSize={75} className="flex flex-col bg-white overflow-hidden">
                {loadingPage ? (
                  <div className="flex-1 flex items-center justify-center">
                    <Loader2 className="animate-spin text-primary" size={24} />
                  </div>
                ) : (
                  <SimpleEditor ref={editorRef} markdown={pageMarkdown} editable />
                )}
              </Panel>
            </PanelGroup>
          ) : (
            <div className="flex-1 flex flex-col bg-white overflow-hidden">
              {loadingPage ? (
                <div className="flex-1 flex items-center justify-center">
                  <Loader2 className="animate-spin text-primary" size={24} />
                </div>
              ) : (
                <SimpleEditor ref={editorRef} markdown={pageMarkdown} editable />
              )}
            </div>
          )}
        </Panel>
      </PanelGroup>
    </div>
  )
}
