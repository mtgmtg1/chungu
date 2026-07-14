const { marked } = require('marked');
const md = `# 제목

## 섹션 1

본문 단락입니다.

![이미지 설명](https://example.com/image.png)

- 항목 1
- 항목 2
- 항목 3

| 컬럼 A | 컬럼 B |
|--------|--------|
| 값 1   | 값 2   |

` + '```python\nprint("hello")\n```\n\n' + `> 인용구입니다.

<video src="https://example.com/video.mp4" />

추가 본문입니다.
`;
const tokens = marked.lexer(md);
tokens.forEach((t, i) => {
  const info = {
    type: t.type,
    depth: t.depth,
    text: (t.text || '').slice(0, 60),
    lang: t.lang,
    itemsLen: t.items?.length,
    headerLen: t.header?.length,
    rowsLen: t.rows?.length,
    innerTokens: t.tokens?.map(x => x.type),
  };
  console.log(i, JSON.stringify(info));
});
