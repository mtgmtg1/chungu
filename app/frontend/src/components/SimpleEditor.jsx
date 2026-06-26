// [Flow: Step 1 (Tiptap 에디터 초기화) -> Step 2 (마크다운 prop을 HTML로 로드) -> Step 3 (풍부한 툴바 렌더링) -> Step 4 (사용자 편집 -> HTML -> 마크다운 반환)]
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Table } from '@tiptap/extension-table'
import { TableRow } from '@tiptap/extension-table-row'
import { TableCell } from '@tiptap/extension-table-cell'
import { TableHeader } from '@tiptap/extension-table-header'
import Underline from '@tiptap/extension-underline'
import Highlight from '@tiptap/extension-highlight'
import TextAlign from '@tiptap/extension-text-align'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import Link from '@tiptap/extension-link'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'
import { marked } from 'marked'
import TurndownService from 'turndown'
import {
  Bold, Italic, Underline as UnderlineIcon, Strikethrough, Highlighter,
  AlignLeft, AlignCenter, AlignRight, AlignJustify,
  List, ListOrdered, ListTodo, Link as LinkIcon, Image as ImageIcon, Table as TableIcon,
  Undo, Redo, Heading1, Heading2, Heading3, Heading4,
} from 'lucide-react'

const turndown = new TurndownService({
  headingStyle: 'atx',
  codeBlockStyle: 'fenced',
  emDelimiter: '_',
  strongDelimiter: '**',
})

turndown.addRule('table', {
  filter: 'table',
  replacement: function (content, node) {
    const rows = Array.from(node.querySelectorAll('tr'))
    if (!rows.length) return ''
    const lines = []
    rows.forEach((row, idx) => {
      const cells = Array.from(row.querySelectorAll('th, td')).map((cell) => cell.textContent.trim().replace(/\|/g, '\\|'))
      lines.push('| ' + cells.join(' | ') + ' |')
      if (idx === 0) {
        lines.push('| ' + cells.map(() => '---').join(' | ') + ' |')
      }
    })
    return '\n\n' + lines.join('\n') + '\n\n'
  },
})

function ToolbarButton({ onClick, active, disabled, children, title }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`p-1.5 rounded-md transition-colors ${
        active ? 'bg-primary text-white' : 'hover:bg-surface-container-high text-on-surface'
      } disabled:opacity-40`}
    >
      {children}
    </button>
  )
}

function ToolbarDivider() {
  return <div className="w-px h-5 bg-outline-variant mx-1"></div>
}

const SimpleEditor = forwardRef(function SimpleEditor({ markdown, editable = true }, ref) {
  const { t } = useTranslation()
  const [headingOpen, setHeadingOpen] = useState(false)

  const editor = useEditor({
    extensions: [
      StarterKit,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      Underline,
      Highlight,
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Link.configure({ openOnClick: false, autolink: true }),
      Image,
      Placeholder.configure({ placeholder: t('page:components.editorPlaceholder') }),
    ],
    content: '',
    editable,
  })

  useEffect(() => {
    if (!editor || !markdown) return
    editor.commands.setContent(marked.parse(markdown), false)
  }, [editor, markdown])

  useImperativeHandle(ref, () => ({
    getMarkdown: () => (editor ? turndown.turndown(editor.getHTML()) : ''),
  }), [editor])

  if (!editor) return null

  const toggleLink = () => {
    if (editor.isActive('link')) {
      editor.chain().focus().unsetLink().run()
      return
    }
    const url = window.prompt(t('page:components.linkUrl'), 'https://')
    if (url) editor.chain().focus().setLink({ href: url }).run()
  }

  const addImage = () => {
    const url = window.prompt(t('page:components.imageUrl'), 'https://')
    if (url) editor.chain().focus().setImage({ src: url }).run()
  }

  const addTable = () => {
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
  }

  const headingIcon = editor.isActive('heading', { level: 1 })
    ? Heading1
    : editor.isActive('heading', { level: 2 })
    ? Heading2
    : editor.isActive('heading', { level: 3 })
    ? Heading3
    : Heading4

  const HeadingIcon = headingIcon

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="flex items-center gap-1 px-3 py-2 border-b border-outline-variant bg-surface flex-wrap">
        <ToolbarButton onClick={() => editor.chain().focus().undo().run()} disabled={!editor.can().undo()} title={t('page:components.undo')}>
          <Undo size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().redo().run()} disabled={!editor.can().redo()} title={t('page:components.redo')}>
          <Redo size={18} />
        </ToolbarButton>
        <ToolbarDivider />

        <div className="relative">
          <ToolbarButton onClick={() => setHeadingOpen((v) => !v)} active={editor.isActive('heading')} title={t('page:components.heading')}>
            <HeadingIcon size={18} />
          </ToolbarButton>
          {headingOpen && (
            <div className="absolute top-full left-0 mt-1 bg-white rounded-lg shadow-lg border border-outline-variant p-1 z-50 flex flex-col gap-0.5">
              {[1, 2, 3, 4].map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => {
                    editor.chain().focus().toggleHeading({ level }).run()
                    setHeadingOpen(false)
                  }}
                  className={`px-3 py-1.5 rounded text-sm text-left hover:bg-surface-container-high ${
                    editor.isActive('heading', { level }) ? 'bg-primary-container/10 text-primary font-bold' : 'text-on-surface'
                  }`}
                >
                  {t('page:components.headingN', { level })}
                </button>
              ))}
              <button
                type="button"
                onClick={() => {
                  editor.chain().focus().setParagraph().run()
                  setHeadingOpen(false)
                }}
                className="px-3 py-1.5 rounded text-sm text-left hover:bg-surface-container-high text-on-surface"
              >
                {t('page:components.paragraph')}
              </button>
            </div>
          )}
        </div>
        <ToolbarDivider />

        <ToolbarButton onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive('bold')} title={t('page:components.bold')}>
          <Bold size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive('italic')} title={t('page:components.italic')}>
          <Italic size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleUnderline().run()} active={editor.isActive('underline')} title={t('page:components.underline')}>
          <UnderlineIcon size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleStrike().run()} active={editor.isActive('strike')} title={t('page:components.strikethrough')}>
          <Strikethrough size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleHighlight().run()} active={editor.isActive('highlight')} title={t('page:components.highlight')}>
          <Highlighter size={18} />
        </ToolbarButton>
        <ToolbarDivider />

        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign('left').run()} active={editor.isActive({ textAlign: 'left' })} title={t('page:components.alignLeft')}>
          <AlignLeft size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign('center').run()} active={editor.isActive({ textAlign: 'center' })} title={t('page:components.alignCenter')}>
          <AlignCenter size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign('right').run()} active={editor.isActive({ textAlign: 'right' })} title={t('page:components.alignRight')}>
          <AlignRight size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().setTextAlign('justify').run()} active={editor.isActive({ textAlign: 'justify' })} title={t('page:components.alignJustify')}>
          <AlignJustify size={18} />
        </ToolbarButton>
        <ToolbarDivider />

        <ToolbarButton onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive('bulletList')} title={t('page:components.bulletList')}>
          <List size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive('orderedList')} title={t('page:components.orderedList')}>
          <ListOrdered size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={() => editor.chain().focus().toggleTaskList().run()} active={editor.isActive('taskList')} title={t('page:components.taskList')}>
          <ListTodo size={18} />
        </ToolbarButton>
        <ToolbarDivider />

        <ToolbarButton onClick={toggleLink} active={editor.isActive('link')} title={t('page:components.link')}>
          <LinkIcon size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={addImage} title={t('page:components.image')}>
          <ImageIcon size={18} />
        </ToolbarButton>
        <ToolbarButton onClick={addTable} active={editor.isActive('table')} title={t('page:components.table')}>
          <TableIcon size={18} />
        </ToolbarButton>
      </div>
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <EditorContent editor={editor} className="prose max-w-none focus:outline-none" />
      </div>
    </div>
  )
})

export default SimpleEditor
